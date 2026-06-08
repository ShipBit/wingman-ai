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
        prompt: str,
        *,
        system: str | None = None,
        data: str | None = None,
        image: str | None = None,
        auto_shorten: bool = False,
    ) -> str:
        """Single-turn generation on the main model. Returns the response text.

        ``prompt`` is the instruction; ``data`` is an optional larger payload appended
        to it; ``image`` is an optional data-URL for vision. When conversation
        condensation is enabled the combined input is capped (see class docstring):
        over the cap raises :class:`FacadeError`, or truncates if ``auto_shorten``.
        """
        from services.token_utils import count_tokens, truncate_to_tokens

        features = self._wingman.config.features
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


class SkillRegistryView:
    """Sanctioned read + invoke over the wingman's tools/commands.

    Lets a skill discover which tool functions exist and invoke one (or a command)
    by name — without reaching into build_tools()/the renamed internal dispatcher.
    The invoke surface is deliberately scoped to enumerable tools/commands, not
    arbitrary attribute calls.
    """

    def __init__(self, wingman: "Wingman") -> None:
        self._wingman = wingman

    def tool_names(self) -> set[str]:
        """Names of all currently-available tool functions."""
        names = set()
        for tool in self._wingman.build_tools():
            name = tool.get("function", {}).get("name")
            if name:
                names.add(name)
        return names

    def has_tool(self, name: str) -> bool:
        """True if a tool function with this name is currently available."""
        return name in self.tool_names()

    async def invoke(self, function_name: str, arguments: dict | None = None):
        """Invoke a tool/command by name. Returns
        ``(function_response, instant_response, used_skill, tool_label)``."""
        return await self._wingman.execute_command_by_function_call(
            function_name, arguments or {}
        )


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

    async def play(self, audio_config: Any, volume_modifier: float = 1.0) -> None:
        """Start playback of a skill-owned audio file (``AudioFile``/``AudioFileConfig``)."""
        await self._wingman.audio_library.start_playback(audio_config, volume_modifier)

    async def stop(self, audio_config: Any, fade_out_time: float = 0.5) -> None:
        """Stop playback of a skill-owned audio file (optionally fading out)."""
        await self._wingman.audio_library.stop_playback(audio_config, fade_out_time)

    def on_playback_started(self, callback: Any) -> None:
        """Subscribe to playback-started events. Callback receives the wingman name."""
        self._wingman.audio_player.playback_events.subscribe("started", callback)

    def on_playback_finished(self, callback: Any) -> None:
        """Subscribe to playback-finished events. Callback receives the wingman name."""
        self._wingman.audio_player.playback_events.subscribe("finished", callback)

    def off_playback_started(self, callback: Any) -> None:
        """Unsubscribe a previously-registered playback-started callback."""
        self._wingman.audio_player.playback_events.unsubscribe("started", callback)

    def off_playback_finished(self, callback: Any) -> None:
        """Unsubscribe a previously-registered playback-finished callback."""
        self._wingman.audio_player.playback_events.unsubscribe("finished", callback)

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

    async def set_output_device(self, device_id: int) -> bool:
        """Switch the system audio OUTPUT device. Returns False if unavailable."""
        return await self._set_devices(output_device=device_id)

    async def set_input_device(self, device_id: int) -> bool:
        """Switch the system audio INPUT device. Returns False if unavailable."""
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
