import os
import io
import glob
import asyncio
import threading
from collections import OrderedDict
from typing import TYPE_CHECKING, Callable, Optional

import torch
import torchaudio
from pocket_tts import TTSModel
from pocket_tts.models.tts_model import export_model_state
from api.enums import LogType, TtsProvider
from api.interface import (
    PocketTTSConfig,
    SoundConfig,
    PocketTTSSettings,
    WingmanInitializationError,
    VoiceInfo,
)
from providers.interfaces import TtsInterface, tts_provider
from providers.pocket_tts_r2 import (
    build_r2_config,
    prefetch_gated_weights,
    use_r2_mirror,
)
from services.file import get_custom_voices_dir, get_pocket_tts_models_dir
from services.audio_player import AudioPlayer
from services.printr import Printr
from providers.open_ai import OpenAiCompatibleTts

if TYPE_CHECKING:
    from api.interface import WingmanConfig



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

# Legacy model IDs that should be silently upgraded to the canonical ID.
LEGACY_MODEL_ALIASES = {
    "english": "english_2026-04",
    "english_2026-01": "english_2026-04",
}


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
        defer_load: bool = False,
    ):
        if settings is None:
            settings = PocketTTSSettings(enable=False, host="localhost", port=5002)
        self.settings = settings
        self.printr = Printr()
        self.model: Optional[TTSModel] = None
        self.remote_client: Optional[OpenAiCompatibleTts] = None
        self.voices_dir = get_custom_voices_dir()
        self.models_dir = get_pocket_tts_models_dir()
        # LRU-bounded voice state cache — each entry is a dict of tensors and
        # can be tens of MB. Keep the most recent 32 voices (well over a
        # typical tower size) and drop the oldest on overflow.
        self.voice_cache: OrderedDict[str, dict] = OrderedDict()
        self._playback_buffer = bytearray()
        self._loading = False
        self.on_model_reloaded: Optional[Callable[[], None]] = None
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

    def update_settings(self, settings: PocketTTSSettings):
        old = self.settings
        self.settings = settings
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
                or old.model != settings.model
                or old.quantize != settings.quantize
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

    def _is_custom_model(self, model_id: str) -> bool:
        """Check if a model ID refers to a custom YAML file in the models dir."""
        return model_id.endswith(".yaml") or model_id.endswith(".yml")

    def load_model(self):
        """Load the PocketTTS model using v2.0 API."""
        self._loading = True
        try:
            model_id = self.settings.model or "english_2026-04"
            model_id = LEGACY_MODEL_ALIASES.get(model_id, model_id)

            # int8 quantization compounds error across layers; on 24L variants
            # it audibly degrades cloned voices. Force it off for 24L regardless
            # of the user's stored setting.
            quantize = self.settings.quantize
            if quantize and model_id.endswith("_24l"):
                self.printr.print(
                    f"PocketTTS: disabling quantization for 24L model '{model_id}' to avoid voice cloning artifacts.",
                    color=LogType.WARNING,
                    server_only=True,
                )
                quantize = False

            if self._is_custom_model(model_id):
                model_path = os.path.join(self.models_dir, model_id)
                self.printr.print(
                    f"Loading PocketTTS custom model: {model_path} (quantize={quantize})...",
                    color=LogType.INFO,
                    server_only=True,
                )
                self.model = TTSModel.load_model(
                    config=model_path, quantize=quantize
                )
            elif use_r2_mirror():
                # Redirect the gated voice-cloning weights to our R2 mirror so users
                # without an HF token can clone voices (see providers/pocket_tts_r2.py).
                config_path = build_r2_config(model_id, self.models_dir)
                self.printr.print(
                    f"Loading PocketTTS model: {model_id} from R2 mirror (quantize={quantize})...",
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
                    config=config_path,
                    quantize=quantize,
                )
            else:
                self.printr.print(
                    f"Loading PocketTTS model: {model_id} from HuggingFace (quantize={quantize})...",
                    color=LogType.INFO,
                    server_only=True,
                )
                self.model = TTSModel.load_model(
                    language=model_id,
                    quantize=quantize,
                )

            self.printr.print(
                "PocketTTS Model loaded.",
                color=LogType.POSITIVE,
                server_only=True,
            )
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

        self.printr.print(
            "PocketTTS Model unloaded.", color=LogType.INFO, server_only=True
        )

    def get_status(self) -> dict:
        """Return current PocketTTS status for the UI."""
        return {
            "is_loading": self._loading,
            "model_loaded": self.model is not None,
            "model": self.settings.model,
            "quantize": self.settings.quantize,
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
        # Remote mode — fetch from server
        if not self.settings.run_locally:
            if not self.remote_client:
                self._init_remote_client()
            if self.remote_client:
                return await self.remote_client.get_available_voices(
                    voices_endpoint="/voices"
                )
            return []

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
        # Custom voices
        for stem in self._list_voice_stems(self.voices_dir):
            voices.append(
                VoiceInfo(id=stem, name=f"Local: {stem}", provider="custom_voices")
            )

        return voices

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
        raw = self.settings.model or "english_2026-04"
        raw = LEGACY_MODEL_ALIASES.get(raw, raw)
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
          1. ``<id>.<active_model>.safetensors`` — model-specific cache (fastest)
          2. ``<id>.wav`` / ``.mp3`` / ``.flac`` — raw audio (will clone+cache)
          3. ``<id>.safetensors`` — legacy unlabeled cache
        """
        active_tag = self._active_model_tag()
        audio_exts = (".wav", ".mp3", ".flac")
        extension_order = (f".{active_tag}.safetensors", *audio_exts, ".safetensors")

        # Bare predefined names (e.g. "alba") are handled by pocket-tts itself
        # (downloaded + cached from HuggingFace on first use); we just pass them
        # through untouched.
        if self.voices_dir:
            base = os.path.join(self.voices_dir, voice_id_or_path)
            if os.path.exists(base):
                return os.path.abspath(base)
            for ext in extension_order:
                p = base + ext
                if os.path.exists(p):
                    return os.path.abspath(p)

        if os.path.exists(voice_id_or_path):
            return os.path.abspath(voice_id_or_path)

        return voice_id_or_path

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

        When ``audio_path`` is a bare predefined-voice name (no directory, no
        extension), pocket-tts resolves it internally from its HF-cached
        registry — we skip writing a disk cache because there's nowhere sensible
        to put it and pocket-tts already caches those.
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
            export_model_state(state, safetensors_path)
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

    # Predefined voice IDs that ship with the pocket-tts library (HF-cached).
    # No point preloading these — pocket-tts resolves them lazily on first use
    # and we can't write a local safetensors cache for bare predefined names.
    _BUILTIN_VOICE_IDS = frozenset(
        {"alba", "marius", "javert", "jean", "fantine", "cosette", "eponine", "azelma"}
    )

    def preload_voice_states(
        self,
        voice_ids: list[str],
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict[str, bool]:
        """Warm the voice-state cache for the given voice IDs.

        Only applies when running locally with a loaded model. Skips built-in
        pocket-tts voices (they're resolved from HF cache on first use anyway)
        so preloading only pays for cloned/custom voices.

        Returns a map of voice_id -> True/False indicating success.
        """
        results: dict[str, bool] = {}
        if not self.settings.run_locally or not self.model:
            return results

        # Dedupe and drop builtins while preserving order.
        seen: set[str] = set()
        unique_ids = [
            v
            for v in voice_ids
            if v
            and v not in self._BUILTIN_VOICE_IDS
            and not (v in seen or seen.add(v))
        ]
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

    def list_custom_voices_needing_precompute(self) -> list[str]:
        """Return custom voice stems whose tagged safetensor for the active
        model does NOT yet exist on disk — these are the ones that would
        actually be cloned by a precompute pass.

        Excludes built-in voices (pocket-tts resolves those from its HF cache).
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
                seen.add(stem)
                tagged = os.path.join(
                    self.voices_dir, f"{stem}.{active_tag}.safetensors"
                )
                if not os.path.exists(tagged):
                    needs.append(stem)
        return needs

    def precompute_custom_voices(
        self,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict:
        """Generate + persist `.<active_model>.safetensors` for every custom
        voice that doesn't yet have one. Built-in voices are skipped.

        Returns ``{"total": N, "succeeded": int, "failed": int}``.
        """
        if not self.settings.run_locally or not self.model:
            return {"total": 0, "succeeded": 0, "failed": 0}

        targets = self.list_custom_voices_needing_precompute()
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
            # .safetensors from a different model version — re-clone from raw audio.
            if resolved_key.endswith(".safetensors"):
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
                return self.model.generate_audio(voice_state, text)

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

    async def _stream_audio(
        self, text, voice_state, sound_config, audio_player, wingman_name
    ):
        """Stream generation.

        Holds ``_model_swap_lock`` across the whole playback so the settings-
        change reload thread waits for the stream to finish before swapping
        the model. Safe to hold across ``await`` because ``_async_gen_lock``
        already guarantees no other coroutine is entering this path
        concurrently, so nothing on the event-loop thread tries to acquire
        ``_model_swap_lock`` synchronously.
        """
        sample_rate = self.model.sample_rate
        self._model_swap_lock.acquire()
        try:
            # Initialize the stream generator. ``frames_after_eos=None`` lets pocket-tts
            # auto-pick 1-3 trailing frames based on text length.
            stream = self.model.generate_audio_stream(voice_state, text)
            iterator = iter(stream)
        except BaseException:
            # Anything that raises between acquire and the main try/finally below
            # must still release the lock, or future reloads deadlock.
            self._model_swap_lock.release()
            raise

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

        try:
            await audio_player.stream_with_effects(
                buffer_callback=buffer_callback,
                config=sound_config,
                wingman_name=wingman_name,
                sample_rate=sample_rate,
                dtype="int16",
                channels=1,
                use_gain_boost=True,
            )
        finally:
            self._model_swap_lock.release()

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
