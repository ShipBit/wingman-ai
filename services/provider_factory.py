"""Provider factory for creating provider instances.

This factory handles instantiation of all provider types with proper
configuration and secret retrieval. It maps provider enums to their
corresponding classes and handles special cases like Azure multi-service
and OpenAI-compatible providers.
"""

from typing import Optional
from api.enums import (
    SttProvider,
    TtsProvider,
    ConversationProvider,
    ImageGenerationProvider,
)
from api.interface import WingmanConfig
from providers.provider_base import BaseProvider
from providers.open_ai import OpenAi, OpenAiAzure, OpenAiCompatibleTts, OpenRouter
from providers.google import GoogleGenAI
from providers.elevenlabs import ElevenLabs
from providers.edge import Edge
from providers.hume import Hume
from providers.inworld import Inworld
from providers.wingman_pro import WingmanPro
from providers.whispercpp import Whispercpp
from providers.faster_whisper import FasterWhisper
from services.printr import Printr
from services.secret_keeper import SecretKeeper

printr = Printr()


class ProviderFactory:
    """Factory for creating provider instances with proper configuration.

    This factory centralizes all provider instantiation logic, handling:
    - Secret retrieval from SecretKeeper
    - Configuration mapping from WingmanConfig
    - Special cases (Azure, OpenAI-compatible, etc.)
    - Singleton providers (shared across all wingmen)
    - Error handling and logging
    """

    # Azure service types for multi-key management
    AZURE_SERVICES = ["whisper", "speech", "tts", "conversation"]

    # Singleton provider instances (shared across all wingmen)
    # Key: provider class name (e.g., "FasterWhisper", "Whispercpp")
    # Value: provider instance
    _singleton_instances: dict[str, BaseProvider] = {}

    # Mapping of STT provider enums to (class, secret_key, config_attr)
    STT_PROVIDERS = {
        SttProvider.OPENAI: (OpenAi, "openai", "openai"),
        SttProvider.AZURE: (OpenAiAzure, "azure_whisper", "azure"),  # Uses Whisper
        SttProvider.AZURE_SPEECH: (OpenAiAzure, "azure_speech", "azure"),  # Uses Speech
        SttProvider.WINGMAN_PRO: (WingmanPro, "wingman_pro", "wingman_pro"),
        SttProvider.WHISPERCPP: (
            Whispercpp,
            None,
            "whispercpp",
        ),  # No API key, uses HTTP
        SttProvider.FASTER_WHISPER: (
            FasterWhisper,
            None,
            "fasterwhisper",
        ),  # No API key, local model
    }

    # Mapping of TTS provider enums to (class, secret_key, config_attr)
    TTS_PROVIDERS = {
        TtsProvider.OPENAI: (OpenAi, "openai", "openai"),
        TtsProvider.AZURE: (OpenAiAzure, "azure_tts", "azure"),
        TtsProvider.OPENAI_COMPATIBLE: (
            OpenAiCompatibleTts,
            "openai_compatible_tts",
            "openai_compatible_tts",
        ),
        TtsProvider.ELEVENLABS: (ElevenLabs, "elevenlabs", "elevenlabs"),
        TtsProvider.EDGE_TTS: (Edge, None, "edge_tts"),  # No API key required
        TtsProvider.HUME: (Hume, "hume", "hume"),
        TtsProvider.INWORLD: (Inworld, "inworld", "inworld"),
        TtsProvider.WINGMAN_PRO: (WingmanPro, "wingman_pro", "wingman_pro"),
        # TtsProvider.XVASYNTH: Not yet migrated to BaseProvider
    }

    # Mapping of conversation provider enums to (class, secret_key, config_attr)
    CONVERSATION_PROVIDERS = {
        ConversationProvider.OPENAI: (OpenAi, "openai", "openai"),
        ConversationProvider.AZURE: (OpenAiAzure, "azure_conversation", "azure"),
        ConversationProvider.GOOGLE: (GoogleGenAI, "google", "google"),
        ConversationProvider.WINGMAN_PRO: (WingmanPro, "wingman_pro", "wingman_pro"),
        # OpenAI-compatible providers (use OpenAi class with custom base_url)
        ConversationProvider.MISTRAL: (OpenAi, "mistral", "mistral"),
        ConversationProvider.GROQ: (OpenAi, "groq", "groq"),
        ConversationProvider.CEREBRAS: (OpenAi, "cerebras", "cerebras"),
        ConversationProvider.OPENROUTER: (OpenRouter, "openrouter", "openrouter"),
        ConversationProvider.LOCAL_LLM: (OpenAi, "local_llm", "local_llm"),
        ConversationProvider.PERPLEXITY: (OpenAi, "perplexity", "perplexity"),
        ConversationProvider.XAI: (OpenAi, "xai", "xai"),
    }

    # Mapping of image generation provider enums to (class, secret_key, config_attr)
    IMAGE_GEN_PROVIDERS = {
        ImageGenerationProvider.WINGMAN_PRO: (WingmanPro, "wingman_pro", "wingman_pro"),
        # Future: ImageGenerationProvider.OPENAI: (OpenAi, "openai", "openai"),
    }

    def __init__(
        self,
        config: WingmanConfig,
        secret_keeper: SecretKeeper,
        wingman_name: str,
        settings,
        app_root_path: str = None,
        app_is_bundled: bool = False,
    ):
        """Initialize the factory.

        Args:
            config: Wingman configuration
            secret_keeper: SecretKeeper for retrieving API keys
            wingman_name: Name of the wingman (for secret retrieval)
            settings: Global settings (includes WingmanProSettings)
            app_root_path: Root path of the application (for FasterWhisper models)
            app_is_bundled: Whether the app is bundled (PyInstaller)
        """
        self.config = config
        self.secret_keeper = secret_keeper
        self.wingman_name = wingman_name
        self.settings = settings
        self.app_root_path = app_root_path
        self.app_is_bundled = app_is_bundled

        # Cache for Azure provider (shared across STT/TTS/LLM)
        self._azure_provider: Optional[BaseProvider] = None
        self._azure_keys_retrieved = False

    @classmethod
    def register_singleton(cls, provider_name: str, provider_instance: BaseProvider):
        """Register a singleton provider instance.

        Singleton providers are shared across all wingmen to save resources.
        Examples: FasterWhisper (model caching), Whispercpp (HTTP client).

        Args:
            provider_name: Unique name for the provider (e.g., "FasterWhisper")
            provider_instance: The provider instance to register
        """
        cls._singleton_instances[provider_name] = provider_instance
        printr.print(
            f"Singleton provider '{provider_name}' registered",
            server_only=True,
        )

    @classmethod
    def get_singleton(cls, provider_name: str) -> Optional[BaseProvider]:
        """Get a singleton provider instance if it exists.

        Args:
            provider_name: Name of the singleton provider

        Returns:
            Provider instance or None if not registered
        """
        return cls._singleton_instances.get(provider_name)

    async def create_stt_provider(
        self, provider_enum: SttProvider
    ) -> Optional[BaseProvider]:
        """Create an STT provider instance.

        Args:
            provider_enum: STT provider enum value

        Returns:
            Provider instance or None on failure
        """
        if provider_enum not in self.STT_PROVIDERS:
            printr.print(
                f"STT provider '{provider_enum.value}' not yet migrated to BaseProvider",
                server_only=True,
            )
            return None

        provider_class, secret_key, config_attr = self.STT_PROVIDERS[provider_enum]

        # Special handling for Azure (shared instance with all keys)
        if provider_enum in (SttProvider.AZURE, SttProvider.AZURE_SPEECH):
            return await self._get_or_create_azure_provider()

        # Special handling for WingmanPro (requires wingman_name)
        if provider_enum == SttProvider.WINGMAN_PRO:
            return await self._create_wingman_pro_provider(config_attr, secret_key)

        # Special handling for FasterWhisper (requires app paths and wingman_name)
        if provider_enum == SttProvider.FASTER_WHISPER:
            return self._create_faster_whisper_provider(config_attr)

        # Special handling for Whispercpp (needs settings from voice_activation)
        if provider_enum == SttProvider.WHISPERCPP:
            return self._create_whispercpp_provider(config_attr)

        # Retrieve API key (if required)
        api_key = None
        if secret_key:
            api_key = await self._retrieve_secret(secret_key)
            if not api_key:
                return None

        # Get provider config
        provider_config = getattr(self.config, config_attr, None)
        if not provider_config:
            printr.print(
                f"Missing config for STT provider '{provider_enum.value}'",
                server_only=True,
            )
            return None

        # Create provider
        try:
            # Handle OpenAI-compatible providers with custom base_url
            if hasattr(provider_config, "endpoint"):
                provider = provider_class(
                    config=provider_config,
                    api_key=api_key,
                    base_url=provider_config.endpoint,
                )
            else:
                provider = provider_class(
                    config=provider_config,
                    api_key=api_key,
                    organization=getattr(provider_config, "organization", None),
                    base_url=getattr(provider_config, "base_url", None),
                )

            return provider
        except Exception as e:
            printr.print(
                f"Failed to create STT provider '{provider_enum.value}': {str(e)}",
                server_only=True,
            )
            return None

    def _create_faster_whisper_provider(
        self, config_attr: str
    ) -> Optional[BaseProvider]:
        """Create FasterWhisper provider as singleton.

        Args:
            config_attr: Config attribute name (e.g., "fasterwhisper")

        Returns:
            FasterWhisper provider instance or None on failure
        """
        # Check if singleton already exists
        existing = self.get_singleton("FasterWhisper")
        if existing:
            return existing

        # Get provider config from settings (FasterWhisperSettings with model_size, device, etc.)
        # NOT from wingman config (which has FasterWhisperSttConfig with transcription params)
        provider_config = getattr(self.settings.voice_activation, config_attr, None)
        if not provider_config:
            printr.print(
                "Missing FasterWhisper settings in voice_activation",
                server_only=True,
            )
            return None

        # Create FasterWhisper provider
        try:
            provider = FasterWhisper(
                config=provider_config,
                api_key=None,
                app_root_path=self.app_root_path,
                app_is_bundled=self.app_is_bundled,
                wingman_name=self.wingman_name,
            )
            # Register as singleton
            self.register_singleton("FasterWhisper", provider)
            return provider
        except Exception as e:
            printr.print(
                f"Failed to create FasterWhisper provider: {str(e)}",
                server_only=True,
            )
            return None

    def _create_whispercpp_provider(self, config_attr: str) -> Optional[BaseProvider]:
        """Create Whispercpp provider as singleton.

        Args:
            config_attr: Config attribute name (e.g., "whispercpp")

        Returns:
            Whispercpp provider instance or None on failure
        """
        # Check if singleton already exists
        existing = self.get_singleton("Whispercpp")
        if existing:
            return existing

        # Get provider config from settings (WhispercppSettings with host, port, enable)
        # NOT from wingman config (which has WhispercppSttConfig with temperature)
        provider_config = getattr(self.settings.voice_activation, config_attr, None)
        if not provider_config:
            printr.print(
                "Missing Whispercpp settings in voice_activation",
                server_only=True,
            )
            return None

        # Create Whispercpp provider
        try:
            provider = Whispercpp(
                config=provider_config,
                api_key=None,
            )
            # Register as singleton
            self.register_singleton("Whispercpp", provider)
            return provider
        except Exception as e:
            printr.print(
                f"Failed to create Whispercpp provider: {str(e)}",
                server_only=True,
            )
            return None

    async def create_tts_provider(
        self, provider_enum: TtsProvider
    ) -> Optional[BaseProvider]:
        """Create a TTS provider instance.

        Args:
            provider_enum: TTS provider enum value

        Returns:
            Provider instance or None on failure
        """
        if provider_enum not in self.TTS_PROVIDERS:
            printr.print(
                f"TTS provider '{provider_enum.value}' not yet migrated to BaseProvider",
                server_only=True,
            )
            return None

        provider_class, secret_key, config_attr = self.TTS_PROVIDERS[provider_enum]

        # Special handling for Azure (shared instance)
        if provider_enum == TtsProvider.AZURE:
            return await self._get_or_create_azure_provider()

        # Special handling for WingmanPro (requires wingman_name)
        if provider_enum == TtsProvider.WINGMAN_PRO:
            return await self._create_wingman_pro_provider(config_attr, secret_key)

        # Special handling for Edge TTS (no API key required)
        if provider_enum == TtsProvider.EDGE_TTS:
            provider_config = getattr(self.config, config_attr, None)
            if not provider_config:
                printr.print(
                    f"Missing config for TTS provider '{provider_enum.value}'",
                    server_only=True,
                )
                return None
            try:
                return provider_class(config=provider_config)
            except Exception as e:
                printr.print(
                    f"Failed to create TTS provider '{provider_enum.value}': {str(e)}",
                    server_only=True,
                )
                return None

        # Retrieve API key (None means no key required)
        if secret_key is not None:
            api_key = await self._retrieve_secret(secret_key)
            if not api_key:
                return None
        else:
            api_key = None

        # Get provider config
        provider_config = getattr(self.config, config_attr, None)
        if not provider_config:
            printr.print(
                f"Missing config for TTS provider '{provider_enum.value}'",
                server_only=True,
            )
            return None

        # Create provider
        try:
            if provider_class == OpenAiCompatibleTts:
                # OpenAI Compatible TTS has different signature
                provider = provider_class(
                    api_key=api_key,
                    base_url=provider_config.base_url,
                )
            elif provider_class in (ElevenLabs, Hume, Inworld):
                # These providers need wingman_name
                provider = provider_class(
                    config=provider_config,
                    api_key=api_key,
                    wingman_name=self.wingman_name,
                )
            elif hasattr(provider_config, "endpoint"):
                # OpenAI-compatible with custom endpoint
                provider = provider_class(
                    config=provider_config,
                    api_key=api_key,
                    base_url=provider_config.endpoint,
                )
            else:
                # Standard OpenAI
                provider = provider_class(
                    config=provider_config,
                    api_key=api_key,
                    organization=getattr(provider_config, "organization", None),
                    base_url=getattr(provider_config, "base_url", None),
                )
            return provider
        except Exception as e:
            printr.print(
                f"Failed to create TTS provider '{provider_enum.value}': {str(e)}",
                server_only=True,
            )
            return None

    async def create_conversation_provider(
        self, provider_enum: ConversationProvider
    ) -> Optional[BaseProvider]:
        """Create a conversation (LLM) provider instance.

        Args:
            provider_enum: Conversation provider enum value

        Returns:
            Provider instance or None on failure
        """
        if provider_enum not in self.CONVERSATION_PROVIDERS:
            printr.print(
                f"Conversation provider '{provider_enum.value}' not yet migrated to BaseProvider",
                server_only=True,
            )
            return None

        provider_class, secret_key, config_attr = self.CONVERSATION_PROVIDERS[
            provider_enum
        ]

        # Special handling for Azure (shared instance)
        if provider_enum == ConversationProvider.AZURE:
            return await self._get_or_create_azure_provider()

        # Special handling for WingmanPro (requires wingman_name)
        if provider_enum == ConversationProvider.WINGMAN_PRO:
            return await self._create_wingman_pro_provider(config_attr, secret_key)

        # Retrieve API key
        api_key = await self._retrieve_secret(secret_key)
        if not api_key:
            return None

        # Get provider config
        provider_config = getattr(self.config, config_attr, None)
        if not provider_config:
            printr.print(
                f"Missing config for conversation provider '{provider_enum.value}'",
                server_only=True,
            )
            return None

        # Create provider
        try:
            if provider_class == GoogleGenAI:
                # Google has simpler constructor
                provider = provider_class(
                    config=provider_config,
                    api_key=api_key,
                )
            elif hasattr(provider_config, "endpoint") and provider_config.endpoint:
                provider = provider_class(
                    config=provider_config,
                    api_key=api_key,
                    base_url=provider_config.endpoint,
                )
            else:
                # Standard OpenAI
                provider = provider_class(
                    config=provider_config,
                    api_key=api_key,
                    organization=getattr(provider_config, "organization", None),
                    base_url=getattr(provider_config, "base_url", None),
                )
            return provider
        except Exception as e:
            printr.print(
                f"Failed to create conversation provider '{provider_enum.value}': {str(e)}",
                server_only=True,
            )
            return None

    async def create_image_provider(
        self, provider_enum: ImageGenerationProvider
    ) -> Optional[BaseProvider]:
        """Create an image generation provider instance.

        Args:
            provider_enum: Image generation provider enum value

        Returns:
            Provider instance or None on failure
        """
        if provider_enum not in self.IMAGE_GEN_PROVIDERS:
            printr.print(
                f"Image generation provider '{provider_enum.value}' not yet supported",
                server_only=True,
            )
            return None

        provider_class, secret_key, config_attr = self.IMAGE_GEN_PROVIDERS[
            provider_enum
        ]

        # Special handling for WingmanPro (requires wingman_name)
        if provider_enum == ImageGenerationProvider.WINGMAN_PRO:
            return await self._create_wingman_pro_provider(config_attr, secret_key)

        # Future: Handle other image generation providers (OpenAI DALL-E, etc.)
        # Retrieve API key
        api_key = await self._retrieve_secret(secret_key)
        if not api_key:
            return None

        # Get provider config
        provider_config = getattr(self.config, config_attr, None)
        if not provider_config:
            printr.print(
                f"Missing config for image generation provider '{provider_enum.value}'",
                server_only=True,
            )
            return None

        # Create provider
        try:
            provider = provider_class(
                config=provider_config,
                api_key=api_key,
            )
            return provider
        except Exception as e:
            printr.print(
                f"Failed to create image generation provider '{provider_enum.value}': {str(e)}",
                server_only=True,
            )
            return None

    # Private helper methods

    async def _retrieve_secret(self, secret_name: str) -> Optional[str]:
        """Retrieve a secret from SecretKeeper.

        Args:
            secret_name: Name of the secret to retrieve

        Returns:
            Secret value or None if not found
        """
        try:
            api_key = await self.secret_keeper.retrieve(
                requester=self.wingman_name,
                key=secret_name,
                prompt_if_missing=False,  # Factory doesn't prompt - validation phase does
            )
            return api_key
        except Exception as e:
            printr.print(
                f"Error retrieving secret '{secret_name}': {str(e)}",
                server_only=True,
            )
            return None

    async def _get_or_create_azure_provider(self) -> Optional[BaseProvider]:
        """Get or create the shared Azure provider with all service keys.

        Azure uses a single provider instance that stores keys for all services:
        - whisper (STT via Azure OpenAI Whisper)
        - speech (STT via Azure Cognitive Services)
        - tts (TTS via Azure Cognitive Services)
        - conversation (LLM via Azure OpenAI)

        This method caches the provider to avoid recreating it multiple times.

        Returns:
            Azure provider instance or None on failure
        """
        # Return cached instance if available
        if self._azure_provider is not None:
            return self._azure_provider

        # Only retrieve keys once
        if not self._azure_keys_retrieved:
            # Retrieve all four service keys
            whisper_key = await self._retrieve_secret("azure_whisper")
            speech_key = await self._retrieve_secret("azure_speech")
            tts_key = await self._retrieve_secret("azure_tts")
            conversation_key = await self._retrieve_secret("azure_conversation")

            self._azure_keys_retrieved = True

            # Check if we have at least one key
            if not any([whisper_key, speech_key, tts_key, conversation_key]):
                printr.print(
                    "No Azure API keys found for any service",
                    server_only=True,
                )
                return None

            # Check if Azure config exists
            if not hasattr(self.config, "azure") or not self.config.azure:
                printr.print(
                    "Missing Azure configuration",
                    server_only=True,
                )
                return None

            # Create unified Azure provider with all keys
            try:
                self._azure_provider = OpenAiAzure(
                    config=self.config,
                    whisper_api_key=whisper_key,
                    speech_api_key=speech_key,
                    tts_api_key=tts_key,
                    llm_api_key=conversation_key,
                )
            except Exception as e:
                printr.print(
                    f"Failed to create Azure provider: {str(e)}",
                    server_only=True,
                )
                return None

        return self._azure_provider

    async def _create_wingman_pro_provider(
        self, config_attr: str, secret_key: str
    ) -> Optional[BaseProvider]:
        """Create WingmanPro provider with special wingman_name parameter.

        Args:
            config_attr: Config attribute name (e.g., "wingman_pro")
            secret_key: Secret key name for API token

        Returns:
            WingmanPro provider instance or None on failure
        """
        # Retrieve API key
        api_key = await self._retrieve_secret(secret_key)
        if not api_key:
            return None

        # Get provider settings (global WingmanProSettings with base_url and region)
        provider_config = self.settings.wingman_pro
        if not provider_config:
            printr.print(
                f"Missing WingmanPro settings",
                server_only=True,
            )
            return None

        # Create WingmanPro provider
        try:
            provider = WingmanPro(
                wingman_config=self.config,
                provider_settings=provider_config,
                api_key=api_key,
                wingman_name=self.wingman_name,
            )
            return provider
        except Exception as e:
            printr.print(
                f"Failed to create WingmanPro provider: {str(e)}",
                server_only=True,
            )
            return None
