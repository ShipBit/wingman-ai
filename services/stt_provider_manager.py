import asyncio
import os
import shutil
from typing import Awaitable, Callable, Optional

from api.enums import LogType, SttProvider
from api.interface import ParakeetSttConfig
from providers import parakeet_r2
from providers.parakeet import Parakeet
from services.model_downloader import ModelDownloader
from services.printr import Printr
from services.system_manager import SystemManager


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

        # Download model (our R2 mirror, see providers/parakeet_r2.py)
        loop = asyncio.get_running_loop()

        def progress(filename: str, pct: float, downloaded_mb: float, total_mb: float):
            if on_status:
                asyncio.run_coroutine_threadsafe(
                    on_status(
                        f"Downloading speech-to-text model ({downloaded_mb} of {total_mb} MB)...",
                        pct / 100,
                    ),
                    loop,
                )

        try:
            for name, (_source, size, sha256) in parakeet_r2.FILES.items():
                path = await self.model_downloader.download_file(
                    url=parakeet_r2.file_url(name),
                    category=parakeet_r2.MODEL_DIR,
                    filename=name,
                    on_progress=progress,
                    size=size,
                    sha256=sha256,
                )
            model_path = os.path.dirname(path)
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

        if await self._health_check_parakeet():
            await asyncio.to_thread(self._remove_old_parakeet)

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
                return True
            else:
                self.printr.toast_warning(
                    "STT loaded but verification failed — transcription may not work correctly."
                )
        except Exception as e:
            self.printr.toast_warning(
                f"STT verification failed: {e}. Transcription may not work correctly."
            )
        return False

    def _remove_old_parakeet(self):
        """Delete the istupakov v3 export Core ran before (3.2 GB), once the
        new model works. Only that folder, and only when it holds that model."""
        old = os.path.join(self.model_downloader.models_root, parakeet_r2.OLD_MODEL_DIR)
        if not os.path.exists(os.path.join(old, "encoder-model.onnx.data")):
            return
        try:
            shutil.rmtree(old)
            self.printr.print(
                "Removed the previous Parakeet model (3.2 GB).",
                server_only=True,
            )
        except OSError as e:
            self.printr.print(
                f"Could not remove the previous Parakeet model in {old}: {e}",
                color=LogType.WARNING,
                server_only=True,
            )

    def unload_all(self):
        """Unload the local model. Called on shutdown."""
        self.parakeet.unload()
        self.active_provider = None
