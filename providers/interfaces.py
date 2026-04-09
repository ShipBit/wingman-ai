"""Unified provider interfaces for STT, TTS, and LLM providers.

ABCs define required contracts — providers that don't implement them crash at instantiation.
Protocols define optional capabilities — check with isinstance() before calling.
Registration decorators map config enum values to provider classes for ProviderFactory lookup.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from api.enums import ConversationProvider, SttProvider, TtsProvider

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletion

    from api.interface import SoundConfig, WingmanInitializationError
    from services.audio_player import AudioPlayer


# ---------------------------------------------------------------------------
# Unified return types
# ---------------------------------------------------------------------------

@dataclass
class Transcript:
    """Unified STT result. Every provider wraps its native result into this."""

    text: str
    language: str | None = None
    confidence: float | None = None


# ---------------------------------------------------------------------------
# Core ABCs (required contracts)
# ---------------------------------------------------------------------------

class SttInterface(ABC):
    """Speech-to-text provider interface."""

    @abstractmethod
    async def transcribe(self, filename: str) -> Transcript | None:
        """Transcribe an audio file to text."""
        ...


class TtsInterface(ABC):
    """Text-to-speech provider interface."""

    @abstractmethod
    async def play_audio(
        self,
        text: str,
        sound_config: "SoundConfig",
        audio_player: "AudioPlayer",
        wingman_name: str,
    ) -> None:
        """Synthesize speech and play it."""
        ...


class LlmInterface(ABC):
    """Large language model provider interface."""

    @abstractmethod
    async def ask(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> "ChatCompletion | None":
        """Send messages to the LLM and get a completion."""
        ...


# ---------------------------------------------------------------------------
# Optional Protocols (capability checks)
# ---------------------------------------------------------------------------

@runtime_checkable
class HasAvailableVoices(Protocol):
    """Provider can enumerate available voices."""

    async def get_available_voices(self, **kwargs) -> list: ...


@runtime_checkable
class HasAvailableModels(Protocol):
    """Provider can enumerate available models."""

    async def get_available_models(self) -> list: ...


@runtime_checkable
class HasLifecycle(Protocol):
    """Provider has load/unload lifecycle for local models."""

    async def load(self) -> None: ...
    async def unload(self) -> None: ...


@runtime_checkable
class Validatable(Protocol):
    """Provider can validate its configuration."""

    async def validate(self, errors: "list[WingmanInitializationError]") -> None: ...


@runtime_checkable
class HasMinimalReasoning(Protocol):
    """LLM provider supports reasoning effort tuning (e.g., O-series, Gemini)."""

    def get_minimal_reasoning_by_model(self, model_name: str) -> dict: ...


# ---------------------------------------------------------------------------
# Registration decorators + registries
# ---------------------------------------------------------------------------

_STT_REGISTRY: dict[SttProvider, type[SttInterface]] = {}
_TTS_REGISTRY: dict[TtsProvider, type[TtsInterface]] = {}
_LLM_REGISTRY: dict[ConversationProvider, type[LlmInterface]] = {}


def stt_provider(*provider_enums: SttProvider):
    """Register a class as the STT provider for given enum value(s)."""

    def decorator(cls):
        for enum_val in provider_enums:
            _STT_REGISTRY[enum_val] = cls
        return cls

    return decorator


def tts_provider(*provider_enums: TtsProvider):
    """Register a class as the TTS provider for given enum value(s)."""

    def decorator(cls):
        for enum_val in provider_enums:
            _TTS_REGISTRY[enum_val] = cls
        return cls

    return decorator


def llm_provider(*provider_enums: ConversationProvider):
    """Register a class as the LLM provider for given enum value(s)."""

    def decorator(cls):
        for enum_val in provider_enums:
            _LLM_REGISTRY[enum_val] = cls
        return cls

    return decorator


def get_stt_class(provider: SttProvider) -> type[SttInterface] | None:
    """Look up the registered STT provider class for an enum value."""
    return _STT_REGISTRY.get(provider)


def get_tts_class(provider: TtsProvider) -> type[TtsInterface] | None:
    """Look up the registered TTS provider class for an enum value."""
    return _TTS_REGISTRY.get(provider)


def get_llm_class(provider: ConversationProvider) -> type[LlmInterface] | None:
    """Look up the registered LLM provider class for an enum value."""
    return _LLM_REGISTRY.get(provider)
