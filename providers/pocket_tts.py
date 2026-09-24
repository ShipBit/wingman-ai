import os
import io
import glob
import asyncio
import threading
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Callable, Optional

import torch
import torchaudio
from pocket_tts import TTSModel
from safetensors import safe_open
from safetensors.torch import load_file, save_file
from pocket_tts.utils.utils import get_predefined_voice

try:
    from pocket_tts.models.text_chunking import split_into_best_sentences
except ImportError:  # before 3.1.0 it lived in tts_model
    from pocket_tts.models.tts_model import split_into_best_sentences

try:
    # Private in pocket-tts; the list of built-in voices it has embeddings for.
    from pocket_tts.utils.utils import _ORIGINS_OF_PREDEFINED_VOICES as _PREDEFINED
except ImportError:  # renamed in a later release: the 3.1.0 set
    _PREDEFINED = dict.fromkeys(
        "alba anna azelma bill_boerst caro_davy charles cosette eponine estelle "
        "eve fantine george giovanni jane javert jean juergen lola marius mary "
        "michael paul peter_yearsley rafael stuart_bell vera".split()
    )
from api.enums import LogType, PocketTtsQuality, SpokenLanguage, TtsProvider, TtsVoiceGender
from api.interface import (
    PocketTTSConfig,
    SoundConfig,
    PocketTTSSettings,
    WingmanInitializationError,
    VoiceInfo,
)
from providers.interfaces import TtsInterface, tts_provider
from providers.pocket_tts_chunks import (
    MAX_TOKENS,
    faded_edges,
    frames_after_eos,
    pieces_for_speech,
)
from providers.pocket_tts_voices import (
    install_bundled_voices,
    load_bundled_voices,
    read_voice_details,
)
from providers.pocket_tts_r2 import (
    build_r2_config,
    download_url_to_path,
    hf_uri_to_https_url,
    prefetch_gated_weights,
    use_r2_mirror,
)
from services.file import get_custom_voices_dir, get_pocket_tts_models_dir
from services.spoken_language import pocket_tts_has_high_quality, pocket_tts_model
from services.audio_player import AudioPlayer
from services.printr import Printr
from providers.open_ai import OpenAiCompatibleTts

if TYPE_CHECKING:
    from api.interface import WingmanConfig


def _library_version() -> str:
    """The installed pocket-tts, as the UI shows it next to the model."""
    try:
        from importlib.metadata import version

        return version("pocket-tts")
    except Exception:
        return "unknown"


POCKET_TTS_VERSION = _library_version()

BUILTIN_MODEL_TEMPERATURE = 0.3
"""Sampling temperature for the built-in models. pocket-tts 3.0 set 0.3 for
English after human listening tests (#223) and left every other language on
the library's 0.7. Measured 2026-09-23, German model, 3 voices x 5 sentences x
2 seeds, transcribed by Parakeet: 10.6% word errors at 0.7, 6.3% at 0.3
(English: 5.7%). A user's own YAML model keeps the temperature it sets."""



# Label == id so the exact pocket-tts model name is visible in the UI and
# matches the tag baked into generated ``<voice>.<id>.safetensors`` caches.
# Makes it obvious when a model family changes (e.g. english_2026-04 -> _06)
# and cached clones need regenerating.
BUILTIN_MODELS = [
    {"id": "english_2026-04", "label": "english_2026-04", "quality": "6L"},
    {"id": "german",          "label": "german",          "quality": "6L"},
    {"id": "german_24l",      "label": "german_24l",      "quality": "24L"},
    {"id": "french_24l",      "label": "french_24l",      "quality": "24L"},
    {"id": "spanish",         "label": "spanish",         "quality": "6L"},
    {"id": "spanish_24l",     "label": "spanish_24l",     "quality": "24L"},
    {"id": "italian",         "label": "italian",         "quality": "6L"},
    {"id": "italian_24l",     "label": "italian_24l",     "quality": "24L"},
    {"id": "portuguese",      "label": "portuguese",      "quality": "6L"},
    {"id": "portuguese_24l",  "label": "portuguese_24l",  "quality": "24L"},
]


class PocketTTS:
    @staticmethod
    def normalize_remote_url(host: str, port: int) -> str:
        """Build a clean base URL from possibly messy user input.

        Handles all common mistakes:
          - scheme included (http://, https://)
          - port embedded in host (host:8000)
          - /v1 path appended
          - trailing slashes
          - leading/trailing whitespace

        Returns ``http://<host>:<port>`` (no trailing slash, no /v1).
        """
        url = (host or "localhost").strip()
        # strip scheme
        for scheme in ("https://", "http://"):
            if url.lower().startswith(scheme):
                url = url[len(scheme) :]
                break
        # strip paths like /v1, /v1/, or just /
        url = url.rstrip("/")
        if url.endswith("/v1"):
            url = url[:-3].rstrip("/")
        # if user embedded port in host (e.g. "myhost:8000"), use it
        if ":" in url:
            host_part, port_str = url.rsplit(":", 1)
            if port_str.isdigit():
                return f"http://{host_part}:{port_str}"
        return f"http://{url}:{port}"

    def __init__(
        self,
        settings: Optional[PocketTTSSettings] = None,
        spoken_language: SpokenLanguage = SpokenLanguage.EN,
        defer_load: bool = False,
        app_root_path: Optional[str] = None,
    ):
        if settings is None:
            settings = PocketTTSSettings(
                enable=False,
                quality=PocketTtsQuality.STANDARD,
                host="localhost",
                port=5002,
            )
        self.settings = settings
        # The model follows the language the user speaks; see model_id.
        self.spoken_language = spoken_language
        self.printr = Printr()
        self.model: Optional[TTSModel] = None
        self.remote_client: Optional[OpenAiCompatibleTts] = None
        self.voices_dir = get_custom_voices_dir()
        self.models_dir = get_pocket_tts_models_dir()
        # Recordings of native speakers Wingman ships (see pocket_tts_voices),
        # by voice id. Once copied into voices_dir they are custom voices.
        self.app_root_path = app_root_path
        self.bundled_voices = {v.id: v for v in load_bundled_voices(app_root_path)}
        # LRU-bounded voice state cache — each entry is a dict of tensors and
        # can be tens of MB. Keep the most recent 32 voices (well over a
        # typical tower size) and drop the oldest on overflow.
        self.voice_cache: OrderedDict[str, dict] = OrderedDict()
        self._loading = False
        self.on_model_reloaded: Optional[Callable[[], None]] = None
        # The model the last successful load brought up, and whether that load
        # replaced a different one (a new spoken language or quality) rather
        # than being the first load after start.
        self._loaded_model_id: Optional[str] = None
        self.last_load_switched_model = False
        # The model the one-off warm-up generation ran on (see warm_up).
        # The model instance the one-off warm-up generation ran on (see warm_up).
        self._warmed_model: Optional[TTSModel] = None
        # Two layers of serialization for v2's explicitly-non-thread-safe TTSModel:
        # - _async_gen_lock: only one coroutine may synthesize at a time. This
        #   singleton outlives any single event loop: push-to-talk interactions
        #   each run on their own loop (see the asyncio.new_event_loop() handlers
        #   in wingman_core). An asyncio.Lock binds to the loop it is first used
        #   on and raises "bound to a different event loop" everywhere else, so
        #   we keep one lock per loop, created on demand in _gen_lock(). This
        #   only needs to prevent same-loop re-entrancy (which could deadlock on
        #   _model_swap_lock); cross-thread model safety is _model_swap_lock's job.
        # - _model_swap_lock: reload (daemon thread) waits for in-flight
        #   generation (executor / audio callback threads) before unloading.
        self._async_gen_lock: Optional[asyncio.Lock] = None
        self._async_gen_lock_loop: Optional[asyncio.AbstractEventLoop] = None
        self._model_swap_lock = threading.Lock()
        # Serializes built-in voice embedding downloads so concurrent
        # get_voice_state calls for the same voice don't fetch it twice.
        self._builtin_voice_download_lock = threading.Lock()

        # Precompute progress state — surfaced via get_status() so the UI can
        # poll inline progress without a dedicated endpoint.
        self._precompute_running: bool = False
        self._precompute_current: int = 0
        self._precompute_total: int = 0
        self._precompute_voice: str = ""

        if not defer_load and self.settings.enable:
            if self.settings.run_locally:
                self.load_model()
            else:
                self._init_remote_client()

    def deferred_init(self):
        """Perform the deferred model load / remote client init (called during startup)."""
        if self.settings.enable:
            if self.settings.run_locally:
                self.load_model()
            else:
                self._init_remote_client()

    def _init_remote_client(self):
        """Initialize the OpenAI-compatible client for remote PocketTTS."""
        base_url = (
            self.normalize_remote_url(self.settings.host, self.settings.port) + "/v1"
        )
        self.remote_client = OpenAiCompatibleTts(
            api_key="not-needed",
            base_url=base_url,
        )
        self.printr.print(
            f"PocketTTS remote client initialized: {base_url}",
            color=LogType.INFO,
            server_only=True,
        )

    def _destroy_remote_client(self):
        """Tear down the remote client."""
        self.remote_client = None

    def validate(self, errors: list[WingmanInitializationError]):
        pass

    def update_settings(
        self, settings: PocketTTSSettings, spoken_language: SpokenLanguage
    ):
        old = self.settings
        old_model_id = self.model_id
        self.settings = settings
        self.spoken_language = spoken_language
        self.voices_dir = get_custom_voices_dir()

        if not settings.enable:
            # Disabled — tear down everything
            if old.enable and old.run_locally:
                self.unload_model()
            self._destroy_remote_client()
            self.printr.print("PocketTTS disabled.", server_only=True)
            return

        if settings.run_locally:
            # Local mode
            if self.remote_client:
                self._destroy_remote_client()
            needs_reload = (
                not old.enable
                or not old.run_locally
                or old_model_id != self.model_id
            )
            if needs_reload:
                def _reload():
                    # Wait for any in-flight generation to finish before swapping
                    # the model out — pocket-tts v2's TTSModel is not thread-safe.
                    with self._model_swap_lock:
                        self.unload_model()
                        self.load_model()

                threading.Thread(target=_reload, daemon=True).start()
        else:
            # Remote mode
            if old.run_locally and old.enable:
                self.unload_model()
            needs_reconnect = (
                not old.enable
                or old.run_locally
                or old.host != settings.host
                or old.port != settings.port
            )
            if needs_reconnect:
                self._destroy_remote_client()
                self._init_remote_client()

        self.printr.print("PocketTTS settings updated.", server_only=True)

    @property
    def model_id(self) -> str:
        """The model for the spoken language in the chosen size, or the user's
        own YAML config when one is set."""
        return pocket_tts_model(
            self.spoken_language, self.settings.quality, self.settings.custom_model
        )

    def _is_custom_model(self, model_id: str) -> bool:
        """Check if a model ID refers to a custom YAML file in the models dir."""
        return model_id.endswith(".yaml") or model_id.endswith(".yml")

    def load_model(self):
        """Load the PocketTTS model using v2.0 API."""
        self._loading = True
        try:
            model_id = self.model_id

            # Never quantized. Measured 2026-09-23 on an M2 Pro, German model:
            # int8 ran at 1.2x real time on our torch 2.8 (torchao without
            # native kernels) and still only 5.9x against 6.9x unquantized on
            # torch 2.11 with them. It also degraded cloned voices on 24L.

            if self._is_custom_model(model_id):
                model_path = os.path.join(self.models_dir, model_id)
                self.printr.print(
                    f"Loading PocketTTS custom model: {model_path}...",
                    color=LogType.INFO,
                    server_only=True,
                )
                self.model = TTSModel.load_model(config=model_path)
            elif use_r2_mirror():
                # Redirect the gated voice-cloning weights to our R2 mirror so users
                # without an HF token can clone voices (see providers/pocket_tts_r2.py).
                config_path = build_r2_config(model_id, self.models_dir)
                self.printr.print(
                    f"Loading PocketTTS model: {model_id} from R2 mirror...",
                    color=LogType.INFO,
                    server_only=True,
                )
                # Pre-populate pocket_tts's cache with retries + atomic writes so
                # its own fragile download path (no timeout/retry/size check)
                # never runs for the large cloning weights. On failure, warn and
                # continue — the library falls back to the public non-cloning
                # weights instead of silently breaking with no explanation.
                try:
                    prefetch_gated_weights(
                        model_id,
                        log=lambda msg: self.printr.print(
                            msg, color=LogType.INFO, server_only=True
                        ),
                    )
                except Exception as fetch_err:
                    self.printr.toast_warning(
                        "Could not download the PocketTTS voice-cloning weights. "
                        "Voice cloning may be unavailable — check your internet "
                        f"connection and restart Wingman AI.\nError: {fetch_err}"
                    )
                self.model = TTSModel.load_model(
                    config=config_path, temp=BUILTIN_MODEL_TEMPERATURE
                )
            else:
                self.printr.print(
                    f"Loading PocketTTS model: {model_id} from HuggingFace...",
                    color=LogType.INFO,
                    server_only=True,
                )
                self.model = TTSModel.load_model(
                    language=model_id, temp=BUILTIN_MODEL_TEMPERATURE
                )

            self.printr.print(
                "PocketTTS Model loaded.",
                color=LogType.POSITIVE,
                server_only=True,
            )
            self.last_load_switched_model = (
                self._loaded_model_id is not None and self._loaded_model_id != model_id
            )
            self._loaded_model_id = model_id
            load_ok = True
        except Exception as e:
            self.printr.print(
                f"Failed to load PocketTTS model: {e}",
                color=LogType.ERROR,
                server_only=True,
            )
            load_ok = False
        finally:
            self._loading = False

        if load_ok and self.on_model_reloaded:
            try:
                self.on_model_reloaded()
            except Exception as cb_err:
                self.printr.print(
                    f"PocketTTS on_model_reloaded callback failed: {cb_err}",
                    color=LogType.WARNING,
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
        self._warmed_model = None

        self.printr.print(
            "PocketTTS Model unloaded.", color=LogType.INFO, server_only=True
        )

    def get_status(self) -> dict:
        """Return current PocketTTS status for the UI."""
        return {
            "is_loading": self._loading,
            "model_loaded": self.model is not None,
            "model": self.model_id,
            "version": POCKET_TTS_VERSION,
            # Whether "high" loads a bigger model for this language than
            # "standard"; French and English have only one size.
            "has_high_quality": pocket_tts_has_high_quality(self.spoken_language),
            "precompute_running": self._precompute_running,
            "precompute_current": self._precompute_current,
            "precompute_total": self._precompute_total,
            "precompute_voice": self._precompute_voice,
        }

    def get_available_models(self) -> list[dict]:
        """Return builtin models + any custom YAML configs found in models_dir."""
        result = list(BUILTIN_MODELS)
        if os.path.isdir(self.models_dir):
            for entry in sorted(os.listdir(self.models_dir)):
                if entry.lower().endswith((".yaml", ".yml")) and os.path.isfile(
                    os.path.join(self.models_dir, entry)
                ):
                    result.append(
                        {"id": entry, "label": entry, "quality": "Custom"}
                    )
        return result

    async def get_available_voices(self) -> list[VoiceInfo]:
        """List available voices for API: Built-ins (provider: pocket_tts) + Custom (provider: custom_voices)."""
        # Remote mode — fetch from server
        if not self.settings.run_locally:
            if not self.remote_client:
                self._init_remote_client()
            if self.remote_client:
                return await self.remote_client.get_available_voices(
                    voices_endpoint="/voices"
                )
            return []

        # Built-in voices: native speakers of the spoken language first, then
        # the rest by name. `languages` is the speaker's own language; every
        # built-in voice speaks the active model's language (per-language
        # embeddings), with that speaker's accent.
        spoken = self.spoken_language.value
        builtins = sorted(
            self._BUILTIN_VOICE_IDS,
            key=lambda v: (self._voice_native_language(v) != spoken, v),
        )
        voices: list[VoiceInfo] = [
            VoiceInfo(
                id=voice_id,
                name=voice_id.replace("_", " ").title(),
                languages=[self._voice_native_language(voice_id)],
                gender=self._BUILTIN_GENDERS.get(voice_id),
                provider="pocket_tts",
            )
            for voice_id in builtins
        ]
        # Custom voices. Built-in stems are excluded: their downloaded
        # per-language embeddings live in the same directory (see
        # _ensure_builtin_voice) but are already listed as built-ins above.
        # Recordings Wingman shipped for the spoken language go right after
        # the native built-ins, with their name and language. Name, gender
        # and a line of description come from the text file next to a voice
        # (see pocket_tts_voices), else from Wingman's list for shipped ones.
        native_count = sum(1 for v in voices if v.languages == [spoken])
        shipped: list[VoiceInfo] = []
        for stem in self._list_voice_stems(self.voices_dir):
            if stem in self._BUILTIN_VOICE_IDS:
                continue
            bundled = self.bundled_voices.get(stem)
            details = read_voice_details(os.path.join(self.voices_dir, stem + ".txt"))
            gender = details.gender or (bundled.gender if bundled else None)
            info = VoiceInfo(
                id=stem,
                name=details.name or (bundled.name if bundled else f"Local: {stem}"),
                languages=[bundled.language] if bundled else None,
                gender=next((g for g in TtsVoiceGender if g.value == gender), None),
                description=details.description or (bundled.description if bundled else None),
                provider="custom_voices",
            )
            if bundled and bundled.language == spoken:
                shipped.append(info)
            else:
                voices.append(info)
        voices[native_count:native_count] = sorted(shipped, key=lambda v: v.name or "")

        return voices

    def bundled_voices_needing_clone(self) -> list[str]:
        """Shipped voices in the custom voices folder without a current clone
        for the active model: copied by a start that was closed before it
        finished cloning them, for one. Only those of the spoken language."""
        missing = self.list_custom_voices_needing_precompute(spoken_language_only=True)
        return [v for v in missing if v in self.bundled_voices]

    def install_bundled_voices(self) -> list[str]:
        """Copy the recordings Wingman ships for the spoken language into
        the custom voices folder (see pocket_tts_voices). Returns the ids
        copied now; they still need cloning for the active model."""
        if not self.settings.run_locally or not self.bundled_voices:
            return []
        try:
            return install_bundled_voices(
                self.app_root_path, self.voices_dir, self.spoken_language.value
            )
        except OSError as e:
            self.printr.print(
                f"PocketTTS: could not copy Wingman's voices: {e}",
                color=LogType.WARNING,
                server_only=True,
            )
            return []

    def _known_model_tags(self) -> set[str]:
        """Canonical model IDs usable as a ``<stem>.<tag>.safetensors`` tag.

        Includes built-in model IDs and any bare filename (no extension) of
        custom YAML configs in ``models_dir``.
        """
        tags = {m["id"] for m in BUILTIN_MODELS}
        if os.path.isdir(self.models_dir):
            for entry in os.listdir(self.models_dir):
                if entry.lower().endswith((".yaml", ".yml")):
                    tags.add(os.path.splitext(entry)[0])
        return tags

    def _active_model_tag(self) -> str:
        """Current model ID, post-alias-resolution, safe to embed in filenames."""
        raw = self.model_id
        # Strip custom-model YAML extension if present.
        if raw.lower().endswith((".yaml", ".yml")):
            raw = os.path.splitext(raw)[0]
        return raw

    def _parse_safetensors_name(
        self, filename: str, known_tags: set[str]
    ) -> tuple[str, Optional[str]]:
        """Split ``Voice.model_tag.safetensors`` into ``("Voice", "model_tag")``.

        Returns ``(stem, None)`` for legacy / standalone safetensors files that
        don't end in a recognized model tag.
        """
        base = os.path.splitext(os.path.basename(filename))[0]  # strip .safetensors
        if "." in base:
            stem, tag = base.rsplit(".", 1)
            if tag in known_tags:
                return stem, tag
        return base, None

    def _list_voice_stems(self, directory: Optional[str]) -> list[str]:
        """Return unique voice stems in a directory, one per voice.

        Recognizes model-tagged cache files (``Voice.model_id.safetensors``)
        and legacy unlabeled ``.safetensors`` alongside raw audio
        (``.wav/.mp3/.flac``). All files sharing a stem collapse to one entry.
        """
        if not directory or not os.path.isdir(directory):
            return []

        known_tags = self._known_model_tags()
        audio_exts = ("*.wav", "*.mp3", "*.flac")
        stems: set[str] = set()

        for pattern in audio_exts:
            for f in glob.glob(os.path.join(directory, pattern)):
                stems.add(os.path.splitext(os.path.basename(f))[0])

        for f in glob.glob(os.path.join(directory, "*.safetensors")):
            stem, _tag = self._parse_safetensors_name(f, known_tags)
            stems.add(stem)

        return sorted(stems)

    def _resolve_voice_path(self, voice_id_or_path: str) -> str:
        """Resolve a voice ID or path to its final filesystem path.

        Preference order per directory:
          1. ``<id>.<active_model>.safetensors`` — model-specific cache (fastest),
             unless the voice's audio file is newer: then the user replaced it
             and the cache is stale
          2. ``<id>.wav`` / ``.mp3`` / ``.flac`` — raw audio (will clone+cache)
          3. ``<id>.safetensors`` — legacy unlabeled cache
        """
        active_tag = self._active_model_tag()
        audio_exts = (".wav", ".mp3", ".flac")
        extension_order = (f".{active_tag}.safetensors", *audio_exts, ".safetensors")

        # Built-in voices resolve ONLY to their model-tagged download (see
        # _ensure_builtin_voice) — never to raw audio or a legacy untagged
        # .safetensors, which could belong to a different (incompatible) model.
        if voice_id_or_path in self._BUILTIN_VOICE_IDS:
            return os.path.abspath(self._builtin_voice_cache_path(voice_id_or_path))

        if self.voices_dir:
            base = os.path.join(self.voices_dir, voice_id_or_path)
            if os.path.exists(base):
                return os.path.abspath(base)
            for ext in extension_order:
                p = base + ext
                if os.path.exists(p):
                    if ext == f".{active_tag}.safetensors":
                        stale = self._audio_newer_than(base, p) or (
                            not self._clone_is_current(p) and self._audio_for(base)
                        )
                        if stale:
                            return os.path.abspath(stale)
                    return os.path.abspath(p)

        if os.path.exists(voice_id_or_path):
            return os.path.abspath(voice_id_or_path)

        return voice_id_or_path

    @staticmethod
    def _audio_newer_than(base: str, cache_path: str) -> Optional[str]:
        """The voice's audio file (``base`` + .wav/.mp3/.flac) if it was
        changed after ``cache_path`` was written, else None.

        Replacing a voice's WAV under the same name must not keep the voice
        cloned from the old recording.
        """
        cache_time = os.path.getmtime(cache_path)
        for ext in (".wav", ".mp3", ".flac"):
            audio = base + ext
            if os.path.exists(audio) and PocketTTS._changed_at(audio) > cache_time:
                return audio
        return None

    @staticmethod
    def _audio_for(base: str) -> Optional[str]:
        for ext in (".wav", ".mp3", ".flac"):
            if os.path.exists(base + ext):
                return base + ext
        return None

    # Written into the header of every voice file Wingman makes. A clone is
    # tied to the pocket-tts that computed it (3.1.0's tanh GELU changed clones
    # of the same recording by ~1.5%, measured 2026-09-23), a built-in voice
    # to the upstream revision it was downloaded from. When either no longer
    # matches the installed library, the file is made again: re-cloned from
    # its recording, or re-downloaded. Files without the entry come from
    # Wingman versions before 3.2.4 and count as outdated.
    _CLONED_BY = "wingman.cloned_by"
    _DOWNLOADED_FROM = "wingman.downloaded_from"

    @staticmethod
    def _voice_file_metadata(path: str) -> dict:
        try:
            with safe_open(path, "pt") as f:
                return f.metadata() or {}
        except Exception:
            return {}

    @classmethod
    def _clone_is_current(cls, path: str) -> bool:
        """Whether a cloned voice was computed by the installed pocket-tts."""
        if POCKET_TTS_VERSION == "unknown":
            # Without a version to compare, re-cloning on every start would be
            # the only safe answer; keeping what is there is the sane one.
            return True
        return cls._voice_file_metadata(path).get(cls._CLONED_BY) == POCKET_TTS_VERSION

    @classmethod
    def _save_voice_state(cls, state: dict, path: str, metadata: dict) -> None:
        """Write a voice state the way pocket-tts' export_model_state does
        (``module/key`` tensors), plus our metadata. Atomic: a crash mid-write
        leaves the old file, never half a new one."""
        tensors = {
            f"{module}/{key}": value
            for module, module_state in state.items()
            for key, value in module_state.items()
        }
        tmp = path + ".tmp"
        save_file(tensors, tmp, metadata=metadata)
        os.replace(tmp, path)

    @staticmethod
    def _changed_at(path: str) -> float:
        """When a file last got new content. Finder and Explorer keep the
        modification time when copying, so a replaced WAV can look older than
        the cache; ctime (macOS/Linux: inode change, Windows: creation) moves
        on every copy."""
        stat = os.stat(path)
        return max(stat.st_mtime, stat.st_ctime)

    def _find_audio_for_safetensors(self, safetensors_path: str) -> Optional[str]:
        """Find a raw audio file sharing the voice stem of a .safetensors file.

        Handles both model-tagged cache files (``Voice.model_id.safetensors``)
        and legacy unlabeled ``Voice.safetensors``.
        """
        directory = os.path.dirname(safetensors_path)
        stem, _tag = self._parse_safetensors_name(
            safetensors_path, self._known_model_tags()
        )
        for ext in (".wav", ".mp3", ".flac"):
            candidate = os.path.join(directory, stem + ext)
            if os.path.exists(candidate):
                return candidate
        return None

    def _clone_from_audio_and_cache(self, audio_path: str) -> dict:
        """Clone a voice from a raw audio file and persist the state as .safetensors.

        The cache file is tagged with the active model ID — e.g.
        ``Emma Watson.english_2026-04.safetensors`` — so switching to another
        model later produces a separate cache entry instead of overwriting.

        When ``audio_path`` has no directory or no extension (nothing sensible
        to derive a cache path from), the state is returned without writing a
        disk cache.
        """
        state = self.model.get_state_for_audio_prompt(audio_path, truncate=True)
        directory = os.path.dirname(audio_path)
        stem, ext = os.path.splitext(os.path.basename(audio_path))
        if not directory or not ext:
            return state
        active_tag = self._active_model_tag()
        safetensors_path = os.path.join(
            directory, f"{stem}.{active_tag}.safetensors"
        )
        try:
            self._save_voice_state(
                state, safetensors_path, {self._CLONED_BY: POCKET_TTS_VERSION}
            )
            self.printr.print(
                f"Saved cloned voice state to {safetensors_path}",
                color=LogType.INFO,
                server_only=True,
            )
            # Drop any legacy unlabeled cache — ambiguous once tagged variants exist.
            legacy_path = os.path.join(directory, f"{stem}.safetensors")
            if os.path.exists(legacy_path) and legacy_path != safetensors_path:
                try:
                    os.remove(legacy_path)
                    self.printr.print(
                        f"Removed legacy cache {legacy_path}",
                        color=LogType.INFO,
                        server_only=True,
                    )
                except OSError:
                    pass
        except Exception as export_err:
            self.printr.print(
                f"Failed to save cloned voice state: {export_err}",
                color=LogType.WARNING,
                server_only=True,
            )
        return state

    # Predefined voice IDs that ship with the pocket-tts library. Their voice
    # states are language-specific (one per model, mutually incompatible), so we
    # download the embedding matching the active model into custom_voices as
    # ``<voice>.<model_id>.safetensors`` on first use (see _ensure_builtin_voice)
    # and resolve them exactly like cloned custom voices from there on.
    # Taken from the library, so a pocket-tts upgrade that adds voices adds
    # them here too (3.x has 26; Wingman up to 3.2.3 offered 8).
    _BUILTIN_VOICE_IDS = frozenset(_PREDEFINED)

    # The language each built-in voice's speaker spoke in the recording it was
    # made from. Kyutai recorded one native speaker per non-English language
    # (their default voice for that language); all others are English.
    _NATIVE_VOICES = {
        "juergen": "de",
        "estelle": "fr",
        "lola": "es",
        "giovanni": "it",
        "rafael": "pt",
    }

    # For the voice picker's gender filter. Measured by pitch on 2026-09-24
    # and checked against the names; alba, caro_davy and eponine speak low
    # (122-147 Hz) but are women, marius gave no reading but is Hugo's.
    _BUILTIN_GENDERS = {
        **dict.fromkeys(
            ("alba", "anna", "azelma", "caro_davy", "cosette", "eponine", "estelle",
             "eve", "fantine", "jane", "lola", "mary", "vera"),
            TtsVoiceGender.FEMALE,
        ),
        **dict.fromkeys(
            ("bill_boerst", "charles", "george", "giovanni", "javert", "jean", "juergen",
             "marius", "michael", "paul", "peter_yearsley", "rafael", "stuart_bell"),
            TtsVoiceGender.MALE,
        ),
    }

    @classmethod
    def _voice_native_language(cls, voice_id: str) -> str:
        return cls._NATIVE_VOICES.get(voice_id, "en")

    def _builtin_voice_cache_path(self, voice_id: str) -> str:
        """Where a built-in voice's embedding for the active model lives on disk."""
        return os.path.join(
            self.voices_dir, f"{voice_id}.{self._active_model_tag()}.safetensors"
        )

    def _ensure_builtin_voice(self, voice_id: str) -> str:
        """Download the language-specific embedding for a built-in voice if missing.

        pocket-tts ships pre-computed voice states for every built-in voice and
        every language in its public (non-gated) HF repo. Its own resolution of
        bare names like "alba" is unusable for us: it hard-requires the model to
        have been loaded from a config *inside* the library's config dir, and we
        always load via a rewritten config file (see build_r2_config). So we
        fetch the embedding for the active model ourselves — tagged with the
        model ID so every language keeps its own file — and let the regular
        custom-voice resolution pick it up.

        Returns the path to the tagged safetensors file. Raises when the active
        model is a custom YAML config (no upstream embeddings exist for those)
        or when the download fails.
        """
        dest = self._builtin_voice_cache_path(voice_id)
        active_tag = self._active_model_tag()
        if active_tag not in {m["id"] for m in BUILTIN_MODELS}:
            raise ValueError(
                f"Built-in voice '{voice_id}' is not available for custom model "
                f"config '{active_tag}'. Use a cloned/custom voice instead."
            )
        # The library's own pinned hf:// URI, revision included: a pocket-tts
        # bump that moves the embeddings makes the file on disk outdated.
        source = get_predefined_voice(language=active_tag, name=voice_id)
        if self._builtin_is_current(dest, source):
            return dest

        url = hf_uri_to_https_url(source)
        with self._builtin_voice_download_lock:
            if self._builtin_is_current(dest, source):
                return dest
            self.printr.print(
                f"Downloading built-in PocketTTS voice '{voice_id}' for model '{active_tag}'...",
                color=LogType.INFO,
                server_only=True,
            )
            download_url_to_path(
                url,
                dest,
                log=lambda msg: self.printr.print(
                    msg, color=LogType.INFO, server_only=True
                ),
            )
            # Record where it came from, so the next pocket-tts can tell.
            tensors = load_file(dest)
            tmp = dest + ".tmp"
            save_file(tensors, tmp, metadata={self._DOWNLOADED_FROM: source})
            os.replace(tmp, dest)
            self.voice_cache.pop(os.path.abspath(dest), None)
        return dest

    @classmethod
    def _builtin_is_current(cls, path: str, source: str) -> bool:
        if not (os.path.exists(path) and os.path.getsize(path) > 0):
            return False
        return cls._voice_file_metadata(path).get(cls._DOWNLOADED_FROM) == source

    def preload_voice_states(
        self,
        voice_ids: list[str],
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict[str, bool]:
        """Warm the voice-state cache for the given voice IDs.

        Only applies when running locally with a loaded model. Built-in voices
        are included on purpose: running right after every model (re)load, this
        is what downloads their language-specific embeddings for the newly
        selected model (cheap no-op once the files exist).

        Returns a map of voice_id -> True/False indicating success.
        """
        results: dict[str, bool] = {}
        if not self.settings.run_locally or not self.model:
            return results

        # Dedupe while preserving order.
        seen: set[str] = set()
        unique_ids = [v for v in voice_ids if v and not (v in seen or seen.add(v))]
        total = len(unique_ids)
        for i, voice_id in enumerate(unique_ids, start=1):
            if progress_cb:
                try:
                    progress_cb(i, total, voice_id)
                except Exception:
                    pass
            try:
                self.get_voice_state(voice_id)
                results[voice_id] = True
            except Exception as e:
                self.printr.print(
                    f"Failed to preload voice '{voice_id}': {e}",
                    color=LogType.WARNING,
                    server_only=True,
                )
                results[voice_id] = False
        return results

    def warm_up(self, voice_id: str) -> None:
        """Generate one short line with ``voice_id`` and throw it away.

        The first generation after a load sets up torch's kernels and caches.
        Done during loading, the first answer the user hears starts as fast
        as every later one. Once per loaded model instance, so also after
        the same model was loaded again; a no-op after that.
        """
        if not self.settings.run_locally or not self.model:
            return
        if self._warmed_model is self.model:
            return
        try:
            state = self.get_voice_state(voice_id)
            started = time.monotonic()
            with self._model_swap_lock:
                self.model.generate_audio(state, "Okay.")
            self._warmed_model = self.model
            self.printr.print(
                f"PocketTTS warmed up in {(time.monotonic() - started) * 1000:.0f} ms.",
                server_only=True,
            )
        except Exception as e:
            self.printr.print(
                f"PocketTTS warm-up failed, the first answer will be slower: {e}",
                color=LogType.WARNING,
                server_only=True,
            )

    def warm_up_voice(self, preferred: Optional[str] = None) -> str:
        """The voice to warm the model up with: ``preferred`` (a voice a
        Wingman uses), else the built-in native speaker of the spoken
        language, which every model has an embedding for."""
        if preferred:
            return preferred
        native = next(
            (v for v, lang in self._NATIVE_VOICES.items() if lang == self.spoken_language.value),
            None,
        )
        return native or "alba"

    def list_custom_voices_needing_precompute(
        self, only_stale: bool = False, spoken_language_only: bool = False
    ) -> list[str]:
        """Return custom voice stems whose tagged safetensor for the active
        model does not exist yet, or is older than the voice's audio file —
        these are the ones that would actually be cloned by a precompute pass.

        Excludes built-in voices — their embeddings are downloaded ready-made
        (see _ensure_builtin_voice), never cloned from audio.

        ``only_stale`` skips voices never cloned for this model and returns
        only clones that exist but are outdated (a newer recording, or made by
        another pocket-tts).

        ``spoken_language_only`` skips voices Wingman shipped for another
        language: after switching to English, cloning the 49 German ones
        took 75 s nobody needs. Picked anyway, such a voice is cloned when
        first used.
        """
        if not self.voices_dir or not os.path.isdir(self.voices_dir):
            return []

        active_tag = self._active_model_tag()
        audio_exts = ("*.wav", "*.mp3", "*.flac")
        needs: list[str] = []
        seen: set[str] = set()

        for pattern in audio_exts:
            for f in sorted(glob.glob(os.path.join(self.voices_dir, pattern))):
                stem = os.path.splitext(os.path.basename(f))[0]
                if stem in self._BUILTIN_VOICE_IDS or stem in seen:
                    continue
                bundled = self.bundled_voices.get(stem)
                if spoken_language_only and bundled and bundled.language != self.spoken_language.value:
                    continue
                seen.add(stem)
                tagged = os.path.join(
                    self.voices_dir, f"{stem}.{active_tag}.safetensors"
                )
                if not os.path.exists(tagged):
                    if not only_stale:
                        needs.append(stem)
                elif (
                    self._changed_at(f) > os.path.getmtime(tagged)
                    or not self._clone_is_current(tagged)
                ):
                    needs.append(stem)
        return needs

    def precompute_custom_voices(
        self,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
        only_stale: bool = False,
        spoken_language_only: bool = False,
    ) -> dict:
        """Generate + persist `.<active_model>.safetensors` for every custom
        voice that doesn't yet have a current one (see
        list_custom_voices_needing_precompute). Built-in voices are skipped.

        Returns ``{"total": N, "succeeded": int, "failed": int}``.
        """
        if not self.settings.run_locally or not self.model:
            return {"total": 0, "succeeded": 0, "failed": 0}

        targets = self.list_custom_voices_needing_precompute(
            only_stale=only_stale, spoken_language_only=spoken_language_only
        )
        total = len(targets)
        self._precompute_running = True
        self._precompute_current = 0
        self._precompute_total = total
        self._precompute_voice = ""

        succeeded = 0
        failed = 0
        try:
            for i, voice_id in enumerate(targets, start=1):
                self._precompute_current = i
                self._precompute_voice = voice_id
                if progress_cb:
                    try:
                        progress_cb(i, total, voice_id)
                    except Exception:
                        pass
                try:
                    self.get_voice_state(voice_id)
                    succeeded += 1
                except Exception as e:
                    failed += 1
                    self.printr.print(
                        f"Failed to precompute voice '{voice_id}': {e}",
                        color=LogType.WARNING,
                        server_only=True,
                    )
        finally:
            self._precompute_running = False
            self._precompute_voice = ""
        return {"total": total, "succeeded": succeeded, "failed": failed}

    _VOICE_CACHE_MAX = 32

    def _cache_voice_state(self, key: str, state: dict) -> None:
        """Insert into the LRU voice cache, evicting the oldest entry if full."""
        self.voice_cache[key] = state
        self.voice_cache.move_to_end(key)
        while len(self.voice_cache) > self._VOICE_CACHE_MAX:
            self.voice_cache.popitem(last=False)

    def get_voice_state(self, voice_id_or_path):
        """Resolve voice ID to a model state with caching."""
        if not self.model:
            raise RuntimeError("PocketTTS Model is not loaded.")

        if (
            isinstance(voice_id_or_path, str)
            and voice_id_or_path in self._BUILTIN_VOICE_IDS
        ):
            try:
                self._ensure_builtin_voice(voice_id_or_path)
            except Exception as e:
                self.printr.print(
                    f"Failed to download built-in voice '{voice_id_or_path}': {e}",
                    color=LogType.ERROR,
                )
                raise ValueError(
                    f"Built-in voice '{voice_id_or_path}' could not be downloaded "
                    "for the current model. Check your internet connection."
                ) from e

        resolved_key = self._resolve_voice_path(voice_id_or_path)

        if resolved_key in self.voice_cache:
            self.voice_cache.move_to_end(resolved_key)
            return self.voice_cache[resolved_key]

        # v2's TTSModel is not thread-safe, and this method is called from
        # multiple threads (event loop for play_audio, executor for preload /
        # precompute). Serialize model access with the swap lock.
        try:
            with self._model_swap_lock:
                if resolved_key.endswith(".safetensors"):
                    state = self.model.get_state_for_audio_prompt(resolved_key)
                else:
                    state = self._clone_from_audio_and_cache(resolved_key)
            self._cache_voice_state(resolved_key, state)
            return state
        except Exception as e:
            if resolved_key.endswith(".safetensors"):
                stem, _tag = self._parse_safetensors_name(
                    resolved_key, self._known_model_tags()
                )
                if stem in self._BUILTIN_VOICE_IDS:
                    # Built-in embedding failed to load — stale (e.g. a
                    # pocket-tts upgrade moved the pinned upstream revision) or
                    # corrupt. Drop the file and re-download exactly once.
                    self.printr.print(
                        f"Built-in voice file invalid, re-downloading: {resolved_key}",
                        color=LogType.WARNING,
                        server_only=True,
                    )
                    try:
                        try:
                            os.remove(resolved_key)
                        except OSError:
                            pass
                        self._ensure_builtin_voice(stem)
                        with self._model_swap_lock:
                            state = self.model.get_state_for_audio_prompt(
                                resolved_key
                            )
                        self._cache_voice_state(resolved_key, state)
                        return state
                    except Exception as retry_err:
                        e = retry_err
                else:
                    # .safetensors from a different model version — re-clone
                    # from raw audio. (Built-ins never take this path: they
                    # have no raw audio and must not fall back to a user file
                    # that happens to share their name.)
                    audio_path = self._find_audio_for_safetensors(resolved_key)
                    if audio_path:
                        self.printr.print(
                            f"Voice embedding incompatible with current model, re-cloning from: {audio_path}",
                            color=LogType.WARNING,
                            server_only=True,
                        )
                        with self._model_swap_lock:
                            state = self._clone_from_audio_and_cache(audio_path)
                        # Cache under the key that will be resolved on subsequent calls
                        # (the newly-written tagged safetensors, if _clone_from_audio_and_cache
                        # persisted one; else the raw audio path). Evict the dead key.
                        new_key = self._resolve_voice_path(audio_path)
                        if new_key != resolved_key:
                            self.voice_cache.pop(resolved_key, None)
                        self._cache_voice_state(new_key, state)
                        return state

            self.printr.print(
                f"Failed to load voice {resolved_key}: {e}", color=LogType.ERROR
            )
            raise ValueError(f"Voice '{voice_id_or_path}' could not be loaded.") from e

    def _gen_lock(self) -> asyncio.Lock:
        """Return an ``asyncio.Lock`` bound to the *current* running loop.

        The provider is a long-lived singleton, but synthesis can be awaited
        from different event loops over the app's lifetime (each push-to-talk
        handler thread creates its own loop). An ``asyncio.Lock`` is bound to
        the loop it is first used on and raises "bound to a different event
        loop" if awaited elsewhere, so we lazily (re)create the lock whenever
        the running loop changes. Same-loop callers always get the same lock,
        preserving the re-entrancy guard that keeps the event-loop thread from
        deadlocking on ``_model_swap_lock``.
        """
        loop = asyncio.get_running_loop()
        if self._async_gen_lock is None or self._async_gen_lock_loop is not loop:
            self._async_gen_lock = asyncio.Lock()
            self._async_gen_lock_loop = loop
        return self._async_gen_lock

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

        # Remote mode — delegate to OpenAI-compatible client
        if not self.settings.run_locally:
            if not self.remote_client:
                self._init_remote_client()
            if self.remote_client:
                await self.remote_client.play_audio(
                    text=text,
                    voice=config.voice or "alba",
                    model="pocket-tts",
                    sound_config=sound_config,
                    audio_player=audio_player,
                    wingman_name=wingman_name,
                    stream=config.output_streaming,
                    speed=config.speed,
                )
                return
            self.printr.toast_error(
                "PocketTTS remote client could not be initialized."
            )
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

            # v2's TTSModel is not thread-safe; serialize concurrent synthesis
            # from multiple wingmen sharing this singleton. The lock is bound to
            # the current running loop (see _gen_lock) so this works across the
            # per-interaction event loops the app uses.
            async with self._gen_lock():
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
        """Generate full audio and play it via the streaming playback path.

        Generates the complete audio first, then feeds it through
        stream_with_effects to avoid end-of-stream artifacts that occur
        with the OutputStream-based play_with_effects on some devices.
        """
        loop = asyncio.get_running_loop()

        def _generate() -> torch.Tensor:
            # Protect model lifecycle: a settings-change reload waits on this
            # lock before swapping self.model out.
            with self._model_swap_lock:
                return torch.cat(list(self._speech_stream(voice_state, text)))

        audio_tensor = await loop.run_in_executor(None, _generate)

        # Convert to int16 PCM bytes (same format as the streaming path)
        if audio_tensor.is_cuda:
            audio_tensor = audio_tensor.cpu()
        if audio_tensor.dim() == 2:
            audio_tensor = audio_tensor.squeeze(0)
        pcm_bytes = (
            (audio_tensor * 32767).clamp(-32768, 32767).to(torch.int16).numpy().tobytes()
        )

        # Feed the preloaded audio through a buffer callback
        read_pos = 0

        def buffer_callback(out_buffer: bytearray) -> int:
            nonlocal read_pos
            remaining = len(pcm_bytes) - read_pos
            if remaining <= 0:
                return 0
            to_copy = min(len(out_buffer), remaining)
            out_buffer[:to_copy] = pcm_bytes[read_pos : read_pos + to_copy]
            read_pos += to_copy
            return to_copy

        await audio_player.stream_with_effects(
            buffer_callback=buffer_callback,
            config=sound_config,
            wingman_name=wingman_name,
            sample_rate=self.model.sample_rate,
            dtype="int16",
            channels=1,
            use_gain_boost=True,
        )

    def _speech_stream(self, voice_state, text: str):
        """Audio chunks for ``text``, generated piece by piece so no piece
        is longer than the model handles cleanly, each faded in and out so
        the joins do not click (see pocket_tts_chunks). Caller holds
        ``_model_swap_lock``."""
        try:
            tokenizer = self.model.flow_lm.conditioner.tokenizer
            pieces = pieces_for_speech(
                text,
                split_sentences=lambda t: split_into_best_sentences(
                    tokenizer,
                    t,
                    MAX_TOKENS,
                    self.model.pad_with_spaces_for_short_inputs,
                    remove_semicolons=self.model.remove_semicolons,
                ),
                count_tokens=lambda t: len(tokenizer(t)[0]),
                language=self.spoken_language,
            )
        except Exception as e:
            # A later pocket-tts moving these internals must not cost speech.
            self.printr.print(
                f"PocketTTS: could not split the text, speaking it as one: {e}",
                color=LogType.WARNING,
                server_only=True,
            )
            pieces = [text]
        for piece in pieces:
            yield from faded_edges(
                self.model.generate_audio_stream(
                    voice_state,
                    piece,
                    # Its own limit is lower (50) and would cut the piece again.
                    max_tokens=MAX_TOKENS,
                    frames_after_eos=self.model.model_recommended_frames_after_eos
                    or frames_after_eos(piece),
                ),
                self.model.sample_rate,
            )

    # Audio the speakers hold back before they start. Covers a slow first
    # sentence boundary on a machine that makes audio only a little faster
    # than real time, at the cost of that much delay before the first word.
    _STREAM_PREBUFFER_MS = 200

    async def _stream_audio(
        self, text, voice_state, sound_config, audio_player, wingman_name
    ):
        """Stream generation.

        The model runs in a thread of its own and hands every chunk to the
        event loop through a queue, so waiting for audio never blocks the loop.
        That thread holds ``_model_swap_lock`` while it generates, so a
        settings-change reload waits until the text is spoken.
        """
        loop = asyncio.get_running_loop()
        sample_rate = self.model.sample_rate
        chunks: asyncio.Queue[Optional[bytes]] = asyncio.Queue()
        cancelled = threading.Event()

        def hand_over(chunk: Optional[bytes]) -> None:
            try:
                loop.call_soon_threadsafe(chunks.put_nowait, chunk)
            except RuntimeError:
                # The interaction's loop is gone; nobody is listening.
                cancelled.set()

        def produce() -> None:
            try:
                with self._model_swap_lock:
                    # ``frames_after_eos=None`` lets pocket-tts pick the
                    # trailing frames from the text length.
                    for tensor in self._speech_stream(voice_state, text):
                        if cancelled.is_set():
                            break
                        if tensor.is_cuda:
                            tensor = tensor.cpu()
                        pcm = (tensor * 32767).clamp(-32768, 32767).to(torch.int16)
                        hand_over(pcm.numpy().tobytes())
            except Exception as e:
                self.printr.print(
                    f"PocketTTS stream error: {e}", color=LogType.ERROR, server_only=True
                )
            finally:
                hand_over(None)

        pending = bytearray()
        finished = False

        async def buffer_callback(out_buffer: bytearray) -> int:
            nonlocal finished
            while not pending and not finished:
                chunk = await chunks.get()
                if chunk is None:
                    finished = True
                else:
                    pending.extend(chunk)
            written = min(len(out_buffer), len(pending))
            out_buffer[:written] = pending[:written]
            del pending[:written]
            return written

        threading.Thread(target=produce, daemon=True).start()
        try:
            await audio_player.stream_with_effects(
                buffer_callback=buffer_callback,
                config=sound_config,
                wingman_name=wingman_name,
                sample_rate=sample_rate,
                dtype="int16",
                channels=1,
                use_gain_boost=True,
                prebuffer_ms=self._STREAM_PREBUFFER_MS,
            )
        finally:
            # Stopped playback: let the thread end after its current chunk.
            cancelled.set()

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



@tts_provider(TtsProvider.POCKET_TTS)
class PocketTtsTts(TtsInterface):
    """Per-wingman adapter around the shared PocketTTS singleton."""

    def __init__(self, shared: "PocketTTS", config: "WingmanConfig"):
        self._shared = shared
        self._config = config

    async def play_audio(self, text, sound_config, audio_player, wingman_name):
        await self._shared.play_audio(
            text=text,
            config=self._config.pocket_tts,
            sound_config=sound_config,
            audio_player=audio_player,
            wingman_name=wingman_name,
        )
