# Skills — Agent Guide

The API reference is [README.md](README.md). Porting an older skill: [MIGRATING-TO-V3.md](MIGRATING-TO-V3.md). This file only holds what you would otherwise get wrong.

## Ask first: Skill or MCP server?

Before writing code, ask the user:

- Does it need Wingman's runtime (audio, TTS, hooks, the conversation)? If not, it should be an MCP server.
- Does it mostly fetch external data (APIs, databases, telemetry)? Then it should be an MCP server.
- How many tools, and how large are their returns?

Push back when the answer is MCP: it is easier to build and share, and its tools do not sit in Wingman's context. See [Skill vs MCP](README.md#skill-vs-mcp-decision-guide).

## Tokens

Skills run on our API, so every token is paid by us or the user.

- 1–3 tools per skill, short descriptions, few parameters. Every tool schema is sent with every call while the skill is active.
- `auto_activate: false` unless the skill is hooks only or has one or two tiny tools.
- Tool returns are short summaries with capped lists, never raw JSON. Use `summarize=False` when the return is already the final answer.
- No tools the AI calls in a loop (polling, paging). Use a hook or a background task.
- `control_windows` and `file_manager` predate these rules. Do not copy their tool count.

## Rules

- `default_config.yaml` needs `api_version: 3`, or the skill is treated as legacy and not loaded. `name` must equal the class name.
- No work at import time: the catalog imports the module without creating the skill.
- Read custom properties when you need them, never cache them in `__init__`: the user changes them while the skill runs. Secrets go through `self.wingman.secrets`, never custom properties. Paths use the `directory` or `file` property type.
- `self.wingman.ai.generate` and `self.wingman.local_ai` do not get the Wingman's system prompt. Put `self.wingman.language.name` into every prompt whose output the user hears or reads.
- Prefer the support model (`local_ai`) for background work, with a `SamplingPreset` per call (`PRECISE` for extraction and yes/no). Use System One to pick, rate or judge.
- Lines a skill says on its own pass a `priority` to `tts.speak` (`EVENT` or `BACKGROUND`), or they cut off the Wingman's answer.
- Never block an event loop. Blocking calls go through `await asyncio.to_thread(...)`, waits use `await asyncio.sleep(...)`.
- The same skill instance runs on several event loops. Do not keep an `asyncio.Lock`, `Event`, `Queue`, `Task` or async HTTP client on `self`; never cancel a task or close a connection from another thread (on Windows that can stop Core's main loop). See [Threads and event loops](README.md#threads-and-event-loops).
- Background loops catch errors per iteration, and `unload()` stops them. `unload()` also unsubscribes every `Subscription`.
- Functions registered at runtime (`commands.register_function`, `add_skill_command`) are gone after a restart. Register them again in `prepare()`.
- No `print()`: use `self.log`.
- Facade members are added over time. A skill that uses a new one fails with `AttributeError` on an older Wingman, so name the minimum Wingman version in its description.

## Allowed imports

A skill imports from Core only:

| Import | For |
|---|---|
| `api.interface`, `api.enums` | config types, `WingmanInitializationError`, enums |
| `skills.skill_base` | `Skill`, `tool`, `command_action` |
| `skills.<your_skill>.*` | your own modules (absolute imports, no `sys.path` changes) |
| `services.skill_local_ai` | `SamplingPreset` |
| `services.image_generation` | image helpers for `ai.generate_image` |
| `services.benchmark` | only the type hint of a legacy `execute_tool` override |
| `wingmen.wingman_context` | under `TYPE_CHECKING`, for the `WingmanContext` hint |

Everything else is internal and changes without notice. If the facade lacks something, say so instead of importing around it. `tests/skills/test_skill_imports.py` checks the bundled skills.

## Before you finish

1. `python -c "import skills.<name>.main"` works (on the skill's platform).
2. Start Wingman, activate the skill and call each tool once. Check the log for errors.
