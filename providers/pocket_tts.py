import os
import io
import sys
import platform
import glob
import asyncio
from typing import Optional
import torch
import torchaudio
from pocket_tts import TTSModel
from api.enums import LogType
from api.interface import (
    PocketTTSConfig,
    SoundConfig,
    PocketTTSSettings,
    WingmanInitializationError,
    VoiceInfo,
)
from services.file import get_custom_voices_dir
from services.audio_player import AudioPlayer
from services.printr import Printr


MODELS_DIR = "pocket-tts-models"
POCKET_TTS_VOICES_DIR = "embeddings"
INCLUDED_VOICES_DIR = "pocket-tts-voices"


class PocketTTS:
    def __init__(self, settings: Optional[PocketTTSSettings] = None):
        if settings is None:
            settings = PocketTTSSettings(enable=False)
        self.settings = settings
        self.printr = Printr()
        self.model: Optional[TTSModel] = None
        self.voices_dir = get_custom_voices_dir()
        self.wingman_included_voices_dir = self._get_wingman_included_voices_dir()
        self.voice_cache = {}
        self._playback_buffer = bytearray()

        # Initialize the model
        if self.settings.enable:
            self.load_model()

    def validate(self, errors: list[WingmanInitializationError]):
        pass

    def update_settings(self, settings: PocketTTSSettings):
        requires_reload = self.settings.custom_model_path != settings.custom_model_path
        requires_restart = (
            self.settings.enable != settings.enable
            or self.settings.custom_model_path != settings.custom_model_path
            or requires_reload
        )

        self.settings = settings
        self.voices_dir = get_custom_voices_dir()
        self.wingman_included_voices_dir = self._get_wingman_included_voices_dir()

        if self.settings.enable:
            if requires_restart:
                self.unload_model()  # Clean up old model if any
                self.load_model()
        else:
            self.unload_model()

        self.printr.print("PocketTTS settings updated.", server_only=True)

    def load_model(self):
        """Load the PocketTTS model."""
        try:
            model_path = self.settings.custom_model_path
            if model_path and os.path.exists(model_path):
                self.printr.print(
                    f"Loading PocketTTS model from custom model path: {model_path}",
                    color=LogType.INFO,
                    server_only=True,
                )
                self.model = TTSModel.load_model(config=model_path)
            else:
                try:
                    default_model_path = self._get_default_model_path()
                    self.printr.print(
                        f"Loading default PocketTTS model from path: {default_model_path}...",
                        color=LogType.INFO,
                        server_only=True,
                    )
                    self.model = TTSModel.load_model(config=default_model_path)
                except Exception:
                    self.printr.print(
                        "Loading backup default PocketTTS model (voice cloning may not be available)...",
                        color=LogType.INFO,
                        server_only=True,
                    )
                    self.model = TTSModel.load_model()

            self.printr.print(
                "PocketTTS Model loaded.",
                color=LogType.POSITIVE,
                server_only=True,
            )
        except Exception as e:
            self.printr.print(
                f"Failed to load PocketTTS model: {e}",
                color=LogType.ERROR,
                server_only=True,
            )

    def unload_model(self):
        """Unload the model to free resources."""
        if self.model:
            del self.model
            self.model = None

        # Explicitly clear CUDA cache if using GPU to free GPU memory
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        self.voice_cache.clear()

        self.printr.print(
            "PocketTTS Model unloaded.", color=LogType.INFO, server_only=True
        )

    # Probably can delete after testing
    def list_voices(self):
        """List available voices: Built-ins + Scanned Directory."""
        builtin_map = {
            "alba": "alba",
            "marius": "marius",
            "javert": "javert",
            "jean": "jean",
            "fantine": "fantine",
            "cosette": "cosette",
            "eponine": "eponine",
            "azelma": "azelma",
        }

        voices = []
        for name_id, _ in builtin_map.items():
            voices.append({"id": name_id, "name": name_id.capitalize()})

        if self.voices_dir and os.path.isdir(self.voices_dir):
            extensions = ("*.wav", "*.mp3", "*.flac")
            audio_files = []
            for ext in extensions:
                audio_files.extend(glob.glob(os.path.join(self.voices_dir, ext)))

            for f in audio_files:
                name = os.path.basename(f)
                stem = os.path.splitext(name)[0]
                voices.append({"id": stem, "name": f"Local: {stem}"})

        return voices

    async def get_available_voices(self) -> list[VoiceInfo]:
        """List available voices for API: Built-ins (provider: pocket_tts) + Custom (provider: custom_voices)."""
        builtin_map = {
            "alba": "alba",
            "marius": "marius",
            "javert": "javert",
            "jean": "jean",
            "fantine": "fantine",
            "cosette": "cosette",
            "eponine": "eponine",
            "azelma": "azelma",
        }

        voices: list[VoiceInfo] = []
        # Built-in voices
        for name_id, _ in builtin_map.items():
            voices.append(
                VoiceInfo(
                    id=name_id, name=f"PocketTTS: {name_id}", provider="pocket_tts"
                )
            )
        # Wingman included cc0 voices
        if self.wingman_included_voices_dir and os.path.isdir(
            self.wingman_included_voices_dir
        ):
            extensions = ("*.wav", "*.mp3", "*.flac", "*.safetensors")
            audio_files = []
            for ext in extensions:
                audio_files.extend(
                    glob.glob(os.path.join(self.wingman_included_voices_dir, ext))
                )

            for f in audio_files:
                name = os.path.basename(f)
                stem = os.path.splitext(name)[0]
                voices.append(
                    VoiceInfo(
                        id=stem,
                        name=f"Wingman Included: {stem}",
                        provider="wingman_included",
                    )
                )
        # Custom voices
        if self.voices_dir and os.path.isdir(self.voices_dir):
            extensions = ("*.wav", "*.mp3", "*.flac", "*.safetensors")
            audio_files = []
            for ext in extensions:
                audio_files.extend(glob.glob(os.path.join(self.voices_dir, ext)))

            for f in audio_files:
                name = os.path.basename(f)
                stem = os.path.splitext(name)[0]
                voices.append(
                    VoiceInfo(id=stem, name=f"Local: {stem}", provider="custom_voices")
                )

        return voices

    def get_voice_state(self, voice_id_or_path):
        """Resolve voice ID to a model state with caching."""
        if not self.model:
            raise RuntimeError("PocketTTS Model is not loaded.")

        # 1. Normalize/Resolve the ID to its final path/form first
        resolved_key = voice_id_or_path
        # Check Pocket-TTS voices
        built_in_voices_dir = self._get_pocket_tts_included_voices_dir()
        possible_path = os.path.join(built_in_voices_dir, f"{resolved_key}.safetensors")
        if os.path.exists(possible_path):
            resolved_key = os.path.abspath(possible_path)
        # Check WingmanAI included voices
        if self.wingman_included_voices_dir:
            possible_path = os.path.join(
                self.wingman_included_voices_dir, voice_id_or_path
            )
            if os.path.exists(possible_path):
                resolved_key = os.path.abspath(possible_path)
            else:
                # Try finding file with supported extensions, preferring safetensors over other formats
                for ext in [
                    ".safetensors",
                    ".wav",
                    ".mp3",
                    ".flac",
                ]:
                    p = possible_path + ext
                    if os.path.exists(p):
                        resolved_key = os.path.abspath(p)
                        break
        # Check custom voices directory
        if self.voices_dir:
            possible_path = os.path.join(self.voices_dir, voice_id_or_path)
            if os.path.exists(possible_path):
                resolved_key = os.path.abspath(possible_path)
            else:
                # Try finding file with supported extensions, preferring safetensors over other formats
                for ext in [
                    ".safetensors",
                    ".wav",
                    ".mp3",
                    ".flac",
                ]:
                    p = possible_path + ext
                    if os.path.exists(p):
                        resolved_key = os.path.abspath(p)
                        break
        elif os.path.exists(voice_id_or_path):
            resolved_key = os.path.abspath(voice_id_or_path)

        # 2. Check cache
        if resolved_key in self.voice_cache:
            return self.voice_cache[resolved_key]

        # 3. Load
        try:
            state = self.model.get_state_for_audio_prompt(resolved_key)
            self.voice_cache[resolved_key] = state
            return state
        except Exception as e:
            self.printr.print(
                f"Failed to load voice {resolved_key}: {e}", color=LogType.ERROR
            )
            raise ValueError(f"Voice '{voice_id_or_path}' could not be loaded.") from e

    async def play_audio(
        self,
        text: str,
        config: PocketTTSConfig,
        sound_config: SoundConfig,
        audio_player: AudioPlayer,
        wingman_name: str,
    ):
        if not text:
            return

        if not self.model:
            self.printr.toast_error("PocketTTS model not loaded.")
            return
        # Hack for pocket-tts sometimes skipping first syllable in short generations
        text = "..." + text
        try:
            # We assume config.voice holds the voice ID or path
            voice_id = config.voice if config.voice else "alba"
            voice_state = self.get_voice_state(voice_id)

            if config.output_streaming:
                await self._stream_audio(
                    text, voice_state, sound_config, audio_player, wingman_name
                )
            else:
                await self._generate_and_play(
                    text, voice_state, sound_config, audio_player, wingman_name
                )

        except Exception as e:
            self.printr.toast_error(f"PocketTTS Synthesis failed: {str(e)}")
            self.printr.print(f"PocketTTS Generation failed: {e}", color=LogType.ERROR)

    async def _generate_and_play(
        self, text, voice_state, sound_config, audio_player, wingman_name
    ):
        """Generate full audio and play it."""
        # Run generation in a thread to avoid blocking asyncio loop
        loop = asyncio.get_event_loop()
        audio_tensor = await loop.run_in_executor(
            None, self.model.generate_audio, voice_state, text
        )

        # Convert to bytes (wav)
        # Note: AudioPlayer play_with_effects might handle raw numpy, let's try to match its expectation
        # It calls get_audio_from_stream(input_data) if bytes.

        audio_buffer = self._convert_audio(audio_tensor, self.model.sample_rate, "wav")

        # Convert buffer to bytes
        audio_bytes = audio_buffer.getvalue()

        await audio_player.play_with_effects(
            input_data=audio_bytes,
            config=sound_config,
            wingman_name=wingman_name,
        )

    async def _stream_audio(
        self, text, voice_state, sound_config, audio_player, wingman_name
    ):
        """Stream generation."""
        # Initialize the stream generator
        stream = self.model.generate_audio_stream(voice_state, text)
        iterator = iter(stream)

        # Internal buffer to store excess data from generator
        self._playback_buffer = bytearray()

        def buffer_callback(out_buffer: bytearray) -> int:
            """
            Callback for AudioPlayer to pull data.
            It fills `out_buffer` and returns number of bytes written.
            """
            out_capacity = len(out_buffer)
            written = 0

            # 1. Fill from internal buffer first
            if len(self._playback_buffer) > 0:
                to_copy = min(len(self._playback_buffer), out_capacity)
                out_buffer[:to_copy] = self._playback_buffer[:to_copy]
                self._playback_buffer[:] = self._playback_buffer[
                    to_copy:
                ]  # Remove copied data
                written += to_copy

                if written == out_capacity:
                    return written

            # 2. If we need more, fetch from generator
            try:
                # Keep fetching chunks until we fill the buffer or run out
                while written < out_capacity:
                    # Note: next(iterator) blocks. We accept this for now
                    # as true async processing requires substantial AudioPlayer changes.
                    chunk_tensor = next(iterator)

                    if chunk_tensor.is_cuda:
                        chunk_tensor = chunk_tensor.cpu()
                    if chunk_tensor.dim() == 1:
                        chunk_tensor = chunk_tensor.unsqueeze(0)

                    # Convert to int16 PCM bytes
                    c = (chunk_tensor * 32767).clamp(-32768, 32767).to(torch.int16)
                    chunk_bytes = c.numpy().tobytes()

                    # Determine how much fits
                    space_left = out_capacity - written
                    to_copy = min(len(chunk_bytes), space_left)

                    data_to_write = chunk_bytes[:to_copy]
                    out_buffer[written : written + len(data_to_write)] = data_to_write
                    written += len(data_to_write)

                    # Store excess
                    if len(chunk_bytes) > to_copy:
                        self._playback_buffer.extend(chunk_bytes[to_copy:])

            except StopIteration:
                pass  # End of stream
            except Exception as e:
                self.printr.print(f"PocketTTS stream error: {e}", color=LogType.ERROR)

            return written

        await audio_player.stream_with_effects(
            buffer_callback=buffer_callback,
            config=sound_config,
            wingman_name=wingman_name,
            sample_rate=self.model.sample_rate,
            dtype="int16",
            channels=1,
            use_gain_boost=True,
        )

    # --- Utilities ---
    def _convert_audio(
        self, audio_tensor: torch.Tensor, sample_rate: int, target_format: str = "wav"
    ) -> io.BytesIO:
        buffer = io.BytesIO()
        if audio_tensor.is_cuda:
            audio_tensor = audio_tensor.cpu()
        if audio_tensor.dim() == 1:
            audio_tensor = audio_tensor.unsqueeze(0)

        try:
            torchaudio.save(buffer, audio_tensor, sample_rate, format=target_format)
            buffer.seek(0)
            return buffer
        except Exception as e:
            self.printr.print(
                f"Error converting audio to {target_format}: {e}", color=LogType.ERROR
            )
            raise e

    def _validate_format(self, fmt: str) -> str:
        fmt = fmt.lower()
        valid_formats = {"mp3", "wav", "opus", "aac", "flac", "pcm"}
        if fmt == "mpeg":
            return "mp3"
        if fmt not in valid_formats:
            return "wav"
        return fmt

    def _get_app_dir(self) -> str:
        """Return the application root directory (bundle-aware).

        In PyInstaller one-dir builds, runtime assets often live under an internal
        directory (e.g. "_internal"), while our bundled models/voices are located
        alongside that directory. We therefore resolve to the parent of
        the PyInstaller extraction directory ("_MEIPASS") when bundled.
        """

        app_is_bundled = getattr(sys, "frozen", False)
        if app_is_bundled:
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                return os.path.dirname(meipass)

        # Source/dev layout: <repo>/providers/pocket_tts.py -> app root is two dirs up.
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _get_default_model_path(self) -> str:
        is_windows = platform.system() == "Windows"
        if is_windows:
            app_dir = self._get_app_dir()
            model_path = os.path.join(app_dir, MODELS_DIR, "b6369a24.yaml")
        else:
            model_path = "b6369a24"
        return model_path

    def _get_pocket_tts_included_voices_dir(self) -> str:
        # Determine path to PocketTTS included/bundled embeddings directory
        app_dir = self._get_app_dir()
        return os.path.join(app_dir, MODELS_DIR, POCKET_TTS_VOICES_DIR)

    def _get_wingman_included_voices_dir(self) -> str:
        # Determine path to wingman included voices directory
        app_dir = self._get_app_dir()
        return os.path.join(app_dir, INCLUDED_VOICES_DIR)
