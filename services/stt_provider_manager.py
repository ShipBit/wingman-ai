import asyncio
import os
from typing import Awaitable, Callable, Optional

from api.enums import LogType, SttProvider
from api.interface import ParakeetSttConfig
from providers.parakeet import Parakeet
from services.model_downloader import ModelDownloader
from services.printr import Printr
from services.system_manager import SystemManager


# HuggingFace repo IDs for Parakeet models
PARAKEET_REPO_MAP = {
    "v2": "istupakov/parakeet-tdt-0.6b-v2-onnx",
    "v3": "istupakov/parakeet-tdt-0.6b-v3-onnx",
}

class SttProviderManager:
    """Manages STT provider lifecycle: CUDA detection, model download, load/unload."""

    def __init__(
        self,
        settings_service,  # forward ref to avoid circular import
        system_manager: SystemManager,
        model_downloader: ModelDownloader,
        parakeet: Parakeet,
        app_root_path: str,
    ):
        self.settings_service = settings_service
        self.system_manager = system_manager
        self.model_downloader = model_downloader
        self.parakeet = parakeet
        self.app_root_path = app_root_path
        self.printr = Printr()
        self.active_provider: SttProvider | None = None
        # Serializes initialize/switch_provider: a settings-triggered switch
        # must not race the startup init (or another switch) into downloading
        # and loading the same model twice concurrently.
        self._init_lock = asyncio.Lock()

    async def initialize(
        self,
        on_status: Optional[Callable[[str, float | None], Awaitable[None]]] = None,
    ):
        """Full STT startup sequence.

        Args:
            on_status: Async callback (message, progress_or_none) for UI updates.
        """
        async with self._init_lock:
            stt_settings = self.settings_service.settings.stt
            provider = stt_settings.provider

            # Check if this is a local provider that needs download + init
            if provider == SttProvider.PARAKEET and stt_settings.parakeet.run_locally:
                await self._initialize_parakeet(on_status)
            else:
                # Remote/cloud provider — nothing to download or init
                self.printr.print(
                    f"STT provider '{provider.value}' is remote/cloud — skipping local init.",
                    server_only=True,
                    color=LogType.INFO,
                )

            self.active_provider = provider

    async def _initialize_parakeet(
        self,
        on_status: Optional[Callable[[str, float | None], Awaitable[None]]] = None,
    ):
        """Download and initialize Parakeet."""
        pk_settings = self.settings_service.settings.stt.parakeet

        # Download model
        variant = pk_settings.model_variant
        repo_id = PARAKEET_REPO_MAP.get(variant)
        if not repo_id:
            self.printr.toast_error(
                f"Unknown Parakeet model variant: {variant}. Using v3."
            )
            repo_id = PARAKEET_REPO_MAP["v3"]

        model_path = None
        try:
            if on_status:
                await on_status("Downloading STT model (Parakeet)...", None)

            model_path = await self.model_downloader.download_huggingface(
                repo_id=repo_id,
                category="parakeet",
            )
        except Exception as e:
            self.printr.toast_error(
                f"Could not download the Parakeet STT model. "
                f"Please check your internet connection and restart Wingman AI. "
                f"If the problem persists, report it at github.com/ShipBit/wingman-ai/issues\n"
                f"Error: {e}"
            )
            return

        # Load model
        if on_status:
            await on_status("Initializing speech-to-text...", None)

        # Add brief delay for CUDA to allow GPU memory cleanup
        if pk_settings.execution_provider == "cuda":
            await asyncio.sleep(0.5)

        await asyncio.get_event_loop().run_in_executor(
            None, self.parakeet.load, model_path
        )

        # Health check
        if on_status:
            await on_status("Verifying speech-to-text...", None)

        await self._health_check_parakeet()

    async def switch_provider(
        self,
        new_provider: SttProvider,
        on_status: Optional[Callable[[str, float | None], Awaitable[None]]] = None,
    ):
        """Switch active STT provider. Unloads old, downloads + loads new.

        ``on_status`` is forwarded to the provider-specific init so settings-
        triggered switches can surface download progress via the same
        LOADING_CONFIG indicator used at startup.
        """
        async with self._init_lock:
            old_provider = self.active_provider

            # Unload current provider
            if old_provider == SttProvider.PARAKEET:
                self.parakeet.unload()

            # Initialize new provider
            stt_settings = self.settings_service.settings.stt
            if new_provider == SttProvider.PARAKEET and stt_settings.parakeet.run_locally:
                await self._initialize_parakeet(on_status)

            self.active_provider = new_provider

    async def _health_check_parakeet(self):
        """Run a quick transcription test on the loaded Parakeet model."""
        wav_path = os.path.join(self.app_root_path, "audio_samples", "beep.wav")
        config = ParakeetSttConfig(temperature=0.0)
        try:
            result = self.parakeet.transcribe(config=config, filename=wav_path)
            if result and result.text is not None:
                self.printr.print(
                    "Parakeet health check passed.",
                    server_only=True,
                    color=LogType.POSITIVE,
                )
            else:
                self.printr.toast_warning(
                    "STT loaded but verification failed — transcription may not work correctly."
                )
        except Exception as e:
            self.printr.toast_warning(
                f"STT verification failed: {e}. Transcription may not work correctly."
            )

    def unload_all(self):
        """Unload the local model. Called on shutdown."""
        self.parakeet.unload()
        self.active_provider = None
