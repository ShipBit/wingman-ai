# Wingman AI Core — Agent Development Guide

## Repository and git worktree

Wingman AI consists of 2 separate repositories, both combined into a single VSCode workspace:

- **Core** (`wingman-core/`) — the Python backend that runs the AI, manages configs, and serves the API
- **Client** (`wingman-client/`) — the Svelte frontend that users interact with

If you start developing a new feature, create a new git worktree in both repos with the same name (e.g., `feature/awesome`) to keep changes organized. Use `git worktree` to have both branches checked out simultaneously for easy switching. Always ask from which branch you should start the new worktree — usually it's `develop`, but if you're working on a related feature, it might make sense to branch off that instead.
Make sure you create worktrees in both repos. If you're done with your work and I have approved that we're all ready, create a pull request in both repos. If you didn't change anything in one of the repos, just dump the worktree and create the PR in the repo where you made changes.

In **Core** (`wingman-core/`): Ask me if there is a GH issue to link the PR to, and if not, create one and link it.
**Client** (`wingman-client/`) does not have issue tracking and is closed source, so just create the PR without an issue.

Before you start coding, reassure me that you are working on your own worktree in both Core and Client repositories and make sure to only apply changes there. This is important because there are multiple agents working on the same codebase, and we want to avoid conflicts and ensure a smooth development process.

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

## Config Properties — interface.py

New fields in Pydantic models should almost never be `Optional`. The correct pattern:

1. Make the field **required** or give it a **concrete default value**
2. Add the default in the appropriate template YAML (`templates/configs/`)
3. Add a migration step that inserts the value into existing configs

Only use `Optional` when `None` is a **semantically meaningful state** (e.g., "no override", "use system default"). Do not use `Optional` just to avoid writing a migration.

## Cross-Platform — Windows and macOS

Core must run on both Windows and macOS. If a feature uses Windows-specific modules, **guard all imports** and skip gracefully on macOS — never crash:

```python
if platform.system() == "Windows":
    import win32api
```

Skills declare OS support via `platforms` in `default_config.yaml` (`windows`, `darwin`, `linux`).

## Version Bumps and Migrations

Version lives in `services/system_manager.py` as `LOCAL_VERSION`. Migration templates in `templates/migration/{version}/configs/` are frozen snapshots of default configs for each version.

**When bumping a version** (e.g., 2.1.1 → 2.2.0):

1. Snapshot current `templates/configs/*.yaml` → `templates/migration/2_1_1/configs/` (freeze old version)
2. Create `templates/migration/2_2_0/configs/` (copy current configs as starting point)
3. Create skeleton migration `services/migrations/migration_211_to_220.py` with no-op `migrate_defaults` and `migrate_wingman` methods
4. Update `LOCAL_VERSION`

**When adding a feature that changes config:**

1. Update the Pydantic model in `api/interface.py`
2. Update `templates/configs/` with new defaults
3. **Sync** changes to `templates/migration/{CURRENT_VERSION}/configs/` — must always reflect the latest state of the version being developed
4. Add migration step(s) to the current migration file

Migration methods: `migrate_settings(old, new)`, `migrate_defaults(old, new)`, `migrate_wingman(old, new)`, and optionally `migrate_secrets(old)`, `migrate_mcp(old, new)`. See `services/migrations/base_migration.py`. Migrations are auto-discovered and chained by version order.

## Client API Regeneration

If you change anything in `api/interface.py`, `api/enums.py`, or FastAPI endpoints in `main.py`, the Wingman Client's generated TypeScript types become stale. **You cannot restart Core yourself.** After making API/interface changes, stop and tell the user:

> "I've changed Core's API. Please restart Core now so the client can regenerate its API types."

Do this before making any related client changes or running client tests.

## Documentation

Update `README.md` and `docs/` when new providers, major features, or setup changes are introduced. Also update `skills/README.md` and `skills/AGENTS.md` if the skill system changes. Skip docs for minor refactors or bugfixes.

## Skills

**Read [skills/AGENTS.md](skills/AGENTS.md) before creating or modifying any skill.** It contains critical rules about token budgets, the mandatory Skill-vs-MCP triage, and implementation patterns. Ignore these docs if you're not working on skills, but if you are, read them carefully.
