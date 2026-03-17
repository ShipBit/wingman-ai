# Plan: Local Summarize & Embed Stack (Milestone 1)

> **Status:** Approved for implementation  
> **Date:** 2026-03-17  
> **Branch:** lore-library (rebuild on top of existing client work)  
> **Research:** [perplexity-research.md](perplexity-research.md)  
> **Lore Library Spec:** [2026-03-16-lore-library-design.md](2026-03-16-lore-library-design.md)

## TL;DR

Replace the current Lore Library SQLite-only approach with a unified **llama.cpp** stack for local summarization (**Qwen 3.5-0.8B**) and embedding (**nomic-embed-text-v1.5**), stored via **sqlite-vec**. This milestone wires up the new dependencies, deployment pipeline, and settings UI — but does **not** rebuild the Lore Library itself.

**Stack:** `llama-cpp-python` + `sqlite-vec` + two GGUF models (~800MB total, downloaded on first use).

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Wingman Client (Tauri/Svelte)               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Settings Page                                            │   │
│  │  ┌─────────────────────────────────────────────────────┐ │   │
│  │  │ Local AI Section                                    │ │   │
│  │  │  [x] Run locally (toggle)                           │ │   │
│  │  │  [ ] Download Models (button / status badge)        │ │   │
│  │  │  --- or when toggle off ---                         │ │   │
│  │  │  Summarize Remote: host [ ] port [ ]                │ │   │
│  │  │  Embed Remote:     host [ ] port [ ]                │ │   │
│  │  └─────────────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────┘   │
│                          │ REST / WebSocket                     │
└──────────────────────────┼──────────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────────┐
│                   Wingman Core (Python / FastAPI)                │
│                          │                                      │
│  ┌───────────────────────▼──────────────────────────────┐       │
│  │            LocalAiService (facade)                   │       │
│  │   routes calls based on settings.run_locally         │       │
│  └──┬──────────────────────────────────────────┬────────┘       │
│     │ run_locally=true                         │ run_locally=   │
│     ▼                                          │ false          │
│  ┌──────────────────────┐    ┌─────────────────▼──────────┐    │
│  │ LlamaCppProvider     │    │ LlamaCppRemote             │    │
│  │ (llama-cpp-python)   │    │ (openai.OpenAI client)     │    │
│  │                      │    │                            │    │
│  │ Qwen 3.5-0.8B .gguf │    │ → summarize_remote:8080    │    │
│  │ nomic-embed    .gguf │    │ → embed_remote:8081        │    │
│  └──────────┬───────────┘    └────────────────────────────┘    │
│             │                                                   │
│  ┌──────────▼───────────┐                                       │
│  │ LocalModelManager    │                                       │
│  │ downloads GGUF models│                                       │
│  │ to AppData on first  │                                       │
│  │ use from HuggingFace │                                       │
│  └──────────────────────┘                                       │
│                                                                  │
│  ┌──────────────────────┐                                       │
│  │ sqlite-vec           │  (dependency present, unused until    │
│  │                      │   Lore Library rebuild in Milestone 2)│
│  └──────────────────────┘                                       │
└──────────────────────────────────────────────────────────────────┘
```

---

## Phase 1 — Backend Dependencies & Model Management

### Step 1: Add Python dependencies

- **File:** `requirements.txt`
- Add `llama-cpp-python` and `sqlite-vec`
- No fastembed / ONNX needed — llama.cpp handles both summarize and embed

### Step 2: Create model manager service

- **NEW file:** `services/local_model_manager.py`
- Responsibilities:
  - Download GGUF models from HuggingFace on first use
  - Store in non-versioned `{AppData}/WingmanAI/local_models/` (same pattern as `get_lore_library_dir()` in `services/file.py`)
  - Track download progress (log server-side via Printr, `server_only=True`)
  - Verify model files (expected file size check)
  - Expose: `get_summarize_model_path()`, `get_embed_model_path()`, `models_available() -> bool`
- **Models (pinned):**
  - **Summarize:** `Qwen3.5-0.8B-GGUF` — Q4_K_M quantization (~500 MB)
  - **Embed:** `nomic-embed-text-v1.5.f16.gguf` (~250 MB)
- Add `get_local_models_dir()` helper to `services/file.py` (non-versioned, persists across app updates)
- Reference pattern: `providers/faster_whisper.py` lines 71-72 (try local → fallback download)

### Step 3: Create llama.cpp local provider

- **NEW file:** `providers/llama_cpp_provider.py`
- Follow the `FasterWhisper` provider pattern (`providers/faster_whisper.py`):
  - `__init__(settings: LlamaCppSettings, model_manager: LocalModelManager)`
  - `load_summarize_model()` — load Qwen into `Llama()` instance
  - `load_embed_model()` — load Nomic into `Llama(embedding=True)` instance
  - `unload_models()` — `del model` + `gc.collect()` to free RAM
  - `update_settings(new_settings: LlamaCppSettings)` — unload/reload if config changed
  - `summarize(text: str, system_prompt: str) -> str` — Qwen chat completion
  - `embed(texts: list[str]) -> list[list[float]]` — Nomic embedding extraction
  - `is_ready() -> bool` — check if models are loaded and responsive
- On-demand model loading: models load on first `summarize()` / `embed()` call, not at startup
- Designed with `load()` / `unload()` for future idle-timeout support (Milestone 2)

### Step 4: Create remote llama.cpp client

- **NEW file:** `providers/llama_cpp_remote.py`
- Uses `openai.OpenAI(base_url=...)` — the same OpenAI-compatible API that `llama-server` exposes
- Two separate endpoint configs (summarize host:port, embed host:port)
- Same interface as local provider: `summarize()`, `embed()`, `is_ready()`
- Non-blocking connectivity validation on settings save (log warnings, don't block)

### Step 5: Create unified facade service

- **NEW file:** `services/local_ai_service.py`
- Single interface consumed by future Lore Library, persistent memory, etc.
- Routes calls based on settings:
  - `run_locally=True` → `LlamaCppProvider`
  - `run_locally=False` → `LlamaCppRemote`
- `update_settings()` handles toggling: True→False unloads local models; False→True triggers load
- Initialized in `wingman_core.py` alongside FasterWhisper / PocketTTS
- Registered with `SettingsService.initialize()` (extend existing signature)

---

## Phase 2 — Pydantic Models & Settings Config

### Step 6: Add interface models

- **File:** `api/interface.py`
- New Pydantic model (follow `FasterWhisperSettings` / `PocketTTSSettings` pattern):

```python
class LlamaCppSettings(BaseModel):
    run_locally: bool = True
    summarize_remote_host: str = "http://127.0.0.1"
    summarize_remote_port: int = 8080
    embed_remote_host: str = "http://127.0.0.1"
    embed_remote_port: int = 8081
```

- Add `llama_cpp: LlamaCppSettings` field to `SettingsConfig` (alongside `pocket_tts`, `xvasynth`, etc.)

### Step 7: Add settings.yaml defaults

- **File:** `templates/configs/settings.yaml`
- New section:

```yaml
llama_cpp:
  run_locally: true
  summarize_remote_host: "http://127.0.0.1"
  summarize_remote_port: 8080
  embed_remote_host: "http://127.0.0.1"
  embed_remote_port: 8081
```

---

## Phase 3 — Core Wiring

### Step 8: Initialize in wingman_core.py

- **File:** `wingman_core.py`
- In the startup sequence (around line 564-575 where FasterWhisper / PocketTTS are created):
  1. Instantiate `LocalModelManager`
  2. Instantiate `LlamaCppProvider(settings, model_manager)`
  3. Instantiate `LlamaCppRemote(settings)`
  4. Instantiate `LocalAiService(provider, remote, settings)`
  5. Pass `local_ai_service` to `SettingsService.initialize()`
- Add API endpoints:
  - `GET /settings/local-ai/status` → returns model download state, loaded state, RAM usage estimate
  - `POST /settings/local-ai/download-models` → triggers model download (async, returns immediately)
- Log model readiness server-side via Printr (`color=LogType.INFO`, `server_only=True`)

### Step 9: Update SettingsService

- **File:** `services/settings_service.py`
- Extend `initialize()` to accept `local_ai_service` parameter
- In `save_settings()`, call `local_ai_service.update_settings()` when `llama_cpp` config changes
- Handle toggle: `run_locally` True→False unloads local models; False→True triggers load

### Step 10: Gut lore_library.py to stub

- **File:** `services/lore_library.py`
- Remove: all SQLite schema, CRUD methods, LLM tool schemas, backstory generation
- Keep: class shell with `__init__`, docstring noting *"Pending rebuild with sqlite-vec + llama.cpp stack"*
- In `wingman_core.py`: keep route stubs but make them return `501 Not Implemented`
- **Do NOT touch** any client-side Lore Library files (LoreLibrary.svelte, TS models, CoreService methods)

---

## Phase 4 — Deployment Pipeline

### Step 11: Update PyInstaller builds

- **Files:** `build.py`, `build_macos.py`
- No model bundling (downloaded on first use to AppData)
- Verify `llama-cpp-python` and `sqlite-vec` C extensions are included:
  - May need `--hidden-import llama_cpp` and `--collect-all sqlite_vec`
  - May need `--collect-binaries llama_cpp` for native shared libs
- Test on both Windows and macOS

### Step 12: Verify Tauri bundling

- **File:** `src-tauri/tauri.conf.json` (wingman-client)
- No new `bundle.resources` entries needed (models download to AppData, not bundled)
- Verify `_internal/` includes llama_cpp shared libraries (.dll on Windows, .dylib on macOS)

### Step 13: Verify installer

- **File:** `src-tauri/installer.iss` (wingman-client)
- No model files to add
- Verify `_internal/` recursive copy picks up llama_cpp native libs

### Step 14: Git LFS check

- **File:** `src-tauri/.gitattributes` (wingman-client)
- No new LFS entries needed (models not stored in repo)

---

## Phase 5 — Client Settings UI

### Step 15: Add localization keys

- **Files:** `messages/en.json`, `de.json`, `es.json`, `fr.json` (wingman-client)
- New keys (en.json values shown; other languages get English text as placeholder):

```json
"settings_local_ai": "Local AI",
"settings_local_ai_hint": "Run small local models for summarization and embedding. Used by the Lore Library and persistent memory features. When disabled, connect to a remote llama.cpp server instead.",
"settings_local_ai_run_locally": "Run models locally",
"settings_local_ai_run_locally_description": "When enabled, Wingman loads small AI models (~800 MB) on your machine. Disable this to offload to a remote llama.cpp server.",
"settings_local_ai_summarize_remote": "Summarize Model (Remote)",
"settings_local_ai_summarize_remote_host": "Host",
"settings_local_ai_summarize_remote_port": "Port",
"settings_local_ai_embed_remote": "Embed Model (Remote)",
"settings_local_ai_embed_remote_host": "Host",
"settings_local_ai_embed_remote_port": "Port",
"settings_local_ai_download_models": "Download Models",
"settings_local_ai_models_ready": "Models ready",
"settings_local_ai_models_downloading": "Downloading models...",
"settings_local_ai_models_not_downloaded": "Models not downloaded"
```

### Step 16: Create LlamaCppSettings.svelte component

- **NEW file:** `src/routes/(app)/settings/LlamaCppSettings.svelte` (wingman-client)
- Follow `PocketTTSSettings.svelte` pattern:
  - `HintedSection` wrapper with `settings_local_ai` / `settings_local_ai_hint`
  - `SlideToggle` for `run_locally` (default: on)
  - When **on**: status badge (ready / downloading / not downloaded) + "Download Models" button
  - When **off**: two expandable sections:
    - Summarize Remote: host input + port input
    - Embed Remote: host input + port input
  - All inputs dispatch `configChanged` event on change

### Step 17: Wire into settings page

- **File:** `src/routes/(app)/settings/+page.svelte` (wingman-client)
- Add new "Local AI" `HintedSection` after the TTS section, before HUD Overlay
- Import and render `LlamaCppSettings` component
- Wire `configChanged` handler into existing save-settings flow

---

## File Change Summary

### Backend — wingman-ai

| File | Action | Description |
|:-----|:-------|:------------|
| `requirements.txt` | **Edit** | Add `llama-cpp-python`, `sqlite-vec` |
| `api/interface.py` | **Edit** | Add `LlamaCppSettings` model, extend `SettingsConfig` |
| `templates/configs/settings.yaml` | **Edit** | Add `llama_cpp:` section with defaults |
| `services/file.py` | **Edit** | Add `get_local_models_dir()` helper |
| `services/settings_service.py` | **Edit** | Extend `initialize()` and `save_settings()` |
| `services/lore_library.py` | **Edit** | Gut to stub (keep class shell, remove all logic) |
| `wingman_core.py` | **Edit** | Initialize new services, add status/download endpoints, stub lore routes |
| `build.py` | **Edit** | Add hidden imports / collect-binaries for llama_cpp, sqlite_vec |
| `build_macos.py` | **Edit** | Same as above for macOS |
| `services/local_model_manager.py` | **NEW** | Model download, path management, integrity verification |
| `providers/llama_cpp_provider.py` | **NEW** | Local llama.cpp wrapper (summarize + embed) |
| `providers/llama_cpp_remote.py` | **NEW** | Remote OpenAI-compatible client |
| `services/local_ai_service.py` | **NEW** | Facade routing local vs. remote |

### Frontend — wingman-client

| File | Action | Description |
|:-----|:-------|:------------|
| `messages/en.json` | **Edit** | Add `settings_local_ai_*` localization keys |
| `messages/de.json` | **Edit** | Add same keys (English placeholder) |
| `messages/es.json` | **Edit** | Add same keys (English placeholder) |
| `messages/fr.json` | **Edit** | Add same keys (English placeholder) |
| `src/routes/(app)/settings/+page.svelte` | **Edit** | Add Local AI section |
| `src/routes/(app)/settings/LlamaCppSettings.svelte` | **NEW** | Settings component |

### Deployment — wingman-client

| File | Action | Description |
|:-----|:-------|:------------|
| `src-tauri/tauri.conf.json` | **Verify** | Confirm `_internal/` picks up llama_cpp libs |
| `src-tauri/installer.iss` | **Verify** | Confirm `_internal/` recursive copy is sufficient |
| `src-tauri/.gitattributes` | **No change** | Models not in repo |

---

## Verification Checklist

1. **Model download** — Run `local_model_manager.py` standalone, confirm both GGUFs land in `{AppData}/WingmanAI/local_models/`
2. **Local summarize** — Load Qwen via `llama_cpp_provider.py`, call `summarize("Hello world")`, confirm text output
3. **Local embed** — Load Nomic, call `embed(["test"])`, confirm 768-dim float array
4. **Remote summarize** — Start `llama-server` on port 8080 with Qwen, call via `llama_cpp_remote.py`, confirm output
5. **Remote embed** — Start `llama-server` on port 8081 with Nomic (embedding mode), call via remote client, confirm output
6. **Settings round-trip** — Change llama_cpp settings in Svelte UI → POST to `/settings` → verify `settings.yaml` updated → verify provider reloads (check Printr server-only logs)
7. **Toggle local↔remote** — Toggle off → models unload (RAM drops); toggle on → models reload and respond
8. **Build: Windows** — Run `build.py`, verify `_internal/` contains llama_cpp .dll + sqlite_vec extension
9. **Build: macOS** — Run `build_macos.py`, verify .dylib equivalents
10. **Installer** — Full Tauri NSIS build → clean Windows VM install → launch → model download triggers correctly
11. **Regression** — FasterWhisper, PocketTTS, voice activation, all existing settings still work after SettingsService changes

---

## Decisions

| Decision | Choice | Rationale |
|:---------|:-------|:----------|
| Model delivery | Download on first use | Keeps installer small; AppData is non-versioned so models persist across updates |
| Remote endpoints | Two separate host:port | Users may run summarize and embed on different machines or ports |
| Lore library | Gut to stub | Service file kept for reference; routes return 501; client code untouched for rebuild |
| AI engine | llama-cpp-python for both | Single engine, single GGUF format — no fastembed/ONNX dependency |
| sqlite-vec | Added but unused | Dependency present for Milestone 2 (Lore Library rebuild with vector search) |
| Summarize model | Qwen 3.5-0.8B (Q4_K_M) | ~500 MB, 262k context, native tool calling, multimodal future |
| Embed model | nomic-embed-text-v1.5.f16 | ~250 MB, 768-dim, Matryoshka support, GGUF-native |
| GPU acceleration | CPU-only for Milestone 1 | Pre-built pip wheels; Metal/CUDA as follow-up |

## Further Considerations (deferred)

1. **GPU acceleration** — `llama-cpp-python` supports Apple Metal and CUDA via `CMAKE_ARGS` build flags. Recommend CPU-only pre-built wheels for Milestone 1; add GPU toggle in a follow-up.
2. **Idle unload timer** — Auto-unload models after ~5 min idle to free RAM for gaming. Provider already designed with `load()` / `unload()` to support this in Milestone 2.
3. **Model version pinning** — Pin exact GGUF filenames and expected file sizes in `local_model_manager.py` to prevent silent corruption from upstream HuggingFace model updates.
4. **llama-swap router** — For users with limited RAM on their second PC, a `llama-swap` router can hot-swap models on a single port. Document this as an advanced option rather than building it in.
5. **Offload toggle per-model** — Current design is all-local or all-remote. Future: allow summarize-local + embed-remote (or vice versa) for fine-grained control.
