"""Facade infrastructure shared by the skill-facing WingmanContext.

Houses the single `FacadeError` exception and the `ReadOnlyConfigView` proxy that
lets skills *read* the live Wingman config freely while making any *write* impossible.

Skills that legitimately need to change something use a sanctioned capability
(e.g. ``ctx.tts.set_voice(...)``) instead of mutating config by reference.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, Optional

from pydantic import BaseModel

if TYPE_CHECKING:
    from wingmen.wingman import Wingman


class FacadeError(Exception):
    """Raised when a skill tries to do something the facade does not allow.

    The message always names the sanctioned capability to use instead, so a skill
    author gets actionable feedback (we don't gate the catalog on this).
    """


@dataclass
class ToolResult:
    """Result of ctx.tools.invoke(). `response` is fed to the AI; `instant_response`
    is spoken verbatim if present; `skill`/`label` identify what ran."""
    response: str
    instant_response: str = ""
    skill: Optional[str] = None
    label: Optional[str] = None


@dataclass
class ToolDescriptor:
    """Describes one callable function available to the wingman (skill tool, MCP tool,
    or command). `parameters` is the JSON-schema object for its arguments."""
    name: str
    source: Optional[str]
    description: Optional[str]
    parameters: dict


class Subscription:
    """Handle returned by ctx.audio.on_playback_*; call unsubscribe() to detach."""

    __slots__ = ("_off", "_done")

    def __init__(self, off: Callable[[], None]) -> None:
        self._off = off
        self._done = False

    def unsubscribe(self) -> None:
        """Detach the callback. Safe to call more than once."""
        if not self._done:
            self._done = True
            self._off()


class CommandCategory:
    """A command category (group) the user sees. Wraps a CommandCategoryConfig."""

    __slots__ = ("id", "name", "_commands")

    def __init__(self, id: str, name: str, commands: Optional[list] = None) -> None:
        self.id = id
        self.name = name
        self._commands = commands if commands is not None else []

    def add(self, command) -> None:
        """Put a command in this category (sets its category_id)."""
        command.category_id = self.id
        if command not in self._commands:
            self._commands.append(command)


class ReadOnlyConfigView:
    """A recursive, read-only proxy over a pydantic model (e.g. ``WingmanConfig``).

    Attribute reads pass through to the live model — so the view never goes stale —
    and nested models / lists / dicts are wrapped recursively so a skill cannot grab
    a mutable inner object and write through it. Any attempt to *set* an attribute
    raises :class:`FacadeError`.

    Example::

        view = ReadOnlyConfigView(wingman.config)
        view.openai.tts_voice            # reads the live value
        view.features.tts_provider       # nested read, also live
        view.openai.tts_voice = "nova"   # -> FacadeError
    """

    __slots__ = ("_model",)

    def __init__(self, model: BaseModel) -> None:
        # Bypass our own __setattr__ to store the wrapped model.
        object.__setattr__(self, "_model", model)

    # --- reads pass through (recursively wrapped) ---

    def __getattr__(self, name: str) -> Any:
        # __getattr__ only fires for names not found normally; since the only real
        # slot is `_model`, every config attribute access lands here.
        if name.startswith("__") and name.endswith("__"):
            # Let dunder lookups (e.g. during copy/pickle) fail normally.
            raise AttributeError(name)
        value = getattr(object.__getattribute__(self, "_model"), name)
        return _wrap(value)

    # --- writes are forbidden ---

    def __setattr__(self, name: str, value: Any) -> None:
        raise FacadeError(
            f"Wingman config is read-only for skills — cannot set '{name}'. "
            f"Use the matching facade capability instead (e.g. ctx.tts.set_voice(...), "
            f"ctx.audio.set_output_device(...), ctx.commands.*)."
        )

    def __delattr__(self, name: str) -> None:
        raise FacadeError(
            f"Wingman config is read-only for skills — cannot delete '{name}'."
        )

    # --- ergonomics ---

    def __repr__(self) -> str:
        return f"ReadOnlyConfigView({object.__getattribute__(self, '_model')!r})"

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, ReadOnlyConfigView):
            other = object.__getattribute__(other, "_model")
        return object.__getattribute__(self, "_model") == other

    def __hash__(self) -> int:
        return id(object.__getattribute__(self, "_model"))

    def __deepcopy__(self, memo):
        # A deep copy detaches from the live config: return a real, MUTABLE copy of
        # the underlying model. Skills legitimately do
        # ``copy.deepcopy(ctx.config.sound)`` to build a customized config to pass to
        # playback — they get an independent object, not a read-only view.
        import copy

        return copy.deepcopy(object.__getattribute__(self, "_model"), memo)


class _ReadOnlyList:
    """Read-only, recursively-wrapping view over a list. Indexing/iteration/len work;
    mutation raises :class:`FacadeError`."""

    __slots__ = ("_items",)

    def __init__(self, items: list) -> None:
        object.__setattr__(self, "_items", items)

    def __getitem__(self, index: Any) -> Any:
        result = object.__getattribute__(self, "_items")[index]
        if isinstance(index, slice):
            return tuple(_wrap(v) for v in result)
        return _wrap(result)

    def __iter__(self):
        return (_wrap(v) for v in object.__getattribute__(self, "_items"))

    def __len__(self) -> int:
        return len(object.__getattribute__(self, "_items"))

    def __contains__(self, item: Any) -> bool:
        if isinstance(item, ReadOnlyConfigView):
            item = object.__getattribute__(item, "_model")
        return item in object.__getattribute__(self, "_items")

    def __setitem__(self, *_: Any) -> None:
        raise FacadeError("This config list is read-only for skills.")

    def __delitem__(self, *_: Any) -> None:
        raise FacadeError("This config list is read-only for skills.")

    def __repr__(self) -> str:
        return f"_ReadOnlyList({object.__getattribute__(self, '_items')!r})"


def _wrap(value: Any) -> Any:
    """Wrap a value so it cannot be mutated through the read-only view."""
    if isinstance(value, BaseModel):
        return ReadOnlyConfigView(value)
    if isinstance(value, list):
        return _ReadOnlyList(value)
    if isinstance(value, dict):
        return MappingProxyType({k: _wrap(v) for k, v in value.items()})
    # Scalars, enums, tuples, None, callables (e.g. model_dump) pass through as-is.
    return value


def apply_voice_to_current_provider(config: Any, voice: Any) -> tuple[Any, str] | None:
    """Write ``voice`` into the config field of the wingman's CURRENT TTS provider
    (and toggle off streaming where the provider requires it).

    Returns ``(voice_name, provider_label)`` for display, or ``None`` if the current
    provider isn't a supported voice target. Pure: only mutates ``config`` — no I/O,
    no provider rebuild — so it can be unit-tested in isolation. Provider switching is
    deliberately NOT handled here; this only ever touches the active provider.
    """
    from api.enums import TtsProvider, WingmanProTtsProvider

    provider = config.features.tts_provider

    if provider == TtsProvider.WINGMAN_PRO:
        # Wingman Pro TTS is only ever Azure or Inworld (per WingmanProTtsProvider).
        subprovider = config.wingman_pro.tts_provider
        if subprovider == WingmanProTtsProvider.AZURE:
            config.azure.tts.voice = voice
            return voice, "Wingman Pro / Azure TTS"
        if subprovider == WingmanProTtsProvider.INWORLD:
            config.inworld.voice_id = voice
            config.inworld.output_streaming = False
            return voice, "Wingman Pro / Inworld"
        return None
    if provider == TtsProvider.OPENAI:
        config.openai.tts_voice = voice
        return getattr(voice, "value", voice), "OpenAI"
    if provider == TtsProvider.ELEVENLABS:
        config.elevenlabs.voice = voice
        config.elevenlabs.output_streaming = False
        return getattr(voice, "name", None) or getattr(voice, "id", voice), "Elevenlabs"
    if provider == TtsProvider.AZURE:
        config.azure.tts.voice = voice
        return voice, "Azure TTS"
    if provider == TtsProvider.XVASYNTH:
        config.xvasynth.voice = voice
        return getattr(voice, "voice_name", voice), "XVASynth"
    if provider == TtsProvider.EDGE_TTS:
        config.edge_tts.voice = voice
        return voice, "Edge TTS"
    if provider == TtsProvider.HUME:
        config.hume.voice = voice
        return voice, "Hume"
    if provider == TtsProvider.INWORLD:
        config.inworld.voice_id = voice
        config.inworld.output_streaming = False
        return voice, "InWorld"
    if provider == TtsProvider.POCKET_TTS:
        config.pocket_tts.voice = voice
        config.pocket_tts.output_streaming = False
        return voice, "PocketTTS"
    if provider == TtsProvider.OPENAI_COMPATIBLE:
        config.openai_compatible_tts.voice = voice
        config.openai_compatible_tts.output_streaming = False
        return voice, "OpenAI Compatible"
    return None


# Wingman Pro pays per-use on our dime, so it gets a fixed, lower side-call cap that
# users cannot raise. Own-provider users use config.features.skill_max_input_tokens.
WINGMAN_PRO_MAX_INPUT_TOKENS = 8000
# Flat per-image token estimate — we must NOT count the raw base64 string (it would be
# enormous and falsely trip the cap). Mirrors a high-detail image's real token cost.
IMAGE_TOKEN_ESTIMATE = 1000


def skill_input_cap(config: Any) -> int:
    """Max input tokens skill-originated content (a ctx.ai.generate side-call OR a
    tool/MCP response) may feed the main model. Wingman Pro is hardcoded lower (we pay);
    own providers use config.features.skill_max_input_tokens."""
    from api.enums import ConversationProvider

    features = config.features
    if features.conversation_provider == ConversationProvider.WINGMAN_PRO:
        return WINGMAN_PRO_MAX_INPUT_TOKENS
    return getattr(features, "skill_max_input_tokens", 16000)


def _count_message_tokens(messages: list) -> int:
    """Token count of a prebuilt message list — string contents are counted directly;
    multimodal image parts are charged a flat IMAGE_TOKEN_ESTIMATE (never the base64)."""
    from services.token_utils import count_tokens

    total = 0
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            total += count_tokens(content)
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    total += count_tokens(part.get("text", ""))
                elif part.get("type") == "image_url":
                    total += IMAGE_TOKEN_ESTIMATE
    return total


class SkillAi:
    """Sanctioned access to the main (cloud) AI model for skills.

    ``generate`` is a single-turn side-call: the skill supplies its own prompt/system,
    the result is NOT added to the conversation, and there's no history/condensation.
    This is the one chokepoint for the input-token cap (and future per-skill limits).
    Bulk reduction belongs on the local model (``self.local_ai.summarize``).
    """

    def __init__(self, wingman: "Wingman") -> None:
        self._wingman = wingman

    def _max_input_tokens(self) -> int:
        return skill_input_cap(self._wingman.config)

    async def generate(
        self,
        prompt: str = "",
        *,
        system: str | None = None,
        data: str | None = None,
        image: str | None = None,
        messages: list | None = None,
        auto_shorten: bool = False,
    ) -> str:
        """Single-turn generation on the main model. Returns the response text.

        ``prompt`` is the instruction; ``data`` is an optional larger payload appended
        to it; ``image`` is an optional data-URL for vision. Pass ``messages`` (a prebuilt
        OpenAI-style message list) to send your own turns directly — it is sent as-is and
        ``prompt``/``system``/``data``/``image`` are ignored. When conversation
        condensation is enabled the combined input is capped (see class docstring):
        over the cap raises :class:`FacadeError`, or (for the prompt/data path) truncates
        if ``auto_shorten``. The ``messages`` path can't be auto-shortened — it raises.
        """
        from services.token_utils import count_tokens, truncate_to_tokens

        features = self._wingman.config.features

        # Prebuilt message-list path: send the skill's own turns directly (still capped).
        if messages is not None:
            if features.condense_conversation:
                cap = self._max_input_tokens()
                total = _count_message_tokens(messages)
                if total > cap:
                    raise FacadeError(
                        f"Skill tried to send ~{total} tokens to the main model, but the "
                        f"limit is {cap}. Reduce the messages or pre-summarize them cheaply "
                        f"with self.local_ai.summarize(...). (A structured message list can't "
                        f"be auto-shortened — trim it yourself. On your own AI provider you can "
                        f"raise features.skill_max_input_tokens or turn off condensation; on "
                        f"Wingman Pro the limit is fixed.)"
                    )
            completion = await self._wingman.actual_llm_call(messages)
            if completion and completion.choices:
                return completion.choices[0].message.content or ""
            return ""

        user_text = prompt if not data else f"{prompt}\n\n{data}"

        if features.condense_conversation:
            cap = self._max_input_tokens()
            system_tokens = count_tokens(system) if system else 0
            image_tokens = IMAGE_TOKEN_ESTIMATE if image else 0
            total = system_tokens + count_tokens(user_text) + image_tokens
            if total > cap:
                if auto_shorten:
                    budget = max(0, cap - system_tokens - image_tokens)
                    user_text = truncate_to_tokens(user_text, budget)
                else:
                    raise FacadeError(
                        f"Skill tried to send ~{total} tokens to the main model, but the "
                        f"limit is {cap}. Reduce the input or pre-summarize it cheaply with "
                        f"self.local_ai.summarize(...). (On your own AI provider you can raise "
                        f"features.skill_max_input_tokens or turn off conversation condensation; "
                        f"on Wingman Pro the limit is fixed.)"
                    )

        messages: list = []
        if system:
            messages.append({"role": "system", "content": system})
        if image:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": image, "detail": "high"}},
                    ],
                }
            )
        else:
            messages.append({"role": "user", "content": user_text})

        completion = await self._wingman.actual_llm_call(messages)
        if completion and completion.choices:
            return completion.choices[0].message.content or ""
        return ""

    async def converse(self, user_message: str) -> str:
        """Conversation-aware reply: uses the wingman's own system prompt + live history
        and is subject to the normal auto-condensation. Use generate() for off-topic
        side work that should NOT join the conversation."""
        await self._wingman.add_user_message(user_message)
        messages = list(self._wingman.conversation.messages)
        completion = await self._wingman.actual_llm_call(messages)
        text = ""
        if completion and completion.choices:
            text = completion.choices[0].message.content or ""
        if text:
            await self._wingman.conversation.add_assistant_message(text)
        return text

    async def summarize(self, text: str, *, system: str | None = None) -> str:
        """Summarize text via the main CLOUD model (capped like generate). For bulk/cheap
        summarization prefer ctx.local_ai.summarize() (free, local)."""
        return await self.generate(text, system=system or "Summarize the following concisely.")

    async def generate_image(self, prompt: str) -> str:
        """Generate an image from a prompt; returns the generated file path/URL."""
        return await self._wingman.generate_image(prompt)


def _text_or_empty(resp) -> str:
    return resp.text if resp is not None and getattr(resp, "text", None) else ""


class SkillLocalAiView:
    """Free, local model. generate()/summarize() return plain strings ("" if the local
    model is unavailable — check `available`). Tune with a SamplingPreset or temperature/top_p."""

    def __init__(self, local_ai) -> None:
        self._la = local_ai

    @property
    def available(self) -> bool:
        return bool(self._la.available)

    async def generate(self, text: str, *, system: str = "", preset=None,
                       temperature=None, top_p=None, top_k=None) -> str:
        resp = await self._la.support(text, system_prompt=system, preset=preset,
                                      temperature=temperature, top_p=top_p, top_k=top_k)
        return _text_or_empty(resp)

    def generate_sync(self, text: str, *, system: str = "", preset=None,
                     temperature=None, top_p=None, top_k=None) -> str:
        resp = self._la.support_sync(text, system_prompt=system, preset=preset,
                                     temperature=temperature, top_p=top_p, top_k=top_k)
        return _text_or_empty(resp)

    async def summarize(self, text: str, *, instruction: str = "", preset=None,
                       temperature=None, top_p=None) -> str:
        resp = await self._la.summarize(text, instruction=instruction, preset=preset,
                                        temperature=temperature, top_p=top_p)
        return _text_or_empty(resp)

    def summarize_sync(self, text: str, *, instruction: str = "", preset=None,
                      temperature=None, top_p=None) -> str:
        resp = self._la.summarize_sync(text, instruction=instruction, preset=preset,
                                       temperature=temperature, top_p=top_p)
        return _text_or_empty(resp)

    async def embed(self, texts: list[str]):
        return await self._la.embed(texts)

    def embed_sync(self, texts: list[str]):
        return self._la.embed_sync(texts)


class SkillMemory:
    """Local persistent memory (free). Returns None/empty when unavailable (check `available`)."""

    def __init__(self, local_ai) -> None:
        self._la = local_ai

    @property
    def available(self) -> bool:
        return bool(getattr(self._la, "memory_available", False))

    async def remember(self, content: str, **kw):
        return await self._la.remember_fact(content, **kw)

    async def recall(self, query: str, **kw):
        return await self._la.recall_memory(query, **kw)

    async def context(self, query: str, max_tokens: int = 500) -> str:
        return await self._la.memory_context(query, max_tokens=max_tokens)

    async def update(self, entry_id: int, new_content: str) -> bool:
        return await self._la.update_memory(entry_id, new_content)

    async def forget(self, query: str) -> bool:
        return await self._la.memory_forget(query)

    async def forget_by_id(self, entry_id: int) -> bool:
        return await self._la.forget_memory_by_id(entry_id)


class SkillTools:
    """Discover and invoke the wingman's callable functions (skill @tools, MCP tools,
    commands) by name. Scoped to enumerable tools — not arbitrary attribute access."""

    def __init__(self, wingman: "Wingman") -> None:
        self._wingman = wingman

    def _tool_defs(self) -> dict:
        return {t.get("function", {}).get("name"): t.get("function", {})
                for t in self._wingman.build_tools()
                if t.get("function", {}).get("name")}

    def names(self) -> set[str]:
        return set(self._tool_defs().keys())

    def has(self, name: str) -> bool:
        return name in self._tool_defs()

    def source(self, name: str) -> str | None:
        """Human-readable origin of a tool: the owning skill's name, or the MCP server's
        display name. Prefers mcp_registry PUBLIC accessors; falls back to internals."""
        skill = (self._wingman.tool_skills or {}).get(name)
        if skill is not None:
            return getattr(skill, "name", None)
        mcp = self._wingman.mcp_registry
        if not mcp:
            return None
        try:
            for manifest in mcp.get_connected_servers():
                sname = getattr(manifest, "name", None)
                tools = mcp.get_server_tools(sname) if sname else []
                tool_names = {getattr(t, "prefixed_name", None) or getattr(t, "name", None) for t in tools}
                if name in tool_names:
                    return getattr(manifest, "display_name", sname)
        except Exception:
            pass
        # Fallback to internals if the public shapes differ.
        server = getattr(mcp, "_tool_to_server", {}).get(name)
        manifests = getattr(mcp, "_manifests", {})
        if server and server in manifests:
            return getattr(manifests[server], "display_name", server)
        return None

    def describe(self, name: str) -> "ToolDescriptor | None":
        fn = self._tool_defs().get(name)
        if not fn:
            return None
        return ToolDescriptor(name=name, source=self.source(name),
                              description=fn.get("description"),
                              parameters=fn.get("parameters", {}))

    def all(self) -> tuple:
        return tuple(self.describe(n) for n in self._tool_defs())

    def icon(self, name: str) -> str | None:
        """Filesystem path to the owning skill's ``logo.png`` for a tool, or ``None`` (MCP
        tools, commands, or skills without a logo). Lets a UI show a per-tool icon without
        touching the skill object."""
        skill = (self._wingman.tool_skills or {}).get(name)
        if skill is None:
            return None
        import inspect
        import os

        try:
            skill_dir = os.path.dirname(inspect.getfile(skill.__class__))
            logo_path = os.path.join(skill_dir, "logo.png")
            return logo_path if os.path.exists(logo_path) else None
        except Exception:
            return None

    def servers(self) -> tuple:
        """Active MCP servers as dicts: name, display_name, connected, tools (prefixed names)."""
        mcp = self._wingman.mcp_registry
        if not mcp:
            return ()
        out = []
        for manifest in mcp.get_connected_servers():
            sname = getattr(manifest, "name", None)
            tools = mcp.get_server_tools(sname) if sname else []
            out.append({
                "name": sname,
                "display_name": getattr(manifest, "display_name", sname),
                "connected": bool(getattr(manifest, "is_connected", True)),
                "tools": [getattr(t, "prefixed_name", None) or getattr(t, "name", None) for t in tools],
            })
        return tuple(out)

    async def invoke(self, name: str, arguments: dict | None = None) -> "ToolResult":
        result = await self._wingman.execute_command_by_function_call(name, arguments or {})
        func_resp, instant_resp, used_skill, label = (list(result) + [None, None, None, None])[:4]
        # execute_command_by_function_call returns the owning Skill object in slot 3;
        # ToolResult.skill is the skill NAME (str | None) per the public contract.
        skill_name = getattr(used_skill, "name", used_skill)
        return ToolResult(response=func_resp or "", instant_response=instant_resp or "",
                          skill=skill_name, label=label)


class SkillCommands:
    """Sanctioned access to the wingman's commands.

    Commands are user-owned config that skills like QuickCommands are designed to
    edit (e.g. attaching learned instant-activation phrases). ``get``/``all`` return
    the live command objects so a skill can adjust them, and ``save`` persists the
    commands section to disk.
    """

    def __init__(self, wingman: "Wingman") -> None:
        self._wingman = wingman

    def get(self, name: str):
        """Return the live CommandConfig with this name, or None."""
        return self._wingman.command_executor.get_command(name)

    def all(self) -> tuple:
        """All configured commands (live objects, as a read-only tuple)."""
        return tuple(self._wingman.config.commands or [])

    async def save(self) -> bool:
        """Persist the wingman's commands section to disk. Returns True on success."""
        if not self._wingman.tower:
            return False
        return self._wingman.tower.save_wingman_commands(self._wingman.name)

    def add(self, command, *, category=None) -> None:
        """Add a command (optionally into a category). Call save() to persist."""
        if self._wingman.config.commands is None:
            self._wingman.config.commands = []
        if category is not None:
            command.category_id = category.id if isinstance(category, CommandCategory) else category
        self._wingman.config.commands.append(command)

    def remove(self, name: str) -> None:
        """Remove a command by name. Call save() to persist."""
        cmds = self._wingman.config.commands or []
        self._wingman.config.commands = [c for c in cmds if c.name != name]

    def add_category(self, name: str) -> "CommandCategory":
        """Create (or return the existing) category with this name. Idempotent by name."""
        from api.interface import CommandCategoryConfig
        import uuid
        cats = self._wingman.config.command_categories
        if cats is None:
            cats = self._wingman.config.command_categories = []
        for cfg in cats:
            if cfg.name == name:
                return CommandCategory(id=cfg.id, name=cfg.name, commands=self._commands_in(cfg.id))
        cfg = CommandCategoryConfig(id=str(uuid.uuid4()), name=name)
        cats.append(cfg)
        return CommandCategory(id=cfg.id, name=cfg.name)

    def update_category(self, category: "CommandCategory") -> None:
        for cfg in (self._wingman.config.command_categories or []):
            if cfg.id == category.id:
                cfg.name = category.name
                return

    def delete_category(self, id_or_name: str) -> None:
        cats = self._wingman.config.command_categories or []
        self._wingman.config.command_categories = [
            c for c in cats if c.id != id_or_name and c.name != id_or_name
        ]

    def categories(self) -> tuple:
        return tuple(
            CommandCategory(id=c.id, name=c.name, commands=self._commands_in(c.id))
            for c in (self._wingman.config.command_categories or [])
        )

    def _commands_in(self, category_id: str) -> list:
        return [c for c in (self._wingman.config.commands or []) if getattr(c, "category_id", None) == category_id]

    def register_function(self, func, *, label=None, description=None,
                          respond="ai", parameters=None) -> str:
        """Register a live skill method as a bindable command function at runtime — the
        dynamic equivalent of @command_action. Returns the registered function name."""
        from skills.skill_base import CommandActionDefinition
        skill = getattr(func, "__self__", None)
        if skill is None:
            raise FacadeError("register_function requires a bound skill method (func.__self__).")
        cad = CommandActionDefinition(func=func.__func__, label=label,
                                      description=description, respond=respond)
        skill._command_actions[cad.name] = cad
        self._wingman.skill_manager.command_action_skills[(skill.name, cad.name)] = skill
        return cad.name

    def unregister_function(self, name: str) -> None:
        registry = self._wingman.skill_manager.command_action_skills
        for key in [k for k in registry if k[1] == name]:
            skill = registry.pop(key)
            skill._command_actions.pop(name, None)

    def add_skill_command(self, name: str, func, *, category=None,
                          instant_phrases=None, respond="ai") -> None:
        """One call: register `func` as a command function, build a command named `name`
        bound to it (with optional instant-activation phrases), categorize it. Call save()."""
        from api.interface import CommandConfig, CommandActionConfig, CommandSkillActionConfig
        fn_name = self.register_function(func, label=name, respond=respond)
        skill = func.__self__
        action = CommandActionConfig(
            skill_action=CommandSkillActionConfig(skill_name=skill.name, function_name=fn_name)
        )
        command = CommandConfig(name=name, actions=[action])
        if instant_phrases:
            command.instant_activation = list(instant_phrases)
        self.add(command, category=category)


class SkillAudio:
    """Sanctioned audio capabilities for skills.

    Lets skills play/stop their own audio files, observe playback start/stop, and
    read whether the wingman is currently speaking — without reaching into the raw
    ``audio_player`` / ``audio_library`` internals.
    """

    def __init__(self, wingman: "Wingman") -> None:
        self._wingman = wingman

    @property
    def is_playing(self) -> bool:
        """True while the wingman is currently playing TTS/audio."""
        return bool(self._wingman.audio_player.is_playing)

    async def play(self, audio_config: Any, *, volume: float = 1.0) -> None:
        """Start playback of a skill-owned audio file."""
        await self._wingman.audio_library.start_playback(audio_config, volume)

    async def stop(self, audio_config: Any, *, fade_out: float = 0.5) -> None:
        """Stop playback of a skill-owned audio file (optionally fading out)."""
        await self._wingman.audio_library.stop_playback(audio_config, fade_out)

    def on_playback_started(self, callback: Any) -> "Subscription":
        """Observe playback start. Returns a Subscription — call .unsubscribe() to detach."""
        self._wingman.audio_player.playback_events.subscribe("started", callback)
        return Subscription(
            lambda: self._wingman.audio_player.playback_events.unsubscribe("started", callback)
        )

    def on_playback_finished(self, callback: Any) -> "Subscription":
        """Observe playback finish. Returns a Subscription — call .unsubscribe() to detach."""
        self._wingman.audio_player.playback_events.subscribe("finished", callback)
        return Subscription(
            lambda: self._wingman.audio_player.playback_events.unsubscribe("finished", callback)
        )

    # --- output/input device control (in-process; replaces HTTP-to-backend hacks) ---

    @property
    def output_device(self):
        """The currently selected audio OUTPUT device settings (read-only)."""
        audio = self._wingman.settings.audio
        return audio.output if audio else None

    @property
    def input_device(self):
        """The currently selected audio INPUT device settings (read-only)."""
        audio = self._wingman.settings.audio
        return audio.input if audio else None

    async def set_output_device(self, device_id: int | None) -> bool:
        """Switch the system audio OUTPUT device (in-process; persists + re-routes playback).
        Pass None to reset to the system default. Returns False if device control is
        unavailable (no settings service)."""
        return await self._set_devices(output_device=device_id)

    async def set_input_device(self, device_id: int | None) -> bool:
        """Switch the system audio INPUT device (in-process). Pass None to reset to the
        system default. Returns False if device control is unavailable."""
        return await self._set_devices(input_device=device_id)

    async def _set_devices(self, input_device: int | None = None,
                           output_device: int | None = None) -> bool:
        settings_service = getattr(self._wingman, "settings_service", None)
        if settings_service is None:
            return False
        # Resolves the device, persists settings_config.audio, and publishes
        # 'audio_devices_changed' which re-routes playback — same path as the HTTP API.
        await settings_service.set_audio_devices(
            input_device=input_device, output_device=output_device
        )
        return True


class SkillTts:
    """Sanctioned TTS capabilities for skills.

    The ONE thing skills may change about TTS is the voice — on the *currently
    selected* provider only. Switching the TTS provider at runtime is intentionally
    not offered (skills must not move a paying user onto a different provider).
    """

    def __init__(self, wingman: "Wingman") -> None:
        self._wingman = wingman

    @property
    def voice(self):
        """The voice configured on the current TTS provider (read)."""
        from api.enums import TtsProvider

        config = self._wingman.config
        provider = config.features.tts_provider
        mapping = {
            TtsProvider.OPENAI: lambda: config.openai.tts_voice,
            TtsProvider.ELEVENLABS: lambda: config.elevenlabs.voice,
            TtsProvider.AZURE: lambda: config.azure.tts.voice,
            TtsProvider.EDGE_TTS: lambda: config.edge_tts.voice,
            TtsProvider.XVASYNTH: lambda: config.xvasynth.voice,
            TtsProvider.HUME: lambda: config.hume.voice,
            TtsProvider.INWORLD: lambda: config.inworld.voice_id,
            TtsProvider.POCKET_TTS: lambda: config.pocket_tts.voice,
            TtsProvider.OPENAI_COMPATIBLE: lambda: config.openai_compatible_tts.voice,
        }
        getter = mapping.get(provider)
        return getter() if getter else None

    async def voices(self) -> list:
        """ALL voices available on the current provider (not just the user-picked ones).

        Best-effort: providers that need a secret/network round-trip or that aren't
        cheaply enumerable here return ``[]`` rather than raising. Providers whose live
        TTS instance exposes a cached/static voice list are read from it. Full
        per-provider enumeration lives in the VoiceService HTTP API; skills that need the
        exhaustive list should call that. (Correctness is smoke-checked at boot.)
        """
        from api.enums import TtsProvider

        config = self._wingman.config
        provider = config.features.tts_provider

        # Prefer the live TTS instance if it advertises a voice list (e.g. static providers
        # like Edge / Pocket cache their catalogue).
        tts = getattr(self._wingman, "tts", None)
        for attr in ("available_voices", "voices", "get_available_voices"):
            candidate = getattr(tts, attr, None) if tts is not None else None
            if candidate is None:
                continue
            try:
                if callable(candidate):
                    result = candidate()
                    if hasattr(result, "__await__"):
                        result = await result
                else:
                    result = candidate
                if result:
                    return list(result)
            except Exception:
                pass

        # Pocket TTS can enumerate its local voices without a secret/network call.
        if provider == TtsProvider.POCKET_TTS:
            pocket = getattr(self._wingman, "pocket_tts", None) or getattr(tts, "pocket_tts", None)
            getter = getattr(pocket, "get_available_voices", None)
            if getter is not None:
                try:
                    result = getter()
                    if hasattr(result, "__await__"):
                        result = await result
                    return list(result or [])
                except Exception:
                    return []

        # Everything else (OpenAI, ElevenLabs, Azure, Hume, Inworld, OpenAI-compatible,
        # XVASynth) needs a secret and/or network call we don't make here.
        return []

    async def speak(self, text: str, *, interrupt: bool = True, sound_config=None) -> None:
        """Say text in the wingman's voice. interrupt=True (default) speaks immediately,
        cutting off current playback; interrupt=False waits for it to finish."""
        await self._wingman.play_to_user(text, no_interrupt=(not interrupt),
                                         sound_config=sound_config)

    async def set_voice(self, voice: Any, errors: list | None = None) -> str:
        """Set the voice on the wingman's current TTS provider and rebuild the TTS
        instance so it takes effect immediately.

        ``voice`` must be a voice value appropriate for the current provider (the
        same type that provider's config field holds). Returns a human-readable
        result string suitable for a ``respond="speak"`` command action.
        """
        from services.provider_factory import ProviderFactory

        config = self._wingman.config
        applied = apply_voice_to_current_provider(config, voice)
        if applied is None:
            provider = config.features.tts_provider
            return (
                "Voice change failed: unsupported TTS provider "
                f"'{getattr(provider, 'value', provider)}'."
            )
        voice_name, provider_label = applied

        # Rebuild the TTS instance so the new voice is used (same provider, no switch).
        factory = ProviderFactory(
            config=config,
            settings=self._wingman.settings,
            secret_keeper=self._wingman.secret_keeper,
            shared_providers=self._wingman._shared_providers,
            wingman_name=self._wingman.name,
        )
        new_tts = await factory.create_tts(errors or [])
        if not new_tts:
            return "Voice change failed while reinitializing the TTS provider."
        self._wingman.tts = new_tts
        return f"Switched {self._wingman.name}'s voice to {voice_name} ({provider_label})."


class SkillConversation:
    """Read + append to the live conversation, and summarize it (free, local)."""

    def __init__(self, wingman: "Wingman") -> None:
        self._wingman = wingman

    def history(self) -> list[dict]:
        """Shallow copy of the live history. Don't mutate individual messages."""
        return list(self._wingman.conversation.messages)

    @property
    def summary(self) -> str:
        return self._wingman.condenser.summary or ""

    async def add_user(self, content: str) -> None:
        await self._wingman.add_user_message(content)

    async def add_assistant(self, content: str) -> None:
        await self._wingman.conversation.add_assistant_message(content)

    async def reset(self) -> None:
        await self._wingman.reset_conversation_history()

    async def summarize(self) -> str:
        """Summarize the live conversation via the FREE local model. '' if unavailable."""
        from services.skill_local_ai import SkillLocalAI
        text = "\n".join(
            f"{m.get('role','')}: {m.get('content','')}"
            for m in self._wingman.conversation.messages
            if isinstance(m.get("content"), str)
        )
        return await SkillLocalAiView(SkillLocalAI(self._wingman)).summarize(text)


class SkillSecrets:
    """Fetch stored secrets (prompts the user if missing)."""

    def __init__(self, wingman: "Wingman") -> None:
        self._wingman = wingman

    async def retrieve(self, name: str, errors: list | None = None) -> str | None:
        return await self._wingman.retrieve_secret(name, errors if errors is not None else [])


class SkillSkills:
    """Read which skills are currently loaded on this wingman."""

    def __init__(self, wingman: "Wingman") -> None:
        self._wingman = wingman

    def active(self) -> tuple:
        out = []
        for s in self._wingman.skill_manager.skills:
            out.append({"name": getattr(s, "name", None),
                        "display_name": getattr(getattr(s, "config", None), "display_name", None)})
        return tuple(out)

    def has(self, name: str) -> bool:
        """Is a skill with this name currently loaded? (symmetric with ctx.tools.has)"""
        return any(getattr(s, "name", None) == name for s in self._wingman.skill_manager.skills)


class SkillSettings:
    """Read-only view of app settings + the one sanctioned mutation (audio devices)."""

    __slots__ = ("_wingman",)

    def __init__(self, wingman: "Wingman") -> None:
        object.__setattr__(self, "_wingman", wingman)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return _wrap(getattr(object.__getattribute__(self, "_wingman").settings, name))

    def __setattr__(self, name: str, value: Any) -> None:
        raise FacadeError(
            f"Settings are read-only for skills — cannot set '{name}'. "
            f"Use ctx.audio.set_output_device(...) to change devices."
        )

    @property
    def output_device(self):
        audio = object.__getattribute__(self, "_wingman").settings.audio
        return audio.output if audio else None

    @property
    def input_device(self):
        audio = object.__getattribute__(self, "_wingman").settings.audio
        return audio.input if audio else None
