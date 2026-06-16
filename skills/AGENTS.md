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

5. **Study existing skills** before writing new ones. Similar skills are good templates — check the [Example Skills](#example-skills) list below.

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
auto_activate: false                   # Default. Only set true for hook-only or 1-2 tiny tools.
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

# CONVERSATION:
self.wingman.conversation.history() / .summary          # read the live conversation
await self.wingman.conversation.add_user(c) / .add_assistant(c) / .reset()
await self.wingman.conversation.summarize()             # summarize the live convo (free, local)

# SECRETS / MEMORY:
await self.wingman.secrets.retrieve(name, errors)       # stored secret (prompts user if missing)
self.wingman.memory.available                           # persistent memory ready?
await self.wingman.memory.remember(c) / .recall(q) / .context(q) / .update(id, c) / .forget(q) / .forget_by_id(id)

# MAIN AI — two clearly-different calls (both replace the removed raw LLM call):
text = await self.wingman.ai.generate(prompt, system=..., data=..., image=..., messages=..., auto_shorten=False)
#   single-turn side-call, NOT added to the conversation; returns a str (""). Input is CAPPED when
#   conversation condensation is on (Wingman Pro hardcoded; own providers config.features.skill_max_input_tokens).
#   Over the cap -> FacadeError (or truncates if auto_shorten=True). Images are charged a flat
#   estimate, never the base64 length. Pass messages= to send a prebuilt message list directly.
summary = await self.wingman.local_ai.summarize(...)    # bulk reduction on the FREE local model
text2 = await self.wingman.local_ai.generate(t, system=...)  # free local single-turn -> str
```

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

Global defaults are tuned for summarization (low temperature). **Override for creative tasks.** Use `SamplingPreset` from `services/skill_local_ai.py` or pass `temperature` / `top_p` directly to `self.wingman.local_ai.generate()`, `.generate_sync()`, and `.summarize()`. Manual values override presets. See `SamplingPreset` docstring for available presets and values.

## Example Skills

| Skill | Type | Key Pattern |
|-------|------|-------------|
| [audio_device_changer](audio_device_changer/) | Hook (auto) | Audio routing via `on_play_to_user` |
| [thinking_sound](thinking_sound/) | Hook (auto) | Sound during processing |
| [hud](hud/) | Hook+Tool (auto) | HUD overlay, `color` properties |
| [image_generation](image_generation/) | Tool | `@tool` with `wait_response` |
| [timer](timer/) | Hook+Tool | State management, `unload()` cleanup |
| [vision_ai](vision_ai/) | Tool | Screen capture, discovery keywords |
| [file_manager](file_manager/) | Tool | Multi-tool skill |
| [spotify](spotify/) | Tool | External API integration |
| [uexcorp](uexcorp/) | Tool | Game integration, domain tags |
