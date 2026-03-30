# Wingman AI Core — Agent Development Guide

## Repository and git worktree

Wingman AI consists of 2 separate repositories, both combined into a single VSCode workspace:

- **Core** — `/Users/shackles/Source/wingman-ai` — Python backend
- **Client** — `/Users/shackles/Source/wingman-client` — Svelte frontend

### Setting up worktrees

Before you start coding a new feature, create a git worktree **in both repos** with the same branch name (e.g., `feature/awesome`). Ask which branch to base it on — usually `feature/local-ai` or `main`.

```bash
# Core
cd /Users/shackles/Source/wingman-ai
git worktree add .worktrees/my-feature -b feature/my-feature <base-branch>

# Client
cd /Users/shackles/Source/wingman-client
git worktree add .worktrees/my-feature -b feature/my-feature <base-branch>
```

Both repos have `.worktrees/` in their `.gitignore`.

### CRITICAL: Always work in your worktree

**Multiple agents work on this codebase simultaneously.** Each agent has their own worktree and feature branch. The base branch (e.g., `feature/local-ai`) is shared — never commit directly to it.

**All edits, reads, and commits MUST happen in your worktree paths:**

- Core: `/Users/shackles/Source/wingman-ai/.worktrees/<your-feature>/`
- Client: `/Users/shackles/Source/wingman-client/.worktrees/<your-feature>/`

**Never** `cd` to or edit files in the main checkout paths (`/Users/shackles/Source/wingman-ai/` or `/Users/shackles/Source/wingman-client/`) — those are the shared base branches. If you edit there, you'll overwrite or conflict with other agents' work.

### Merging and testing

When the user wants to test, merge your feature branch into the base branch:

```bash
cd /Users/shackles/Source/wingman-ai  # main checkout, on base branch
git merge feature/my-feature --no-edit
```

If there are conflicts, resolve them in the merge commit — don't modify your feature branch to accommodate other agents' code. After testing, continue development back in your worktree.

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
