import asyncio
import os
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

# Mirror of faster_whisper.utils._MODELS — duplicated so we can fetch the
# snapshot via our own ModelDownloader (with progress/status broadcasting)
# instead of relying on faster_whisper's silent tqdm download.
FASTER_WHISPER_REPO_MAP = {
    "tiny.en":           "Systran/faster-whisper-tiny.en",
    "tiny":              "Systran/faster-whisper-tiny",
    "base.en":           "Systran/faster-whisper-base.en",
    "base":              "Systran/faster-whisper-base",
    "small.en":          "Systran/faster-whisper-small.en",
    "small":             "Systran/faster-whisper-small",
    "medium.en":         "Systran/faster-whisper-medium.en",
    "medium":            "Systran/faster-whisper-medium",
    "large-v1":          "Systran/faster-whisper-large-v1",
    "large-v2":          "Systran/faster-whisper-large-v2",
    "large-v3":          "Systran/faster-whisper-large-v3",
    "large":             "Systran/faster-whisper-large-v3",
    "distil-large-v2":   "Systran/faster-distil-whisper-large-v2",
    "distil-medium.en":  "Systran/faster-distil-whisper-medium.en",
    "distil-small.en":   "Systran/faster-distil-whisper-small.en",
    "distil-large-v3":   "Systran/faster-distil-whisper-large-v3",
    "distil-large-v3.5": "distil-whisper/distil-large-v3.5-ct2",
    "large-v3-turbo":    "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "turbo":             "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}

FASTER_WHISPER_ALLOW_PATTERNS = [
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
]


def resolve_faster_whisper_repo(model_size: str) -> str:
    """Resolve a FasterWhisper ``model_size`` to a HuggingFace repo ID.

    Accepts either a bare size ('distil-large-v3') or a user-supplied repo
    path ('Systran/faster-whisper-large-v3'); the latter is passed through.
    """
    if "/" in model_size:
        return model_size
    repo = FASTER_WHISPER_REPO_MAP.get(model_size)
    if not repo:
        raise ValueError(
            f"Unknown FasterWhisper model_size '{model_size}'. "
            f"Expected one of: {', '.join(FASTER_WHISPER_REPO_MAP.keys())}, "
            f"or a HuggingFace repo path."
        )
    return repo


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
        fw_settings = self.settings_service.settings.voice_activation.fasterwhisper
        model_size = fw_settings.model_size

        try:
            repo_id = resolve_faster_whisper_repo(model_size)
        except ValueError as e:
            self.printr.toast_error(str(e))
            return

        # Download model snapshot via our ModelDownloader so the UI gets a
        # 'Downloading...' status message — mirrors the Parakeet flow.
        try:
            if on_status:
                await on_status(
                    f"Downloading STT model (FasterWhisper: {model_size})...", None
                )

            await self.model_downloader.download_huggingface(
                repo_id=repo_id,
                category=f"faster-whisper/{model_size}",
                allow_patterns=FASTER_WHISPER_ALLOW_PATTERNS,
            )
        except Exception as e:
            self.printr.toast_error(
                f"Could not download the FasterWhisper STT model. "
                f"Please check your internet connection and restart Wingman AI. "
                f"If the problem persists, report it at github.com/ShipBit/wingman-ai/issues\n"
                f"Error: {e}"
            )
            return

        # Load model
        if on_status:
            await on_status("Initializing speech-to-text...", None)

        model_dir = self.model_downloader.get_model_dir("faster-whisper")
        await asyncio.get_event_loop().run_in_executor(
            None, self.fasterwhisper.load, model_dir
        )

        # Health check
        if on_status:
            await on_status("Verifying speech-to-text...", None)

        await self._health_check_fasterwhisper()

    async def switch_provider(
        self,
        new_provider: VoiceActivationSttProvider,
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
            if old_provider == VoiceActivationSttProvider.PARAKEET:
                self.parakeet.unload()
            elif old_provider == VoiceActivationSttProvider.FASTER_WHISPER:
                self.fasterwhisper.unload()

            # Initialize new provider
            va_settings = self.settings_service.settings.voice_activation
            if new_provider == VoiceActivationSttProvider.PARAKEET and va_settings.parakeet.run_locally:
                await self._initialize_parakeet(on_status)
            elif new_provider == VoiceActivationSttProvider.FASTER_WHISPER:
                await self._initialize_fasterwhisper(on_status)

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
