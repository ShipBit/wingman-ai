# Migrating a Skill to the v3 Skill API

## If you're a user

If a skill shows an **"Incompatible (legacy)"** badge in Wingman AI, it was written for an
older Skill API and won't load until its author updates it. **Bundled skills are already
updated.** For a third-party skill, ask its author to migrate it (point them at this guide),
or remove it. Nothing on your side is broken — incompatible skills are simply skipped so the
app always boots.

## If you're a developer or coding agent

v3 makes the skill–runtime boundary explicit. Your skill talks to the runtime ONLY through
`self.wingman` (a controlled facade) and keeps its own concerns on `self`. Port mechanically
using the checklist + mapping table below.

**The one rule:** `self.` is *this skill* (its identity, config, storage, decorators,
lifecycle hooks). `self.wingman` is *the runtime* (everything about the wingman/app, grouped
into feature namespaces). No capability lives on both. If you reach for a runtime capability,
it is under a feature noun on `self.wingman`: `ai`, `local_ai`, `tts`, `audio`, `commands`,
`tools`, `conversation`, `memory`, `secrets`, `skills`.

### The 5 breaking changes

1. **Declare the API version.** Add `api_version: 3` to your `default_config.yaml`. Skills
   without it are treated as legacy and are not loaded.
2. **No work at import time.** No network, file I/O, or global side effects at module scope —
   the catalog import-probes your module without instantiating it. Do setup in `__init__` /
   `validate()` / `prepare()`.
3. **No raw LLM calls.** `self.llm_call(...)` and `self.wingman.actual_llm_call(...)` are gone.
   Use `self.wingman.ai.generate(...)` (a single-turn, **capped** side-call),
   `self.wingman.ai.converse(...)` (conversation-aware), or the free local model
   `self.wingman.local_ai.generate(...)` / `.summarize(...)`.
4. **Config is read-only.** `self.wingman.config` reads live values; writing raises
   `FacadeError`. Change things through capabilities (`self.wingman.tts.set_voice(...)`, the
   `self.wingman.commands.*` editors, `self.wingman.audio.set_output_device(...)`). Runtime
   TTS *provider* switching is removed — you may only change the voice on the current provider.
5. **No raw runtime access.** `audio_player`, `audio_library`, the registries
   (`tool_skills`, `mcp_registry`, `skill_registry`), `messages`, `secret_keeper`, `tower`,
   `local_ai_service`, `persistent_memory_service` are all gone from the facade. Use the
   feature namespaces.

### Old → new mapping

Everything you might reach for, and its v3 replacement. `await` where the v3 form is async
(noted by `await` in the cell).

#### LLM & local model

| v2 (removed) | v3 |
|---|---|
| `await self.llm_call(msgs)` | `await self.wingman.ai.generate(prompt, system=..., data=..., image=..., messages=...)` |
| `await self.wingman.llm_call(msgs)` | `await self.wingman.ai.generate(messages=msgs)` |
| `...get_wingman().actual_llm_call(msgs)` | `await self.wingman.ai.generate(messages=msgs)` |
| `await self.local_ai.support(text, sys)` | `await self.wingman.local_ai.generate(text, system=sys)` |
| `self.local_ai.support_sync(...)` | `self.wingman.local_ai.generate_sync(...)` |
| `await self.local_ai.summarize(...)` | `await self.wingman.local_ai.summarize(...)` |
| `await self.local_ai.embed(texts)` | `await self.wingman.local_ai.embed(texts)` |
| `self.local_ai.available` | `self.wingman.local_ai.available` |

> **`ai.generate` returns a `str`, not a completion object.** The old `actual_llm_call`
> returned a `ChatCompletion`; you used to read `completion.choices[0].message.content`.
> `ai.generate(...)` already gives you that text. If your code parsed JSON out of the
> completion, parse it straight from the returned string. It returns `""` (empty string)
> when the model gives nothing back — never `None` — and raises `FacadeError` only when the
> input is over the cap. So a v2 retry loop that re-called on a bad/empty completion should
> now: wrap the call in `try/except FacadeError` (cap errors won't fix themselves on retry —
> shorten instead) and treat an empty string as the "no answer, retry" case.

> **`ai.generate` is capped.** When conversation condensation is on, the combined input
> (system + prompt + data, plus a flat estimate per image) is limited (Wingman Pro: a fixed
> 8,000 tokens; own provider: `features.skill_max_input_tokens`, default 16,000). Over the cap
> it raises `FacadeError`, or truncates if you pass `auto_shorten=True`. For bulk text, reduce
> it first with the free `self.wingman.local_ai.summarize(...)`.

#### Memory (now its own namespace)

| v2 (removed) | v3 |
|---|---|
| `self.local_ai.memory_available` | `self.wingman.memory.available` |
| `await self.local_ai.remember_fact(c)` | `await self.wingman.memory.remember(c)` |
| `await self.local_ai.recall_memory(q)` | `await self.wingman.memory.recall(q)` |
| `await self.local_ai.memory_context(q)` | `await self.wingman.memory.context(q)` |
| `await self.local_ai.update_memory(id, c)` | `await self.wingman.memory.update(id, c)` |
| `await self.local_ai.memory_forget(q)` | `await self.wingman.memory.forget(q)` |
| `await self.local_ai.forget_memory_by_id(id)` | `await self.wingman.memory.forget_by_id(id)` |

#### Speech, audio & devices

| v2 (removed) | v3 |
|---|---|
| `await self.wingman.play_to_user(t)` | `await self.wingman.tts.speak(t)` |
| `await self.wingman.play_to_user(t, no_interrupt=True)` | `await self.wingman.tts.speak(t, interrupt=False)` |
| `await self.wingman.play_to_user(t, True, sound_config=sc)` | `await self.wingman.tts.speak(t, interrupt=False, sound_config=sc)` |
| `self.wingman.switch_tts_provider(...)` | removed — use `self.wingman.tts.set_voice(...)` |
| `self.wingman.audio_player.is_playing` | `self.wingman.audio.is_playing` |
| `await self.wingman.audio_library.start_playback(c, v)` | `await self.wingman.audio.play(c, volume=v)` |
| `await self.wingman.audio_library.stop_playback(c, f)` | `await self.wingman.audio.stop(c, fade_out=f)` |
| `audio_player.playback_events.subscribe("started", cb)` | `sub = self.wingman.audio.on_playback_started(cb)` |
| `audio_player.playback_events.subscribe("finished", cb)` | `sub = self.wingman.audio.on_playback_finished(cb)` |
| `audio_player.playback_events.unsubscribe(ev, cb)` | `sub.unsubscribe()` (keep the returned `Subscription`) |
| `self.wingman.audio.off_playback_started(cb)` / `off_playback_finished(cb)` | **removed** — capture the `Subscription` returned by `on_playback_started/finished(cb)` (e.g. `self._sub = ...`) and call `self._sub.unsubscribe()` in `unload()` |
| device read / change (HTTP hack) | `self.wingman.audio.output_device` / `.set_output_device(id)` (+ `input` variants) |

> **`tts.speak`'s `interrupt` is keyword-only and inverted from the old `no_interrupt`.**
> `play_to_user(t, no_interrupt=True)` → `tts.speak(t, interrupt=False)`. `interrupt=True`
> (the default) cuts off current playback immediately; `interrupt=False` waits for it.
> Watch for the **positional** form: old code often called `play_to_user(text, True)` — that
> `True` is the second positional arg `no_interrupt`, so it maps to `tts.speak(text, interrupt=False)`.

#### Conversation

| v2 (removed) | v3 |
|---|---|
| `self.wingman.get_conversation_history()` | `self.wingman.conversation.history()` |
| `self.wingman.messages` | `self.wingman.conversation.history()` |
| `await self.wingman.add_user_message(c)` | `await self.wingman.conversation.add_user(c)` |
| `await self.wingman.add_assistant_message(c)` | `await self.wingman.conversation.add_assistant(c)` |
| `await self.wingman.reset_conversation_history()` | `await self.wingman.conversation.reset()` |
| condenser summary | `self.wingman.conversation.summary` |
| summarize the live convo | `await self.wingman.conversation.summarize()` (free, local) |

#### Tools, commands & other skills

| v2 (removed) | v3 |
|---|---|
| `self.wingman.registry.has_tool(name)` | `self.wingman.tools.has(name)` |
| `self.wingman.registry.tool_names()` | `self.wingman.tools.names()` |
| `await self.wingman.registry.invoke(name, args)` | `await self.wingman.tools.invoke(name, args)` → returns a `ToolResult` |
| `self.wingman.tool_skills[name]` | `self.wingman.tools.source(name)` (human origin: skill / MCP server name) |
| `self.wingman.mcp_registry._tool_to_server` / `._manifests` | `self.wingman.tools.source(name)` / `.servers()` / `.describe(name)` |
| `self.wingman.skill_registry` | `self.wingman.skills.active()` / `self.wingman.skills.has(name)` |
| `self.wingman.get_command(name)` | `self.wingman.commands.get(name)` |
| `self.wingman.tower` (save commands) | `await self.wingman.commands.save()` |

> **`tools.invoke(...)` returns a `ToolResult`, not a 4-tuple.** The old call returned
> `(function_response, instant_response, used_skill, tool_label)`. Now:
> ```python
> result = await self.wingman.tools.invoke(name, args)
> result.response          # was function_response
> result.instant_response  # was instant_response
> result.skill             # was used_skill
> result.label             # was tool_label
> ```

> **`tools.source(name)` returns a name string, not the skill/server object.** It gives the
> human origin (the owning skill's name, or the MCP server's display name), or `None`. Two
> things the old raw registries gave you that `source()` does NOT:
> - **Skill-vs-MCP discrimination:** if you need to know whether a tool came from a skill or an
>   MCP server, compare against the MCP display names: `mcp = {s["display_name"] for s in
>   self.wingman.tools.servers()}; is_mcp = source in mcp`.
> - **Skill icon/logo:** if you reached into the skill object for its `logo.png` (e.g. old code
>   doing `inspect.getfile(skill.__class__)`), use `self.wingman.tools.icon(name)` — it returns
>   the owning skill's `logo.png` path, or `None` for MCP tools / skills without a logo. There
>   is still no general path to a skill's other files.

#### Secrets, threading, image, settings, logging

| v2 (removed) | v3 |
|---|---|
| `await self.retrieve_secret(name, errors)` | `await self.wingman.secrets.retrieve(name, errors)` |
| `self.wingman.secret_keeper` | `self.wingman.secrets.retrieve(...)` |
| `self.threaded_execution(fn, *a)` | `self.wingman.run_in_thread(fn, *a)` |
| `await self.wingman.generate_image(p)` | `await self.wingman.ai.generate_image(p)` |
| writing to `self.wingman.config.X` | a capability (e.g. `self.wingman.tts.set_voice(...)`) |
| `self.settings.X = ...` | read-only now; change devices via `self.wingman.audio.set_output_device(...)` |
| `self.printr.print(msg, ...)` | `self.log.info(msg)` / `self.log.warning(msg)` / `self.log.error(msg)` (pass `server_only=True` to keep a line out of the client toast) |

> **`self.log` vs `self.printr`.** `self.log.info/warning/error(message,
> server_only=False)` is the friendly logger — prefer it for plain status/debug/error
> messages (including the async `printr.print_async(msg, color=...)` calls: drop the
> `color`/`source`/`source_name`/`skill_name` kwargs and use `self.log.*`). BUT `self.printr`
> is **not removed** — keep using `self.printr.print_async(...)` for the cases `self.log`
> can't express, specifically anything passing **`additional_data=`** (e.g. shipping an
> `image_url`/`image_base64` payload to the client UI). Don't downgrade those to `self.log`.

### Gotchas that bite during migration

**Threaded TTS / async calls passed to `run_in_thread`.** `run_in_thread(fn, *args)` (like the
old `threaded_execution`) runs `fn` in a fresh thread, and if `fn` is a coroutine function it
spins up an event loop and runs `fn(*args)`. Two consequences:

- It calls `fn(*args)` **positionally**, so you cannot pass `tts.speak`'s keyword-only
  `interrupt`/`sound_config` through it. `run_in_thread(self.wingman.tts.speak, text, False)`
  fails — `speak` takes one positional arg.
- A `lambda`/`functools.partial` wrapper does NOT work: a `lambda` returning a coroutine isn't
  detected as a coroutine function (its result is never awaited), and `partial` has no
  `__name__` (the helper names the thread after `fn.__name__`).

The clean fix is a tiny async helper method on your skill, then thread *that*:

```python
# v2
self.threaded_execution(self.wingman.play_to_user, response, True)         # no_interrupt=True

# v3
async def _speak(self, text, sound_config=None):
    await self.wingman.tts.speak(text, interrupt=False, sound_config=sound_config)
...
self.wingman.run_in_thread(self._speak, response)
```

(If your threaded call had no special kwargs — e.g. `threaded_execution(self._loop)` — it's a
straight rename to `self.wingman.run_in_thread(self._loop)`.)

**Skills that pass their threading function into a helper/dependency.** If your skill handed
the old `self.threaded_execution` to a helper object (which then called it later), pass
`self.wingman.run_in_thread` instead — and check the helper's own call signature. `run_in_thread`
takes `(fn, *args)` (args spread positionally); a helper that stored args as a tuple and called
`stored_fn(fn, args_tuple)` must be updated to `stored_fn(fn, *args_tuple)`. Also rename any
helper method still literally called `threaded_execution` (the lockdown gate flags that name
anywhere in `skills/**`).

**Stale comments and strings.** Search for the old names in comments/docstrings too (e.g. a
comment mentioning `switch_tts_provider`). Update or delete them — leftover references read as
"still using the old API."

**Unused imports.** Removing the last use of `self.printr`/`play_to_user`/etc. often orphans an
import (`from api.enums import LogType`, `Benchmark`, …). Grep won't flag those — delete any
import your migration made dead so the module stays clean.

**`self.settings` is now a read-only view.** Reads still work
(`self.wingman.settings` is preferred); any assignment raises `FacadeError`.

### Migration checklist (run top to bottom)

1. Add `api_version: 3` to `default_config.yaml`.
2. Move any import-time work into `__init__`/`prepare`.
3. Grep your skill for each v2 form in the tables above and replace it. Don't forget submodules
   (`*/api/*.py`, helpers), not just `main.py`.
4. Fix the gotchas: threaded TTS helpers; `tools.invoke` unpacking → `ToolResult` attributes;
   `ai.generate` returns a string.
5. Remove any writes to `self.wingman.config` / `self.settings`; clean stale comments.
6. Boot Wingman, confirm your skill shows **no** incompatibility badge.
7. Exercise every capability path your skill uses (speak, audio, LLM, commands, secrets, tools).

### Before / after example

```python
# v2
class MySkill(Skill):
    async def react(self, data):
        text = await self.llm_call([{"role": "user", "content": data}])
        await self.wingman.play_to_user(text, no_interrupt=True)
        self.threaded_execution(self._bg)

# v3  (default_config.yaml: api_version: 3)
class MySkill(Skill):
    async def react(self, data):
        text = await self.wingman.ai.generate(data, system="React in character.")
        await self.wingman.tts.speak(text, interrupt=False)
        self.wingman.run_in_thread(self._bg)
```

### Calling other skills & MCP servers

Cross-skill / MCP invocation is a first-class, supported use case. Discover what's callable
right now, guard with `has(...)` / `servers()`, then `invoke`; degrade gracefully if the
skill/MCP the user needs isn't active.

```python
# Discover everything callable right now (your tools + other skills' + all MCP tools)
for tool in self.wingman.tools.all():
    self.log.info(f"{tool.name} (from {tool.source}) — {tool.description}", server_only=True)

# Call another ACTIVE skill's tool by name, guarding first
if self.wingman.tools.has("take_screenshot"):
    result = await self.wingman.tools.invoke("take_screenshot", {})
    self.log.info(f"{result.response} (from {result.skill})")

# Call your own MCP server's tool (devs often ship an MCP for their datasource)
servers = {s["display_name"] for s in self.wingman.tools.servers()}
if "My Data MCP" in servers and self.wingman.tools.has("mydata_query"):
    res = await self.wingman.tools.invoke("mydata_query", {"q": "ships"})
    data = res.response
else:
    self.log.warning("My Data MCP not active; skipping enriched lookup")
```

> MCP tool names are prefixed by the registry — use the name exactly as it appears in
> `self.wingman.tools.names()` / `.all()`, not the bare tool name.

### What's available to call

See `skills/README.md` → "The `self.wingman` facade API" for the full reference, and use
`self.wingman.tools.all()` at runtime to enumerate every callable function (with params).
