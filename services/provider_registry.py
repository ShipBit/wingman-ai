"""Provider registry for managing providers by capability.

This registry centralizes provider management, storing providers by their
capabilities (STT, TTS, LLM) and providing convenient access methods.
"""

from typing import Optional
from api.interface import WingmanConfig, SettingsConfig
from providers.provider_base import BaseProvider
from services.provider_factory import ProviderFactory
from services.printr import Printr
from services.secret_keeper import SecretKeeper

printr = Printr()


class ProviderRegistry:
    """Registry for managing providers by capability.

    This registry uses ProviderFactory to instantiate providers based on
    the wingman's configuration, then stores them organized by capability
    for efficient access during runtime.

    Key features:
    - Async initialization (provider creation involves secret retrieval)
    - Sync getters (no async overhead during usage)
    - Capability-based organization (STT, TTS, LLM)
    - Handles missing providers gracefully
    """

    def __init__(
        self,
        config: WingmanConfig,
        secret_keeper: SecretKeeper,
        wingman_name: str,
        settings: SettingsConfig,
        app_root_path: str = None,
        app_is_bundled: bool = False,
    ):
        """Initialize the registry (does not create providers yet).

        Args:
            config: Wingman configuration
            secret_keeper: SecretKeeper for retrieving API keys
            wingman_name: Name of the wingman (for logging)
            settings: Global settings (includes WingmanProSettings)
            app_root_path: Root path of the application (for FasterWhisper models)
            app_is_bundled: Whether the app is bundled (PyInstaller)
        """
        self.config = config
        self.secret_keeper = secret_keeper
        self.wingman_name = wingman_name
        self.settings = settings

        # Provider storage by capability
        self._stt_provider: Optional[BaseProvider] = None
        self._tts_provider: Optional[BaseProvider] = None
        self._llm_provider: Optional[BaseProvider] = None
        self._image_provider: Optional[BaseProvider] = None

        # Factory for creating providers
        self._factory = ProviderFactory(
            config=config,
            secret_keeper=secret_keeper,
            wingman_name=wingman_name,
            settings=settings,
            app_root_path=app_root_path,
            app_is_bundled=app_is_bundled,
        )

    async def initialize_from_config(self):
        """Initialize providers based on wingman configuration.

        This method:
        1. Reads provider selections from config.features
        2. Uses ProviderFactory to create provider instances
        3. Stores providers by capability
        4. Logs any initialization failures

        This is async because provider creation involves secret retrieval.
        """
        # Initialize STT provider
        if hasattr(self.config.features, "stt_provider"):
            stt_enum = self.config.features.stt_provider
            self._stt_provider = await self._factory.create_stt_provider(stt_enum)
            if self._stt_provider:
                printr.print(
                    f"STT provider '{stt_enum.value}' initialized",
                    server_only=True,
                )

        # Initialize TTS provider
        if hasattr(self.config.features, "tts_provider"):
            tts_enum = self.config.features.tts_provider
            self._tts_provider = await self._factory.create_tts_provider(tts_enum)
            if self._tts_provider:
                printr.print(
                    f"TTS provider '{tts_enum.value}' initialized",
                    server_only=True,
                )

        # Initialize conversation (LLM) provider
        if hasattr(self.config.features, "conversation_provider"):
            llm_enum = self.config.features.conversation_provider
            self._llm_provider = await self._factory.create_conversation_provider(
                llm_enum
            )
            if self._llm_provider:
                printr.print(
                    f"LLM provider '{llm_enum.value}' initialized",
                    server_only=True,
                )

        # Initialize image generation provider
        if hasattr(self.config.features, "image_generation_provider"):
            img_enum = self.config.features.image_generation_provider
            self._image_provider = await self._factory.create_image_provider(img_enum)
            if self._image_provider:
                printr.print(
                    f"Image generation provider '{img_enum.value}' initialized",
                    server_only=True,
                )

    # Sync getters (no async overhead during runtime)

    def get_stt_provider(self) -> Optional[BaseProvider]:
        """Get the configured STT provider.

        Returns:
            STT provider instance or None if not configured
        """
        return self._stt_provider

    def get_tts_provider(self) -> Optional[BaseProvider]:
        """Get the configured TTS provider.

        Returns:
            TTS provider instance or None if not configured
        """
        return self._tts_provider

    def get_llm_provider(self) -> Optional[BaseProvider]:
        """Get the configured LLM provider.

        Returns:
            LLM provider instance or None if not configured
        """
        return self._llm_provider

    def get_image_provider(self) -> Optional[BaseProvider]:
        """Get the configured image generation provider.

        Returns:
            Image generation provider instance or None if not configured
        """
        return self._image_provider

    # Availability checks

    def has_stt(self) -> bool:
        """Check if an STT provider is available.

        Returns:
            True if STT provider is configured and initialized
        """
        return self._stt_provider is not None

    def has_tts(self) -> bool:
        """Check if a TTS provider is available.

        Returns:
            True if TTS provider is configured and initialized
        """
        return self._tts_provider is not None

    def has_llm(self) -> bool:
        """Check if an LLM provider is available.

        Returns:
            True if LLM provider is configured and initialized
        """
        return self._llm_provider is not None

    def has_image_gen(self) -> bool:
        """Check if an image generation provider is available.

        Returns:
            True if image generation provider is configured and initialized
        """
        return self._image_provider is not None

    # Utility methods

    def get_provider_summary(self) -> dict:
        """Get a summary of configured providers.

        Returns:
            Dict with provider names by capability
        """
        return {
            "stt": (
                self._stt_provider.__class__.__name__ if self._stt_provider else None
            ),
            "tts": (
                self._tts_provider.__class__.__name__ if self._tts_provider else None
            ),
            "llm": (
                self._llm_provider.__class__.__name__ if self._llm_provider else None
            ),
            "image_gen": (
                self._image_provider.__class__.__name__
                if self._image_provider
                else None
            ),
        }

    def clear(self):
        """Clear all providers (for cleanup/reinitialization)."""
        self._stt_provider = None
        self._tts_provider = None
        self._llm_provider = None
        self._image_provider = None
