# Local AI Stack — Implementation Status

> **Date:** 2026-03-18
> **Original plan:** [local-summarize-embed-plan.md](local-summarize-embed-plan.md)
> **Branch:** lore-library

---

## What's Done

Everything from the original Milestone 1 plan is implemented and working, plus conversation condensation and a playground UI that were added on top.

### Backend Stack (wingman-ai)

#### Model Management — `services/local_model_manager.py`

- Downloads GGUF models + `llama-server` binary from HuggingFace on first use
- Stores in non-versioned `{AppData}/WingmanAI/local_models/`
- Platform-aware: macOS arm64/x64, Windows cpu/cuda/vulkan, Linux x86_64
- `llama-server` version pinned to `b8400`
- Models:
  - **Summarize:** `Qwen3.5-0.8B-Q4_K_M.gguf` (~500 MB)
  - **Embed:** `nomic-embed-text-v1.5.f16.gguf` (~250 MB)

#### Local Provider — `providers/llama_cpp_provider.py`

- Manages two `llama-server` subprocesses (not `llama-cpp-python` — switched to standalone binary for simpler deployment)
- Fixed ports: `49172` (summarize), `49173` (embed)
- OpenAI-compatible API calls via `openai.OpenAI(base_url=...)`
- GPU offload with `-ngl 99`, thread cap at 8
- `summarize()`: `max_tokens=512, temperature=0.3`
- `embed()`: returns float arrays via `/v1/embeddings`
- `is_ready()`: checks both servers are responsive

#### Remote Provider — `providers/llama_cpp_remote.py`

- Same interface as local provider
- Two separate endpoints (summarize host:port, embed host:port)
- Uses `openai.OpenAI(base_url=...)` against user-specified remote `llama-server`

#### Facade — `services/local_ai_service.py`

- Routes `summarize()` / `embed()` / `is_ready()` to local or remote provider based on `settings.llama_cpp.run_locally`
- `update_settings_async()` handles toggle: unloads local models when switching to remote
- `initialize()` eagerly loads local models on startup

#### Config Models — `api/interface.py`

```python
class LlamaCppSettings(BaseModel):
    run_locally: bool = False
    gpu_backend: str = "vulkan"
    summarize_model: str = "Qwen3.5-0.8B-Q4_K_M.gguf"
    embed_model: str = "nomic-embed-text-v1.5.f16.gguf"
    n_ctx: int = 2048
    n_threads: int = 0       # 0 = auto
    reasoning_effort: int = 0  # 0 = disabled
    summarize_remote_host/port, embed_remote_host/port
```

Added to `FeaturesConfig`:

```python
condense_conversation: bool = False
condense_threshold: int = 20    # user messages before auto-trigger
condense_keep_recent: int = 6   # recent messages kept verbatim
```

`PlaygroundChatRequest`: `system_message` + `user_message` (used by playground chat endpoint).

#### Settings YAML — `templates/configs/settings.yaml`

`llama_cpp:` section with all defaults matching the Pydantic model.

#### Defaults YAML — `templates/configs/defaults.yaml`

- `{conversation_summary}` placeholder added to system prompt (between `{skills}` and CONVERSATION STYLE)
- `condense_conversation`, `condense_threshold`, `condense_keep_recent` in `features:` section

#### API Routes — `wingman_core.py`

| Route                                     | Method | Purpose                                           |
| :---------------------------------------- | :----- | :------------------------------------------------ |
| `/settings/local-ai/status`               | GET    | Model download state, loaded state                |
| `/settings/local-ai/backends`             | GET    | Platform-specific GPU backends                    |
| `/settings/local-ai/download-models`      | POST   | Trigger model + binary download                   |
| `/settings/local-ai/playground/chat`      | POST   | Test summarization model                          |
| `/settings/local-ai/playground/embed`     | POST   | Test embedding model                              |
| `/settings/local-ai/playground/benchmark` | POST   | Timed benchmarks (1–20 iterations)                |
| `/local-ai/summarize`                     | POST   | Public summarize endpoint                         |
| `/local-ai/embed`                         | POST   | Public embed endpoint                             |
| `/condense-conversation`                  | POST   | Manual condensation trigger                       |
| `/reset-conversation-history`             | POST   | Clear history (existing, now also clears summary) |

`local_ai_service` injected into all `OpenAiWingman` instances in `initialize_tower()`.

#### Settings Service Integration — `services/settings_service.py`

- `save_settings()` calls `local_ai_service.update_settings_async()` when `llama_cpp` config changes
- Handles local↔remote toggle with model load/unload

---

### Conversation Condensation (wingman-ai)

#### Core Logic — `wingmen/open_ai_wingman.py`

**Fields:**

- `conversation_summary: str` — running summary of condensed older messages
- `_is_condensing: bool` — prevents concurrent condensation

**Methods:**

| Method                      | Purpose                                                                                         |
| :-------------------------- | :---------------------------------------------------------------------------------------------- |
| `_maybe_condense_history()` | Auto-trigger: checks all conditions, fires background task via `asyncio.create_task()`          |
| `_condense_history(force)`  | Does the work: snapshots messages, calls local AI, replaces old messages, broadcasts WS command |
| `_chunked_summarize()`      | Handles text exceeding model context window — splits into chunks, summarizes each, merges       |
| `_messages_to_text()`       | Converts message list to plain text (includes tool call names/args/results)                     |
| `_message_text_content()`   | Extracts text from message objects (supports dict & ChatCompletionMessage)                      |

**How it works:**

1. After each user message, `_maybe_condense_history()` checks: feature enabled, local AI ready, no pending tool calls, not already condensing, user message count ≥ threshold
2. If all pass, fires `asyncio.create_task(_condense_history())` — **never blocks the user**
3. `_condense_history()` finds a cutoff point (keeping `keep_recent` user messages + their responses), adjusts boundary to avoid orphaning tool call/response pairs
4. Builds a summarization prompt that includes any existing summary for incremental merge
5. If text exceeds model's context window, uses `_chunked_summarize()` to split/merge
6. Runs summarization in thread executor (`run_in_executor`) to avoid blocking event loop
7. Replaces old messages with nothing; summary goes into system prompt via `{conversation_summary}` placeholder in `get_context()`
8. Broadcasts `ConversationCondensationCommand` via WebSocket at start and finish
9. Manual trigger via `POST /condense-conversation` calls `_condense_history(force=True)` — skips threshold check, reduces `keep_recent` to `min(config, 2)`

**WebSocket Command — `api/commands.py`:**

```python
class ConversationCondensationCommand(WebSocketCommandModel):
    command: Literal["conversation_condensation"]
    wingman_name: str
    status: str  # "started" | "finished"
    messages_condensed: Optional[int]
    messages_remaining: Optional[int]
    summary_length: Optional[int]
    estimated_tokens_saved: Optional[int]
    summary_text: Optional[str]  # full summary on finish
```

**System prompt integration:**

- `get_context()` replaces `{conversation_summary}` placeholder with the summary text
- Falls back to appending if placeholder is missing
- `reset_conversation_history()` clears `conversation_summary`

---

### Frontend — Settings UI (wingman-client)

#### LlamaCppSettings.svelte

Settings component in the Settings page:

- **Run locally toggle** — auto-downloads models if needed
- **Model status badge** — ready / downloading / not_downloaded
- **Download Models button** — triggers async download
- **GPU backend selector** — shows available backends with availability icons
- **Local mode fields:** model filenames, context size slider (512→32K with 7 tick marks), CPU threads, reasoning effort
- **Remote mode fields:** summarize host/port, embed host/port

#### LocalAiPlayground.svelte

Drawer accessible from Settings with 3 tabs:

- **Chat tab:** system prompt + user message → send → response + inference time
- **Embed tab:** multi-line text input → compute → results grid (text, dimensions, vector preview, copy)
- **Benchmark tab:** iterations → run → summary cards (total time, avg summarize, avg embed) + expandable detailed results table

Pre-populated with Star Citizen example data for testing.

#### ConfigBar.svelte — Toolbar

Three states for the condensation area (visible when a wingman is focused):

1. **Condensing:** Yellow spinner + "Summarizing..." text
2. **Summary available:** `BrainCircuit` icon button (variant-soft-primary) — click opens modal with full summary text. Condense (`Shrink`) button alongside for re-triggering.
3. **No summary yet:** Only the condense (`Shrink`) button

#### WebSocket Integration — +layout.svelte

- Registers handler for `conversation_condensation` command
- On `started`: adds wingman name to `condensingWingmen` store (Set)
- On `finished`: removes from set, stores `summary_text` into `wingmanSummaries` store

#### Stores — stores.ts

- `condensingWingmen: writable<Set<string>>` — tracks active condensations
- `wingmanSummaries: writable<Record<string, string>>` — maps wingman name → last summary

#### CoreService.ts

New methods: `condenseConversation()`, `getLocalAiStatus()`, `getLocalAiBackends()`, `downloadLocalAiModels()`, `playgroundChat()`, `playgroundEmbed()`, `playgroundBenchmark()`

#### Localization (en/de/fr/es)

All keys added to 4 locales:

- `settings_local_ai_*` — Settings UI labels/hints
- `playground_*` — Playground tab labels, buttons, placeholders
- `condense_conversation` / `condensing_conversation` — toolbar
- `conversation_summary` / `view_summary` — summary viewer modal

---

## What's Left (Remaining from Original Plan)

### Deployment Pipeline (Phase 4 — untested)

| Task                                              | Status                                                                                          |
| :------------------------------------------------ | :---------------------------------------------------------------------------------------------- |
| PyInstaller builds (`build.py`, `build_macos.py`) | **Not verified** — need to confirm `llama-server` binary and `sqlite-vec` are bundled correctly |
| Tauri bundling (`tauri.conf.json`)                | **Not verified** — need to confirm `_internal/` picks up all binaries                           |
| Installer (`installer.iss`)                       | **Not verified** — need to confirm recursive copy                                               |
| Windows test build                                | **Not done**                                                                                    |
| macOS test build                                  | **Not done**                                                                                    |

### Lore Library Stub (Phase 3, Step 10)

The original plan called for gutting `services/lore_library.py` to a stub. This was **not done** — the existing lore library code is still intact. This is fine since it's separate from Milestone 1 and will be rebuilt in Milestone 2 with sqlite-vec.

### sqlite-vec

Dependency added to `requirements.txt` but unused. Reserved for Milestone 2 (Lore Library rebuild with vector search).

---

## Architecture Deviation from Plan

| Original Plan                         | Actual Implementation            | Reason                                                                            |
| :------------------------------------ | :------------------------------- | :-------------------------------------------------------------------------------- |
| `llama-cpp-python` (Python bindings)  | `llama-server` standalone binary | Simpler deployment, no C extension compilation issues, same OpenAI-compatible API |
| CPU-only for Milestone 1              | GPU offload enabled (`-ngl 99`)  | Works out of the box with llama-server, no extra build flags needed               |
| Conversation condensation not in plan | Fully implemented                | Natural use case for the summarization model — auto-compresses long conversations |
| Playground not in plan                | Fully implemented                | Needed for testing/debugging models during development, useful for users too      |
| Context size slider not in plan       | Implemented (512→32K)            | Important for tuning model performance vs quality                                 |

---

## File Inventory

### New Files

| File                                                 | Description                              |
| :--------------------------------------------------- | :--------------------------------------- |
| `services/local_model_manager.py`                    | Model + binary download management       |
| `services/local_ai_service.py`                       | Facade routing local vs. remote          |
| `providers/llama_cpp_provider.py`                    | Local llama-server subprocess management |
| `providers/llama_cpp_remote.py`                      | Remote OpenAI-compatible client          |
| `src/routes/(app)/settings/LlamaCppSettings.svelte`  | Settings component                       |
| `src/routes/(app)/settings/LocalAiPlayground.svelte` | Test playground drawer                   |
| `src/api/models/ConversationCondensationCommand.ts`  | TS type for WS command                   |
| `src/api/models/PlaygroundChatRequest.ts`            | TS type for chat endpoint                |

### Modified Files

| File                                     | Changes                                                                       |
| :--------------------------------------- | :---------------------------------------------------------------------------- |
| `api/interface.py`                       | `LlamaCppSettings`, `FeaturesConfig` condense fields, `PlaygroundChatRequest` |
| `api/commands.py`                        | `ConversationCondensationCommand`                                             |
| `wingman_core.py`                        | All new routes, service initialization, injection                             |
| `wingmen/open_ai_wingman.py`             | Condensation logic, summary integration                                       |
| `services/settings_service.py`           | `local_ai_service` update on settings save                                    |
| `services/file.py`                       | `get_local_models_dir()` helper                                               |
| `templates/configs/defaults.yaml`        | Condense config, `{conversation_summary}` placeholder                         |
| `templates/configs/settings.yaml`        | `llama_cpp:` section                                                          |
| `src/routes/(app)/settings/+page.svelte` | LlamaCppSettings + playground button                                          |
| `src/lib/ConfigBar.svelte`               | Condense button, spinner, summary viewer                                      |
| `src/routes/(app)/+layout.svelte`        | WS handler for condensation                                                   |
| `src/services/stores.ts`                 | `condensingWingmen`, `wingmanSummaries`                                       |
| `src/services/index.ts`                  | Re-exports                                                                    |
| `src/services/websocketService.ts`       | `ConversationCondensationCommand` in CommandUnion                             |
| `src/api/services/CoreService.ts`        | All new service methods                                                       |
| `src/api/index.ts`                       | New type exports                                                              |
| `messages/en.json`                       | ~30 new keys                                                                  |
| `messages/de.json`                       | ~30 new keys                                                                  |
| `messages/fr.json`                       | ~30 new keys                                                                  |
| `messages/es.json`                       | ~30 new keys                                                                  |
