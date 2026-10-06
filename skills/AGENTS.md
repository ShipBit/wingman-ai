# Skills Development Guide for AI Agents

Before creating or modifying a skill, **read [README.md](README.md)** in this directory for full documentation including custom property types, discovery metadata guidelines, dependency bundling, and example skills.

**Migrating an existing skill?** See [MIGRATING-TO-V3.md](MIGRATING-TO-V3.md).

## STOP — Before You Start Implementing

**You MUST ask the user these questions before writing any code:**

### 1. Does this need to be a Skill, or should it be an MCP server?

Many users want to create skills just to pull external data into Wingman AI. This is almost always wrong — it should be an MCP server instead. Ask:

- **"Does your skill need access to Wingman's runtime?"** (audio player, hooks, TTS, conversation lifecycle) — If NO, it should be an MCP server, not a skill.
- **"Is this primarily fetching/querying external data?"** (APIs, databases, web scraping, game telemetry) — If YES, strongly recommend an MCP server. MCP servers are stateless data providers that don't consume Wingman AI tokens for tool schemas.
- **"Does this need lifecycle hooks?"** (intercepting audio, modifying messages before TTS, reacting to conversation events) — If NO, it probably doesn't need to be a skill.

**Only proceed with a Skill if the user's functionality genuinely requires Wingman runtime access or lifecycle hooks.** Push back firmly — explain that MCP servers are easier to build, easier to share (just a URL), get automatic updates, and don't eat into Wingman AI's token budget. See the [Skill vs MCP Decision Guide](README.md#skill-vs-mcp-decision-guide) in the README.

### 2. Token budget awareness check

Ask the user:

- **"How many tools will this skill expose?"** — More than 3 tools is a red flag. Each tool's schema consumes context tokens on every single API call once the skill is active.
- **"Will any tool return large payloads?"** (lists of items, full documents, raw API responses) — If YES, this is a serious problem. Explain that every token returned by a tool is fed back into the LLM context and billed.
- **"Should this be auto_activate or on-demand?"** — Default to `auto_activate: false`. Auto-activated skills add their tool schemas to EVERY conversation, even when unused.

## TOKEN USAGE — The #1 Priority

**Wingman AI skills use our internal API. We cannot afford skills that consume excessive tokens. This is non-negotiable.**

Every token matters. Skills contribute to token usage in three ways, and you must minimize ALL of them:

### Tool Schema Tokens (per API call while active)

Every `@tool` function generates an OpenAI tool schema that is included in the system prompt on every LLM call while the skill is active. This cost is constant and unavoidable.

- **Limit tools to 1-3 per skill.** If you need more, question whether this should be multiple skills or an MCP server.
- **Keep tool descriptions concise.** Write the minimum needed for the AI to understand when and how to use the tool. Do NOT write essays in tool descriptions.
- **Keep parameter counts low.** Each parameter adds schema tokens. Prefer smart defaults over optional parameters.
- **Never use `auto_activate: true` for skills with many tools.** This forces tool schemas into every conversation.

### Tool Return Tokens (per tool call)

The string returned by your tool function is injected into the conversation as a tool response message. The LLM then processes it to generate a user-facing response. Large returns are extremely expensive.

- **Return short, structured summaries** — NOT raw API responses, NOT full documents, NOT lists of 50+ items.
- **Truncate and summarize server-side.** If your tool fetches data from an API, extract only the fields the user asked about. Never pass through raw JSON.
- **Set hard limits on list sizes.** If returning a list, cap it (e.g., top 5 results) and tell the user there are more available.
- **Use `summarize=False`** on tools that return final, user-ready text (avoids a second LLM call to rephrase).
- **Consider whether the data even needs to go through the LLM.** Can you display it directly via HUD, log, or toast instead?

### Conversation History Tokens (cumulative)

Tool calls and responses accumulate in conversation history. A chatty skill that makes many tool calls bloats the context window over the course of a conversation.

- **Prefer fewer, more complete tool calls** over many small ones.
- **Don't create tools that the AI will call repeatedly in a loop.** If you find yourself building pagination or polling, stop — this is an MCP server use case, not a skill.

### Red Flags — REJECT These Patterns

If you see any of these, stop and redesign or recommend an MCP server instead:

| Pattern | Problem | Fix |
| ------- | ------- | --- |
| Tool returns raw API JSON | Hundreds/thousands of wasted tokens | Parse and summarize server-side |
| Tool returns unbounded lists | Token bomb on large datasets | Cap results, add pagination info as text |
| 5+ tools in one skill | Schema bloat on every API call | Split into multiple skills or use MCP |
| `auto_activate` with 4+ tools | Permanent token overhead in all conversations | Use progressive disclosure (`auto_activate: false`) |
| Tool that fetches + formats + displays | Multiple LLM round-trips | Combine into one tool call, use `summarize=False` |
| Polling/looping tool patterns | Repeated tool calls drain tokens | Use hooks or background tasks instead |
| "Fetch all" without filters | Potentially massive return payload | Require filters, enforce result limits |
| Skill only wraps an external API | No Wingman runtime needed | Should be an MCP server |

### Token Estimation

Before implementing, estimate the token cost of your skill:

- **Tool schema**: ~50-100 tokens per simple tool, ~200+ for complex tools with many parameters
- **Tool return**: Count the characters in a typical response, divide by 4 for rough token estimate
- **Multiplier**: Schema tokens are paid on EVERY API call. A skill with 3 tools adding 300 schema tokens costs 300 tokens x every message in the conversation

**If your skill would add more than ~200 schema tokens total, it MUST use progressive disclosure (`auto_activate: false`).**

## Critical Rules

1. **Never cache config values.** Always retrieve custom properties just-in-time — users can change them in the UI while the skill is running:
   ```python
   # BAD — cached, won't reflect UI changes:
   self.my_val = self.retrieve_custom_property_value("x", errors)

   # GOOD — fresh every call:
   def _get_x(self):
       return self.retrieve_custom_property_value("x", [])
   ```

2. **Use `retrieve_secret()` for API keys and sensitive data.** Never put secrets in custom properties.

3. **Use the `@tool` decorator** for all AI-callable functions. Include type hints (they auto-generate the OpenAI tool schema). Write clear but concise descriptions.

4. **Always implement `unload()`** to clean up resources (unsubscribe events, close connections, cancel tasks).

5. **Name the user's language in every prompt whose output the user hears or reads.** `self.wingman.ai.generate()` and `self.wingman.local_ai.*` do not get the Wingman's system prompt, so the model does not know the language unless you say it:
   ```python
   system = f"... Write in {self.wingman.language.name}."   # "German", "Dutch", ...
   ```
   Internal calls (yes/no checks, JSON extraction, matching) don't need it. If a user-written prompt may ask for another language on purpose (English radio chatter for a German user), add "unless the scenario asks for another language".

6. **Never block Core's event loop.** Tools and hooks run on the loop that also plays audio and listens to the microphone. A sync `def` tool runs on that loop too. Wrap blocking calls (`requests`, SDK clients, file or image work, `keyboard`, `time.sleep`) in `await asyncio.to_thread(fn, *args)` and wait with `await asyncio.sleep(...)`. `aiohttp` needs no thread.

7. **Background loops must survive errors.** A loop started with `self.wingman.run_in_thread(...)` dies silently on the first exception. Put `try/except` around the work of each iteration, reset any "running" flag in `finally`, and check a flag or run id so `unload()` stops it.

8. **Import only what the facade allows** (see [Allowed imports](#allowed-imports)). Everything else is Core-internal and changes without notice.

9. **Study existing skills** before writing new ones. Similar skills are good templates — check the [Example Skills](#example-skills) list below.

## Required Files

```
skills/your_skill_name/
├── main.py              # Skill class (must inherit from Skill)
├── default_config.yaml  # Metadata, description, custom_properties
└── logo.png             # 256x256 or 512x512 PNG icon
```

## Minimal Skill Template

```python
from typing import TYPE_CHECKING
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from skills.skill_base import Skill, tool

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext

class YourSkillName(Skill):
    def __init__(self, config: SkillConfig, settings: SettingsConfig, wingman: "WingmanContext") -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()
        self.retrieve_custom_property_value("your_property", errors)  # validate, don't cache
        return errors

    async def prepare(self) -> None:
        await super().prepare()

    @tool(description="What this tool does. WHEN TO USE: describe trigger scenarios.", wait_response=True)
    async def your_tool(self, param: str) -> str:
        """Args:
            param: Description of the parameter.
        """
        return "result"  # Keep returns SHORT

    async def unload(self) -> None:
        await super().unload()
```

## Command Actions — `@command_action`

Besides AI-callable `@tool`s, a skill can expose **command actions**: functions a user binds as an action inside a **Command** (alongside keyboard / mouse / write / wait), triggered by an **instant phrase** or by the AI. The Client renders an input for each parameter; the user fills **static** values that are stored in the command and passed to your function at trigger time.

```python
from skills.skill_base import Skill, command_action   # separate decorator from @tool
from typing import Literal

class YourSkill(Skill):
    @command_action(label="Set Brightness", description="Set the display brightness.")
    def set_brightness(self, level: int, mode: Literal["soft", "hard"] = "soft") -> str:
        ...
        return f"Brightness set to {level}"   # handed to the AI (respond="ai" default)
```

**Decorator:** `@command_action(label=None, description=None, respond="ai")`

- `label` — name shown in the command editor (defaults to the function name).
- `description` — one-line help text shown under the function picker in the editor.
- `respond` — `Literal["ai", "speak"]`; **where your return value goes** (see below).

**Separate from `@tool`.** A function can carry both, one, or neither. Carrying both makes it AI-callable *and* user-bindable.

**Parameters must be UI-renderable** — only `str`, `int`, `float`, `bool`, and `Literal[...]` (rendered as a dropdown), plus optionals (params with defaults). Any other type (`dict`, `list`, custom) is **rejected at import time** with a clear error. The schema is auto-generated from your type hints (same machinery as `@tool`). The Client sends only declared params and Core drops stray keys, so your function never gets an unexpected keyword argument.

**Output — return a plain `str` (or `None`); `respond` decides where it goes:**

- `respond="ai"` *(default)* — the return is handed to the **AI**, which voices/uses it (it may paraphrase or chain). Pair with a command's static `responses` for a fixed acknowledgment.
- `respond="speak"` — the return is **spoken verbatim** via TTS (no AI roundtrip on instant activation) and also given to the AI. Use for a *dynamic*, input-dependent spoken reply.
- **Return `None`** ⇒ the command falls through to its usual `"OK"` acknowledgment (fire-and-forget), like a keyboard command.

**Interplay with a Command's static `responses`:** the command's static `responses` (e.g. "I got you.") are the *fixed* acknowledgment — used when the action doesn't speak its own result (`respond="ai"` or fire-and-forget). A `respond="speak"` action provides a *dynamic* spoken result and **takes precedence** over the static response (the wingman never says both). Static for input-independent replies; `respond="speak"` for input-dependent ones.

**Runtime functions** registered with `self.wingman.commands.register_function(...)` or `add_skill_command(...)` live until Core restarts. A saved command keeps pointing at the function name, so register it again in `prepare()` on every start.

**Reference examples in bundled skills:**

- `radio_chatter` — `turn_on_radio` / `turn_off_radio` / `get_radio_status`: stacks `@command_action` on existing `@tool` methods; no-arg `respond="speak"` toggles.
- `spotify` — `control_spotify_playback`: a `Literal[...]` param renders as an enum dropdown (the user fixes one action per command) plus an optional `int` input.
- `hud` — `hud_show` / `hud_hide`: no-arg async toggles.
- `voice_changer` — `switch_voice_now`: a *new* method (no matching `@tool`), giving users a manual handle on an otherwise event-driven skill.

## Minimal default_config.yaml

```yaml
module: skills.your_skill_name.main
api_version: 3                         # REQUIRED for v3 — without it the skill is treated as legacy and won't load
name: YourSkillName                    # Must match class name exactly
display_name: Your Skill Name
author: Your Name
version: 1.0.0                         # Your skill's own release, shown in error reports. Bump it when you ship.
platforms: [windows]                   # Optional: only if you use OS-specific modules. windows | darwin | linux
auto_activate: false                   # Default. Only set true for hook-only or 1-2 tiny tools.
requires: [sc_gamelog]                 # Optional: hud_server and/or sc_gamelog must be on in the settings.
tags:
  - Utility
description:
  en: Clear, action-focused description. The AI reads this to find your skill.
discovery_keywords:                    # Optional but recommended for non-auto-activated skills
  - synonym1
  - synonym2
custom_properties:
  - id: your_property
    name: Display Name
    hint: Help text for the user
    value: default
    required: true
    property_type: string              # string|textarea|number|boolean|single_select|slider|color|audio_device|voice_selection|audio_files
```

## Available Hooks

```python
async def on_add_user_message(self, message: str) -> None
async def on_add_assistant_message(self, message: str, tool_calls: list) -> None
async def on_play_to_user(self, text: str, sound_config: SoundConfig) -> str  # return modified text or {SKIP-TTS}
async def is_summarize_needed(self, tool_name: str) -> bool      # default True
async def is_waiting_response_needed(self, tool_name: str) -> bool  # default False
async def prepare(self) -> None
async def unload(self) -> None
```

## Key APIs

```python
self.retrieve_custom_property_value(property_id, errors)  # Config value (just-in-time!)
await self.wingman.secrets.retrieve(secret_name, errors)  # stored secret (prompts user if missing)
self.wingman.config                                        # READ-ONLY view of the config
self.log.info(msg) / self.log.warning(msg) / self.log.error(msg)  # Logging (server_only=True skips the toast)
self.get_generated_files_dir()                             # Persistent storage directory
```

### The facade — what you may read vs. change

`self.wingman` is a **controlled facade** (`WingmanContext`). You can **read** almost everything,
but you may only **change** things through sanctioned capabilities. Writing to config raises
`FacadeError` with guidance.

```python
# READ (free): self.wingman.config.<...>  — live, read-only. Writing raises FacadeError.
#   copy.deepcopy(self.wingman.config.sound) gives a mutable detached copy if you need to customize.

# CHANGE (sanctioned capabilities only):
await self.wingman.tts.set_voice(voice)                 # voice on the CURRENT provider (no switching)
await self.wingman.tts.speak(text, interrupt=True)      # say text; interrupt=False waits for current playback
self.wingman.audio.is_playing                           # read playback state
await self.wingman.audio.play(cfg) / .stop(cfg)         # play/stop your own audio
sub = self.wingman.audio.on_playback_started(cb)        # returns a Subscription; sub.unsubscribe() in unload()
await self.wingman.audio.set_output_device(device_id)   # switch output device in-process
self.wingman.commands.get(name) / .all() / await .save()  # read/edit/persist commands
self.wingman.tools.has(name) / await .invoke(name, args)  # discover + invoke tools/commands -> ToolResult
self.wingman.tools.source(name) / .all() / .servers()   # tool origin + enumerate callable functions / MCP servers
self.wingman.audio.mic_status                           # current MicStatus (listening/recording/...), None before the first
sub = self.wingman.audio.on_mic_status_changed(cb)      # cb(status) on every change; sub.unsubscribe() in unload()
self.wingman.stt.add_hotwords(["Hornet"]) / .remove_hotwords([...])  # names the transcript is corrected against (runtime only)
self.wingman.stt.remember_spelling("Hornet", heard="Hornit")         # permanent: goes into the user's vocabulary
self.wingman.run_in_thread(fn, *args)                   # start a background loop in its own thread (fire and forget)

# LANGUAGE — the one language the user and their Wingmen speak (read fresh, it can change):
self.wingman.language.name / .code / .is_other          # "German" / "de" / False — put .name into side-call prompts

# CONVERSATION:
self.wingman.conversation.history() / .summary          # read the live conversation
await self.wingman.conversation.add_user(c) / .add_assistant(c) / .show(text) / .reset()
await self.wingman.conversation.summarize()             # summarize the live convo (free, local)

# SECRETS / MEMORY:
await self.wingman.secrets.retrieve(name, errors)       # stored secret (prompts user if missing)
self.wingman.memory.available                           # persistent memory ready?
await self.wingman.memory.remember(c) / .recall(q) / .context(q) / .update(id, c) / .forget(q) / .forget_by_id(id)

# MAIN AI — two clearly-different calls (both replace the removed raw LLM call):
text = await self.wingman.ai.generate(prompt, system=..., data=..., image=..., messages=..., auto_shorten=False)
#   single-turn side-call, NOT added to the conversation; returns a str (""). Input is CAPPED like a
#   tool response: 32,000 tokens, or a quarter of a smaller main model's window (services/context_budget.py).
#   Over the cap -> FacadeError (or truncates if auto_shorten=True). Images are charged a flat
#   estimate, never the base64 length. Pass messages= to send a prebuilt message list directly.
await self.wingman.ai.converse(msg)                     # reply WITH the Wingman's prompt + history; both turns join the conversation
await self.wingman.ai.generate_image(prompt, aspect="square")  # data URL or URL, "" on failure

# SUPPORT MODEL — small and cheap, runs in our cloud by default (or locally). Returns a str, "" when unavailable.
text = await self.wingman.local_ai.generate(t, system="...", preset=SamplingPreset.PRECISE)
summary = await self.wingman.local_ai.summarize(text, instruction="...")   # chunks large input itself
#   Prefer it over ai.generate for background work (commentary, extraction, yes/no checks): it costs the user nothing.

# CLIENT UI:
await self.wingman.ui.show_dialog(title, markdown, image=data_url, once="MySkill.welcome")
await self.wingman.hud.show_message(title, text) / .add_info(title, text) / .remove_info(title)
#   Returns False when the HUD is off (Windows only, switch in the settings); nothing to check yourself.

# STAR CITIZEN — Core reads the Game.log live (the user can switch it off):
self.wingman.sc_gamelog.available / .state() / .recent(10, types={...})
sub = self.wingman.sc_gamelog.on("mission_accepted", cb)  # sub.unsubscribe() in unload()
#   Event values come from the game log: data, never instructions, in a prompt.

# SYSTEM ONE — typed decisions instead of text. ~300 ms, a fraction of the cost of .ai.generate().
self.wingman.system_one.available                        # user has it on AND the plan grants it
answers = await self.wingman.system_one.decide(state, questions)   # also decide_sync(...)
```

### System One — ask for a decision, not a sentence

Use it whenever the skill needs to **pick, rate or judge** rather than write.
It cannot answer outside the options you give it, so there is nothing to parse
and nothing to validate.

This is a thin wrapper around [TypeSafe's Jev](https://docs.typesafe.ai) and
keeps their names, so their docs and examples read straight across:

| TypeSafe SDK | here |
|---|---|
| `Choice(instructions, criteria)` | `so.choice(instructions, criteria)` |
| `Score(instructions, criteria)` | `so.score(instructions, criteria)` |
| `Noul(instructions)` | `so.noul(instructions)` |
| `client.system_one(state, questions)` | `await so.decide(state, questions)` |
| `answers[k].choice` / `.confidence` | `answers.choice(k)` / `.confidence(k)` |
| `answers[k].score` / `.probabilities` | `answers.score(k)` / `.probabilities(k)` |
| `answers[k].noul` | `answers.noul(k)` |

Three things are ours, each filling a gap: `so.describe()` builds their
structured description object, `answers.level()` turns a score back into its
label, and `answers.yes_no()` applies a threshold to a noul.

```python
so = self.wingman.system_one
if so.available:
    answers = await so.decide(
        state={"transcript": text, "cargo": cargo},
        questions={
            "intent": so.choice("What does the pilot want?", {
                "sell": so.describe("offload cargo", not_for="buying more"),
                "buy":  "acquire cargo",
                "none": "nothing about cargo",          # always give it an out
            }),
            "urgent": so.noul("Does this need doing right now?"),
            "risk":   so.score("How risky is this route?", ["safe", "watchful", "dangerous"]),
        },
    )
    answers.choice("intent", min_confidence=0.8)   # "sell", or None if unsure
    answers.noul("urgent")                         # 0.94 — a probability
    answers.yes_no("urgent")                       # True — thresholded at 0.5
    answers.level("risk")                          # "dangerous"
    answers.score("risk")                          # 1.99 — the position, continuous
    answers.probabilities("risk")                  # {"safe": 0.0, ... } keyed by label
```

Four rules that come out of measuring it (`evals/FINDINGS-jev-2026-09-20.md`):

- **Ask everything in one `decide()`.** Questions are evaluated in parallel:
  eight cost 13 ms and 28% more tokens than one. Three calls for three
  questions is three times the latency for nothing.
- **Describe options that could be confused.** Descriptions cut wrong answers
  from 16 to 3 out of 152 on Wingman's own command routing, at no cost in
  latency. `not_for=` separates two neighbours better than a longer
  description of either. A bare option name is fine when nothing is close.
- **Give a choice a "none of these" option** whenever nothing applying is an
  honest answer. Without one the probability has nowhere to go but onto the
  real options.
- **`min_confidence` separates unsure from sure, not two overlapping options.**
  If the wrong neighbour keeps winning at high confidence, the fix is a better
  description, not a higher threshold.

Always handle `available` being False — the user can switch System One off in
Settings, and a plan may not include it. Every reader returns `None`/`{}` in
that case, so the skill silently takes the None branch unless you check.

**Removed (do NOT use):** the raw LLM call (`self.llm_call(...)` / `actual_llm_call` — use `self.wingman.ai.generate`),
`self.wingman.switch_tts_provider(...)` (runtime provider switching is not allowed; use `tts.set_voice`),
the raw registries (`self.wingman.registry.*` — use `self.wingman.tools.*`), and writing to
`self.wingman.config` / `self.settings` (read-only; use the capabilities above).

### Calling other skills & MCP servers

```python
# Discover everything callable right now (with origin + params)
for tool in self.wingman.tools.all():
    self.log.info(f"{tool.name} (from {tool.source})", server_only=True)

# Call another ACTIVE skill's tool by name
if self.wingman.tools.has("take_screenshot"):
    result = await self.wingman.tools.invoke("take_screenshot", {})
    self.log.info(f"{result.response} (from {result.skill})")

# Call your own MCP server's tool (many skills ship an MCP for their datasource)
servers = {s["display_name"] for s in self.wingman.tools.servers()}
if "My Data MCP" in servers and self.wingman.tools.has("mydata_query"):
    res = await self.wingman.tools.invoke("mydata_query", {"q": "ships"})
    data = res.response
else:
    self.log.warning("My Data MCP not active; skipping enriched lookup")
```

MCP tool names are prefixed by the registry — use the name exactly as it appears in
`self.wingman.tools.names()` / `.all()`.

## Local Model — Sampling Parameters

The global defaults are 1.0 / 1.0, which is too loose for most skill work. **Pick a preset per call:** `PRECISE` for extraction, matching and yes/no answers (otherwise the model drops or duplicates facts), `BALANCED` for summaries, `CREATIVE` for in-character lines. Import `SamplingPreset` from `services.skill_local_ai` and pass `preset=` to `self.wingman.local_ai.generate()`, `.generate_sync()`, `.summarize()` and `.summarize_sync()`. Manual `temperature` / `top_p` override the preset. See the `SamplingPreset` docstring for the values.

Pass `reasoning=True` to make the local model *think* before answering — better quality on structured or analytical work, but slower. Only do this on background tasks the user is not waiting for. Leave it unset (or `False`) on anything latency-sensitive. Available on `generate()`, `generate_sync()`, `summarize()`, and `summarize_sync()`.

## Allowed imports

A skill imports from Core only:

| Import | For |
|---|---|
| `api.interface`, `api.enums` | config types, `WingmanInitializationError`, enums |
| `skills.skill_base` | `Skill`, `tool`, `command_action` |
| `skills.<your_skill>.*` | your own modules (absolute imports, no `sys.path` changes) |
| `services.skill_local_ai` | `SamplingPreset` |
| `services.image_generation` | `reference_data_url` and the image file helpers next to `ai.generate_image` |
| `services.benchmark` | only the type hint of a legacy `execute_tool` override |
| `wingmen.wingman_context` | under `TYPE_CHECKING`, for the `WingmanContext` hint |

Everything else (`services.printr`, `services.file`, `services.secret_keeper`, `wingmen.*`, `providers.*`, `hud_server.*`) is internal. Use `self.log`, `self.get_generated_files_dir()`, `self.wingman.secrets` and the other facade members instead. If the facade lacks something your skill needs, say so; do not import around it. `tests/skills/test_skill_imports.py` checks the bundled skills.

Facade members are added over time (`ui`, `hud`, `sc_gamelog`, `system_one`, `stt`, `language` came during 3.x). A skill that uses one needs a Wingman that has it; on an older one the attribute is missing and the skill fails with an `AttributeError`. Name the minimum Wingman version in your skill's description when you share it.

## Before you finish

1. `python -m py_compile` on every file, and `python -c "import skills.<name>.main"` (on the skill's platform).
2. No `print()`, no import from the list above that is not allowed, no blocking call in an `async def`.
3. Every `on(...)` / `on_playback_*` subscription and every background loop is stopped in `unload()`.
4. Tool returns are capped; the manifest has `api_version: 3`, `version`, and `platforms` if needed.
5. Start Wingman, activate the skill on a Wingman and call each tool once. Check the log for errors.

## Example Skills

| Skill | Type | Key Pattern |
|-------|------|-------------|
| [audio_device_changer](audio_device_changer/) | Hook (auto) | Audio routing via `on_play_to_user` |
| [thinking_sound](thinking_sound/) | Hook (auto) | Sound during processing |
| [mic_status](mic_status/) | Hook (auto) | `audio.on_mic_status_changed`, `requires: [hud_server]` |
| [image_generation](image_generation/) | Tool | `@tool` with `wait_response` |
| [timer](timer/) | Hook+Tool | State management, `unload()` cleanup |
| [vision_ai](vision_ai/) | Tool | Screen capture, discovery keywords |
| [file_manager](file_manager/) | Tool | Multi-tool skill |
| [spotify](spotify/) | Tool | External API integration |
| [uexcorp](uexcorp/) | Tool | Game integration, domain tags |
| [sc_game_events](sc_game_events/) | Hook+Tool (auto) | Star Citizen log events via `self.wingman.sc_gamelog.on`, support-model reactions, `language.name` in prompts |
| [sc_accountant](sc_accountant/) | Hook+Tool (auto) | `sc_gamelog.on("*")`, own web dashboard, `ui.show_dialog(once=...)` |
| [elite_dangerous](elite_dangerous/) | Hook+Tool (auto) | Reads a game's own files in a `run_in_thread` loop, support-model reactions |
| [elite_dangerous_controls](elite_dangerous_controls/) | Hook (auto) | No tools: turns the game's key bindings into commands via `commands.add_category` / `add` / `save` |

Do not copy the tool count of `hud`, `control_windows` or `file_manager`: they predate the token rules and expose 9–10 tools each.
