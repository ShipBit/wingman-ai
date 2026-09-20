# Wingman AI Core — Agent Development Guide

### Pull requests

When work is approved, create a PR in both repos. If you didn't change anything in one repo, just remove that worktree.

- **Core**: Ask if there is a GitHub issue to link the PR to. If not, create one and link it.
- **Client**: Closed source, no issue tracking — just create the PR.

## Logging — Never use bare `print()`

All output goes through the `Printr` singleton (`services/printr.py`). The two modes have different calling conventions:

- **`server_only=True`** → **sync** call, terminal and log file only, client never sees it:

  ```python
  printr.print("debug info", color=LogType.SYSTEM, server_only=True)
  ```

- **`server_only=False`** (default) → **async** call, broadcasts to client GUI, **MUST be awaited**:

  ```python
  await printr.print_async("Wingman ready", color=LogType.INFO, source_name=self.name)
  ```

If you use `printr.print()` without `server_only=True`, it sends to the client synchronously via `ensure_async()` — prefer the explicit async version when you want client visibility.

### LogType.LOCALMODEL — local support/embedding model messages

Use `LogType.LOCALMODEL` for any message originating from the local support model or embedding model (greetings, condensation status, etc.). The client renders these with a distinct dashed-border style and a label ("Generated locally — not part of the conversation with your AI provider") to distinguish them from conversation messages with the main AI provider.

### LogType.MEMORY — persistent memory operations

Use `LogType.MEMORY` for memory recall/store/forget messages. The client renders these as system pills with a brain icon and pink accent — distinct from LOCALMODEL chat bubbles. Example:

```python
await printr.print_async(
    "Memory stored: user prefers dark mode",
    color=LogType.MEMORY,
    source_name=self.name,
)
```

## Writing Prompts for the Support Model

The local support model is a small 2B-parameter LLM (llama.cpp). It does not follow instructions as reliably as cloud models. When writing or editing prompt templates in `prompts/` or `system_prompt` strings for `local_ai_service.support()`, follow these rules:

**Use prompt templates with `{variables}`, not hard-coded strings.** Prompt files live in `prompts/*.md` and use Python `str.format()` placeholders (e.g., `{name}`, `{backstory}`, `{comm_context}`). The calling code fills them in via `.format(name=..., backstory=...)`. Never hard-code values that should come from config or runtime — always use a `{variable}` and pass it in from the caller.

**Structure for small models:**

- **Use labeled sections** (`Backstory:`, `Rules:`, `Input:`) instead of prose paragraphs. Small models parse structure better than flowing text.
- **Say "EXACT words"** when the model should reference source material. Without this, it paraphrases loosely and hallucinates details (e.g., turning "gift ideas" into "gift cards").
- **Say "IN CHARACTER"** when the model must rephrase injected text in its persona's voice. Otherwise it dumps `{variable}` content verbatim instead of weaving it naturally.
- **Add explicit "Do NOT" constraints.** Small models confabulate freely unless told not to.
- **Keep prompts under ~200 tokens.** Every system-prompt token reduces the budget available for input and output.

See also: [skills/README.md — Prompt Writing Guidelines](skills/README.md#prompt-writing-guidelines-for-small-models) for the full reference.

## Sampling Parameters — Temperature and Top P

The support model is a small 2B model — sampling parameters matter more than on large models. Global defaults are tuned for summarization (0.3 / 1.0). **Override for creative tasks or output will be flat.**

All `support()` calls accept optional `temperature` and `top_p` overrides. In skills, use `SamplingPreset` from `services/skill_local_ai.py` (`PRECISE`, `BALANCED`, `CREATIVE`, `ADVENTUROUS`) or pass raw values. Manual values override presets. See `SamplingPreset` docstring for values.

## Config Properties — interface.py

New fields in Pydantic models should almost never be `Optional`. The correct pattern:

1. Make the field **required** or give it a **concrete default value**
2. DO NOT give it a default value in interface.py.
3. Add the default in the appropriate template YAML (`templates/configs/`)
4. Add a migration step that inserts the value into existing configs

Only use `Optional` when `None` is a **semantically meaningful state** (e.g., "no override", "use system default"). Do not use `Optional` just to avoid writing a migration.

## Cross-Platform — Windows and macOS

Core must run on both Windows and macOS and Linux. If a feature uses Windows-specific modules, **guard all imports** and skip gracefully on the other OSes — never crash:

```python
if platform.system() == "Windows":
    import win32api
```

Skills declare OS support via `platforms` in `default_config.yaml` (`windows`, `darwin`, `linux`).

## Version Bumps and Migrations

The version is written in seven places across Core and the Client. Do not edit them by hand:

```
python scripts/bump_version.py 3.2.4
```

That sets `LOCAL_VERSION` in `services/system_manager.py`, the six client spots (`package.json`, both places in `package-lock.json`, `tauri.conf.json`, `Cargo.toml`, `Cargo.lock`), and writes the skeleton migration `services/migrations/migration_<old>_to_<new>.py`. The chain loader scans that directory, so there is nothing to register. `python scripts/bump_version.py --check` reports disagreement and is what `tests/test_version_consistency.py` runs.

There are no frozen per-version config snapshots. A migration reads the user's own file and the *current* `templates/configs/`; fields no step adds are backfilled from the template at the end of the chain.

**When adding a feature that changes config:**

1. Update the Pydantic model in `api/interface.py`
2. Update `templates/configs/` with new defaults
3. Add a migration step to the migration **into the release you are building** — never to one that already shipped. If the current `LOCAL_VERSION` is already out with testers, bump first and put the step in the new file.

## Client API Regeneration

If you change anything in `api/interface.py`, `api/enums.py`, or FastAPI endpoints in `main.py`, the Wingman Client's generated TypeScript types become stale. **You cannot restart Core yourself.** After making API/interface changes, stop and tell the user:

> "I've changed Core's API. Please restart Core now so the client can regenerate its API types."

Do this before making any related client changes or running client tests.

## Documentation

Update `README.md` and `docs/` when new providers, major features, or setup changes are introduced. Also update `skills/README.md` and `skills/AGENTS.md` if the skill system changes. Skip docs for minor refactors or bugfixes.

## Skills

**Read [skills/AGENTS.md](skills/AGENTS.md) before creating or modifying any skill.** It contains critical rules about token budgets, the mandatory Skill-vs-MCP triage, and implementation patterns. Ignore these docs if you're not working on skills, but if you are, read them carefully.
