import asyncio
import os
import platform
from typing import Awaitable, Callable, Optional

from api.enums import LogType, VoiceActivationSttProvider
from api.interface import ParakeetSttConfig, FasterWhisperSttConfig
from providers.faster_whisper import FasterWhisper
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
        fasterwhisper: FasterWhisper,
        app_root_path: str,
    ):
        self.settings_service = settings_service
        self.system_manager = system_manager
        self.model_downloader = model_downloader
        self.parakeet = parakeet
        self.fasterwhisper = fasterwhisper
        self.app_root_path = app_root_path
        self.printr = Printr()
        self.active_provider: VoiceActivationSttProvider | None = None

    async def initialize(
        self,
        on_status: Optional[Callable[[str, float | None], Awaitable[None]]] = None,
    ):
        """Full STT startup sequence.

        Args:
            on_status: Async callback (message, progress_or_none) for UI updates.
        """
        va_settings = self.settings_service.settings.voice_activation
        provider = va_settings.stt_provider

        # Check if this is a local provider that needs download + init
        if provider == VoiceActivationSttProvider.PARAKEET and va_settings.parakeet.run_locally:
            await self._initialize_parakeet(on_status)
        elif provider == VoiceActivationSttProvider.FASTER_WHISPER:
            await self._initialize_fasterwhisper(on_status)
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
        pk_settings = self.settings_service.settings.voice_activation.parakeet

        # Auto-detect CUDA and update execution_provider in settings
        self._auto_detect_execution_provider(pk_settings)

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

    async def _initialize_fasterwhisper(
        self,
        on_status: Optional[Callable[[str, float | None], Awaitable[None]]] = None,
    ):
        """Download and initialize FasterWhisper."""
        if on_status:
            await on_status("Initializing speech-to-text (FasterWhisper)...", None)

        model_dir = self.model_downloader.get_model_dir("faster-whisper")

        await asyncio.get_event_loop().run_in_executor(
            None, self.fasterwhisper.load, model_dir
        )

        # Health check
        if on_status:
            await on_status("Verifying speech-to-text...", None)

        await self._health_check_fasterwhisper()

    def _auto_detect_execution_provider(self, pk_settings):
        """Auto-detect CUDA and set execution_provider if still on default (cpu)."""
        if pk_settings.execution_provider != "cpu":
            # User has manually set a non-default provider — respect it
            self.printr.print(
                f"Parakeet execution_provider already set to '{pk_settings.execution_provider}', skipping auto-detection.",
                server_only=True,
                color=LogType.INFO,
            )
            return

        if platform.system() == "Darwin":
            # macOS — always CPU (CoreML excluded for TDT models)
            pk_settings.execution_provider = "cpu"
            return

        if self.system_manager.is_cuda_available():
            pk_settings.execution_provider = "cuda"
            gpu_name = self.system_manager.get_gpu_name() or "Unknown GPU"
            self.printr.print(
                f"CUDA detected ({gpu_name}). Setting Parakeet to CUDA execution provider.",
                server_only=True,
                color=LogType.POSITIVE,
            )
        else:
            pk_settings.execution_provider = "cpu"
            self.printr.print(
                "No CUDA available. Parakeet will use CPU execution provider.",
                server_only=True,
                color=LogType.INFO,
            )

        # Persist to settings
        self.settings_service.save_settings_to_disk()

    async def switch_provider(self, new_provider: VoiceActivationSttProvider):
        """Switch active STT provider. Unloads old, downloads + loads new."""
        old_provider = self.active_provider

        # Unload current provider
        if old_provider == VoiceActivationSttProvider.PARAKEET:
            self.parakeet.unload()
        elif old_provider == VoiceActivationSttProvider.FASTER_WHISPER:
            self.fasterwhisper.unload()

        # Initialize new provider
        va_settings = self.settings_service.settings.voice_activation
        if new_provider == VoiceActivationSttProvider.PARAKEET and va_settings.parakeet.run_locally:
            await self._initialize_parakeet()
        elif new_provider == VoiceActivationSttProvider.FASTER_WHISPER:
            await self._initialize_fasterwhisper()

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

    async def _health_check_fasterwhisper(self):
        """Run a quick transcription test on the loaded FasterWhisper model."""
        if not self.fasterwhisper.model:
            self.printr.toast_warning(
                "FasterWhisper model not loaded — health check skipped."
            )
            return

        wav_path = os.path.join(self.app_root_path, "audio_samples", "beep.wav")
        config = FasterWhisperSttConfig(
            beam_size=1, best_of=1, temperature=0.0,
            no_speech_threshold=0.7, language_detection_threshold=0.5,
            multilingual=False, language=None, hotwords=[], additional_hotwords=[],
        )
        try:
            result = self.fasterwhisper.transcribe(
                config=config, filename=wav_path, hotwords=None
            )
            if result and result.text is not None:
                self.printr.print(
                    "FasterWhisper health check passed.",
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
        """Unload all STT providers. Called on shutdown."""
        self.parakeet.unload()
        self.fasterwhisper.unload()
        self.active_provider = None
