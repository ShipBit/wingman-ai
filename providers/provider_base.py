"""Provider capability system and base classes.

This module defines the foundation for the modular provider architecture:
- ProviderCapability enum for declaring provider abilities
- @capabilities decorator for marking provider classes
- Protocol classes defining provider interfaces
- BaseProvider abstract class with common functionality
"""

from abc import ABC
from enum import Enum
from typing import Protocol, runtime_checkable, Any
from openai.types.chat import ChatCompletion


class ProviderCapability(Enum):
    """Capabilities that providers can offer."""

    STT = "speech_to_text"
    TTS = "text_to_speech"
    LLM = "language_model"
    IMAGE_GEN = "image_generation"


def capabilities(*caps: ProviderCapability):
    """Decorator to mark provider classes with their capabilities.

    Usage:
        @capabilities(ProviderCapability.STT, ProviderCapability.TTS)
        class MyProvider(BaseProvider):
            pass

    Args:
        *caps: Variable number of ProviderCapability values

    Returns:
        Decorated class with _capabilities attribute
    """

    def decorator(cls):
        cls._capabilities = set(caps)
        return cls

    return decorator


@runtime_checkable
class SttProvider(Protocol):
    """Protocol for Speech-to-Text providers.

    Providers implementing this protocol can transcribe audio to text.
    All implementations must be async and support **kwargs for flexibility.
    """

    async def transcribe(self, audio_input_wav: str, **kwargs) -> str:
        """Transcribe audio file to text.

        Args:
            audio_input_wav: Path to WAV audio file
            **kwargs: Additional provider-specific parameters
                - prompt: Optional transcription hint/context
                - language: Optional language code
                - model: Optional model override

        Returns:
            Transcribed text string

        Raises:
            Exception: On transcription failure
        """
        ...


@runtime_checkable
class TtsProvider(Protocol):
    """Protocol for Text-to-Speech providers.

    Providers implementing this protocol can synthesize speech from text.
    All implementations must be async and support **kwargs for flexibility.
    """

    async def synthesize(
        self, text: str, audio_player, sound_config, wingman_name: str, **kwargs
    ) -> None:
        """Synthesize speech from text.

        Args:
            text: Text to convert to speech
            audio_player: AudioPlayer instance for playback
            sound_config: Sound configuration with voice settings
            wingman_name: Name of wingman (for audio file naming)
            **kwargs: Additional provider-specific parameters
                - voice: Optional voice override
                - model: Optional model override
                - speed: Optional speed multiplier
                - effects: Optional audio effects

        Returns:
            None - Audio is played directly via audio_player

        Raises:
            Exception: On synthesis failure
        """
        ...


@runtime_checkable
class ImageGenProvider(Protocol):
    """Protocol for Image Generation providers.

    Providers implementing this protocol can generate images from text descriptions.
    All implementations must be async and support **kwargs for flexibility.
    """

    async def generate_image(self, prompt: str, **kwargs) -> str:
        """Generate an image from a text description.

        Args:
            prompt: Text description of the image to generate
            **kwargs: Additional provider-specific parameters
                - size: Optional image size (e.g., "1024x1024")
                - quality: Optional quality setting
                - style: Optional style parameter
                - model: Optional model override

        Returns:
            URL or local path to the generated image

        Raises:
            Exception: On generation failure
        """
        ...


@runtime_checkable
class LlmProvider(Protocol):
    """Protocol for Language Model providers.

    Providers implementing this protocol can generate text completions.
    All implementations must be async and support **kwargs for flexibility.
    """

    async def complete(
        self, messages: list[dict], tools: list[dict] = None, **kwargs
    ) -> ChatCompletion | None:
        """Generate completion from messages.

        Args:
            messages: List of message dicts with 'role' and 'content'
            tools: Optional list of tool definitions for function calling
            **kwargs: Additional provider-specific parameters
                - temperature: Optional temperature override
                - max_tokens: Optional token limit
                - model: Optional model override
                - stream: Optional streaming flag
                - response_format: Optional response format (e.g., JSON)

        Returns:
            ChatCompletion object from OpenAI (or compatible) API, or None on error.
            All providers return OpenAI-compatible ChatCompletion objects.

        Raises:
            Exception: On completion failure
        """
        ...


class BaseProvider(ABC):
    """Abstract base class for all providers.

    Provides common functionality for capability checking and configuration.
    All provider implementations should inherit from this class and use the
    @capabilities decorator to declare their abilities.

    Attributes:
        config: Provider-specific configuration object (typed per provider)
        api_key: Optional API key for authentication
    """

    def __init__(self, config: Any, api_key: str = None):
        """Initialize base provider.

        Args:
            config: Provider-specific configuration object
            api_key: Optional API key for authentication
        """
        self.config = config
        self.api_key = api_key

    @classmethod
    def get_capabilities(cls) -> set[ProviderCapability]:
        """Get the capabilities this provider supports.

        Returns:
            Set of ProviderCapability values declared via @capabilities decorator
            Returns empty set if no capabilities declared
        """
        return getattr(cls, "_capabilities", set())

    @classmethod
    def supports(cls, capability: ProviderCapability) -> bool:
        """Check if this provider supports a specific capability.

        Args:
            capability: ProviderCapability to check

        Returns:
            True if provider supports the capability, False otherwise
        """
        return capability in cls.get_capabilities()

    def __repr__(self) -> str:
        """String representation showing provider class and capabilities."""
        caps = ", ".join(c.value for c in self.get_capabilities())
        return f"<{self.__class__.__name__} capabilities=[{caps}]>"
