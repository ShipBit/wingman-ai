# Wingman AI Core — Agent Guide

## Pull requests

When work is approved, open a PR in both repos (Core and the closed-source Client). Drop the worktree of a repo you did not change. Link a GitHub issue in Core if there is one (`Closes #123`).

## Client API regeneration

After a change to `api/interface.py`, `api/enums.py` or an endpoint, the Client's generated types are stale. You cannot restart Core yourself, so stop and tell the user:

> "I've changed Core's API. Please restart Core now so the client can regenerate its API types."

Do this before any related client change or client test.

## Tests

`python -m pytest`, in `tests/` by area; CI runs them on Linux for every PR.

- Add a test for a bug fix or a behavior change. Do not test library behavior or pin constants.
- `tests/` is public: no backend internals, client details, tester names, network or API keys.
- Every test passes on a developer's Mac and on Linux CI: no skips for missing tools or checkouts, nothing read outside the repo and `tmp_path`.
- Helpers go in `tests/support.py`, fixtures in a `conftest.py`.

## Logging

Never `print()`. Use the `Printr` singleton (`services/printr.py`):

- `printr.print(..., server_only=True)` is sync and goes to the terminal and log only.
- `await printr.print_async(...)` also reaches the client. It must be awaited.

Use `LogType.LOCALMODEL` for support-model work, `LogType.MEMORY` for memory operations and `LogType.FILLER` for the line spoken while a tool runs: the client styles each one differently.

## Support model prompts

The support model is small (cloud by default, Qwen3.5-4B locally). Write prompts for the weakest one:

- Templates in `prompts/*.md` with `{variables}` filled by the caller, never hard-coded values.
- Labeled sections (`Rules:`, `Input:`), "EXACT words" when it must quote, "IN CHARACTER" when it must rephrase, explicit "Do NOT" lines, under ~200 tokens.
- Pick a `SamplingPreset` per task (`services/skill_local_ai.py`). The 1.0/1.0 defaults make extraction drop and duplicate facts.

## Config fields and migrations

- New fields in `api/interface.py` are required, without a default there. `Optional` only when `None` means something.
- The default goes into `templates/configs/`, and a migration step adds it to existing configs.
- Bump versions only with `python scripts/bump_version.py <version>`: it sets all seven places in Core and Client and writes the migration skeleton.
- A migration step goes into the release being built, never into one that shipped. If `LOCAL_VERSION` is already out with testers, bump first.

## Cross-platform

Core runs on Windows, macOS and Linux. Guard OS-specific imports behind `platform.system()` and skip gracefully elsewhere. Skills declare `platforms` in their `default_config.yaml`. HUD OS code lives behind `hud_server/platform/`.

## Docs and skills

Update `README.md` and `docs/` for new providers, major features or setup changes, not for bug fixes. Before working on a skill, read [skills/AGENTS.md](skills/AGENTS.md).
