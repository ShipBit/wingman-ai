from copy import deepcopy
from os import path
from typing import Awaitable, Callable, Optional
from fastapi import APIRouter
import sounddevice as sd
from api.enums import LogType, SttProvider, ToastType
from api.interface import (
    AudioSettings,
    AudioDeviceSettings,
    SettingsConfig,
)
from providers.parakeet import Parakeet
from providers.xvasynth import XVASynth
from providers.pocket_tts import PocketTTS
from services.config_manager import ConfigManager
from services.local_ai_service import LocalAiService
from services.config_service import ConfigService
from services.printr import Printr
from services.pub_sub import PubSub


SPOKEN_TO_POCKET_TTS = {
    "en": "english_2026-04",
    "de": "german",
    # French has no 6-layer model in pocket-tts v2 — 24l is the only variant.
    "fr": "french_24l",
    "es": "spanish",
    "it": "italian",
    "pt": "portuguese",
}


class SettingsService:
    def __init__(self, config_manager: ConfigManager, config_service: ConfigService):
        self.printr = Printr()
        self.config_manager = config_manager
        self.config_service = config_service
        self.converted_audio_settings = False
        self.get_settings()
        self.settings_events = PubSub()
        self.parakeet: Parakeet = None
        self.xvasynth: XVASynth = None
        self.pocket_tts: PocketTTS = None
        self.local_ai_service: LocalAiService = None
        # Injected by WingmanCore to surface STT download/init progress via
        # the shared LOADING_CONFIG indicator during runtime settings changes.
        # ``stt_status_callback`` broadcasts per-step progress, ``stt_done_callback``
        # flips the state back to READY once the switch finishes.
        self.stt_status_callback: Optional[
            Callable[[str, Optional[float]], Awaitable[None]]
        ] = None
        self.stt_done_callback: Optional[Callable[[], Awaitable[None]]] = None
        # Injected by WingmanCore. The settings page holds the stt block it
        # loaded and posts all of it back on the next change, so a word added
        # by a wingman tool has to reach an open page or it is written away.
        self.vocabulary_changed_callback: Optional[Callable[[list[str]], None]] = None

        self.router = APIRouter()
        tags = ["settings"]

        self.router.add_api_route(
            methods=["GET"],
            path="/settings",
            endpoint=self.get_settings,
            response_model=SettingsConfig,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings",
            endpoint=self.save_settings,
            tags=tags,
        )
        self.router.add_api_route(
            methods=["POST"],
            path="/settings/audio-devices",
            endpoint=self.set_audio_devices,
            tags=tags,
        )

    def initialize(
        self,
        parakeet: Parakeet,
        xvasynth: XVASynth,
        pocket_tts: PocketTTS,
        local_ai_service: LocalAiService = None,
        stt_provider_manager=None,
    ):
        self.parakeet = parakeet
        self.xvasynth = xvasynth
        self.pocket_tts = pocket_tts
        self.local_ai_service = local_ai_service
        self.stt_provider_manager = stt_provider_manager

    # --- speech vocabulary ---

    def add_vocabulary(self, entries: list[str]) -> list[str]:
        """Add entries ("Hurston" or "Houston=Hurston"), persist, return what
        was new. Used by the wingman tools and the skill facade."""
        from services.audio.vocabulary import format_entry, parse_entry

        current = list(self.settings.stt.vocabulary or [])
        known = {e.lower() for e in current}
        added: list[str] = []
        for raw in entries:
            correct, heard = parse_entry(raw)
            entry = format_entry(correct, heard)
            if len(correct) < 3 or entry.lower() in known:
                continue
            current.append(entry)
            known.add(entry.lower())
            added.append(entry)
        if added:
            self.settings.stt.vocabulary = current
            self.config_manager.save_settings_config()
            self.printr.print(
                f"Speech vocabulary: added {', '.join(added)}", server_only=True, color=LogType.INFO
            )
            self._announce_vocabulary()
        return added

    def seed_vocabulary(self) -> list[str]:
        """Put the names people say every day into the list, once: every
        wingman of every configuration, and the signed-in user. Runs at start
        and after login; the list dedupes, so a second run adds nothing."""
        names: list[str] = []
        for config_dir in self.config_manager.get_config_dirs():
            if getattr(config_dir, "is_deleted", False):
                continue
            for wingman_file in self.config_manager.get_wingmen_configs(config_dir):
                if getattr(wingman_file, "is_deleted", False):
                    continue
                raw = self.config_manager.read_config(
                    path.join(self.config_manager.config_dir, config_dir.directory, wingman_file.file)
                )
                name = (raw or {}).get("name") or wingman_file.name
                if name:
                    names.append(str(name))
        if self.settings.user_name:
            names.append(self.settings.user_name)
        return self.add_vocabulary(names)

    def remove_vocabulary(self, words: list[str]) -> int:
        """Drop every entry whose correct spelling or heard form matches."""
        from services.audio.vocabulary import parse_entry

        drop = {" ".join(w.split()).lower() for w in words if w}
        current = list(self.settings.stt.vocabulary or [])
        kept = [
            e for e in current
            if parse_entry(e)[0].lower() not in drop
            and (parse_entry(e)[1] or "").lower() not in drop
            and e.lower() not in drop
        ]
        removed = len(current) - len(kept)
        if removed:
            self.settings.stt.vocabulary = kept
            self.config_manager.save_settings_config()
            self.printr.print(
                f"Speech vocabulary: removed {removed} entries", server_only=True, color=LogType.INFO
            )
            self._announce_vocabulary()
        return removed

    def _announce_vocabulary(self) -> None:
        """Tell an open settings page what the list looks like now."""
        if self.vocabulary_changed_callback:
            self.vocabulary_changed_callback(list(self.settings.stt.vocabulary or []))

    @property
    def settings(self):
        """Always the object the config manager holds. Migration at start
        replaces that object; a reference taken before it would write into
        a settings copy that is never saved."""
        return self.config_manager.settings_config

    # GET /settings
    def get_settings(self):
        config = self.config_manager.settings_config
        config.audio = self._get_audio_settings_indexed(
            not self.converted_audio_settings
        )
        self.converted_audio_settings = True
        return config

    # POST /settings
    async def save_settings(self, settings: SettingsConfig):
        old = deepcopy(self.config_manager.settings_config)

        # Speech-to-text. One block for every wingman and both ways of talking.
        old_stt = old.stt
        new_stt = settings.stt
        # The edits to a bundled hotword list are written by their own
        # endpoint. The settings page holds the block it loaded, so taking its
        # copy here would throw away every edit made since - keep ours.
        new_stt.preset_overrides = old_stt.preset_overrides
        # The shared providers hold a reference to their settings object;
        # hand them the new one before anything reads it.
        self.parakeet.settings = new_stt.parakeet
        self.config_manager.settings_config.stt = new_stt

        reload_needed = new_stt.provider != old_stt.provider
        if new_stt.provider == SttProvider.PARAKEET:
            old_pk, new_pk = old_stt.parakeet, new_stt.parakeet
            reload_needed = reload_needed or (
                old_pk.model_variant != new_pk.model_variant
                or old_pk.execution_provider != new_pk.execution_provider
                or old_pk.run_locally != new_pk.run_locally
            )
        if reload_needed and self.stt_provider_manager:
            # Let the manager unload the old model and download/load the new one.
            try:
                await self.stt_provider_manager.switch_provider(
                    new_stt.provider, on_status=self.stt_status_callback
                )
            finally:
                if self.stt_done_callback:
                    await self.stt_done_callback()
            self.printr.print(
                f"Speech-to-text provider: {new_stt.provider.value}.",
                server_only=True,
            )

        # audio devices
        if (
            (settings.audio is not None and old.audio is None)
            or (settings.audio is None and old.audio is not None)
            or (
                settings.audio is not None
                and old.audio is not None
                and (
                    settings.audio.input != old.audio.input
                    or settings.audio.output != old.audio.output
                )
            )
        ):
            await self.set_audio_devices(settings.audio.input, settings.audio.output)

        # XVASynth
        if not self.xvasynth:
            self.printr.toast_error(
                "XVASynth is not initialized. Please run SettingsService.initialize()",
            )
            return
        self.xvasynth.update_settings(settings=settings.xvasynth)
        self.config_manager.settings_config.xvasynth = settings.xvasynth

        # PocketTTS
        if not self.pocket_tts:
            self.printr.toast_error(
                "PocketTTS is not initialized. Please run SettingsService.initialize()",
            )
            return
        self.pocket_tts.update_settings(settings=settings.pocket_tts)
        self.config_manager.settings_config.pocket_tts = settings.pocket_tts

        # Spoken language cascade
        old_spoken = old.spoken_language
        new_spoken = settings.spoken_language
        if new_spoken != old_spoken:
            self.config_manager.settings_config.spoken_language = new_spoken

            # Cascade to PocketTTS model language
            pocket_lang = SPOKEN_TO_POCKET_TTS.get(new_spoken, "english_2026-04")
            if settings.pocket_tts.model != pocket_lang:
                settings.pocket_tts.model = pocket_lang
                self.config_manager.settings_config.pocket_tts.model = pocket_lang
                self.pocket_tts.update_settings(settings=settings.pocket_tts)

            # Cascade to the STT language
            stt_lang = None if new_spoken == "multilingual" else new_spoken
            settings.stt.parakeet.language = stt_lang

            self.printr.print(
                f"Spoken language changed to '{new_spoken}'. "
                f"PocketTTS: {pocket_lang}, STT: {stt_lang or 'auto-detect'}",
                server_only=True,
                color=LogType.INFO,
            )
        else:
            self.config_manager.settings_config.spoken_language = new_spoken

        # Local AI (llama.cpp)
        if self.local_ai_service:
            await self.local_ai_service.update_settings_async(settings.llama_cpp)
            self.config_manager.settings_config.llama_cpp = settings.llama_cpp

        # voice activation
        self.config_manager.settings_config.voice_activation = settings.voice_activation

        if settings.voice_activation.enabled != old.voice_activation.enabled:
            await self.settings_events.publish(
                "voice_activation_changed", settings.voice_activation.enabled
            )
            self.printr.print(
                f"Voice activation {'enabled' if settings.voice_activation.enabled else 'disabled'}.",
                server_only=True,
            )

        new_va, old_va = settings.voice_activation, old.voice_activation
        if any(
            getattr(new_va, field) != getattr(old_va, field)
            for field in (
                "sensitivity", "end_pause_ms", "max_utterance_s", "min_speech_ms",
                "pre_roll_ms", "listen_while_speaking", "stop_words",
            )
        ):
            await self.settings_events.publish(
                "va_settings_changed", settings.voice_activation
            )
            self.printr.print("Voice Activation settings changed.", server_only=True)

        # rest
        self.config_manager.settings_config.wingman_pro = settings.wingman_pro
        if self.local_ai_service:
            # The cloud support model talks to whatever base_url this holds.
            self.local_ai_service.update_subscription(settings.wingman_pro)
        self.config_manager.settings_config.debug_mode = settings.debug_mode
        self.config_manager.settings_config.streamer_mode = settings.streamer_mode

        # cancel TTS ("shut up") bindings
        self.config_manager.settings_config.cancel_tts_key = settings.cancel_tts_key
        self.config_manager.settings_config.cancel_tts_key_codes = (
            settings.cancel_tts_key_codes
        )
        self.config_manager.settings_config.cancel_tts_joystick_button = (
            settings.cancel_tts_joystick_button
        )

        # HUD server
        self.config_manager.settings_config.hud_server = settings.hud_server
        if settings.hud_server != old.hud_server:
            await self.settings_events.publish(
                "hud_server_settings_changed", settings.hud_server
            )

        # save the config file
        self.config_manager.save_settings_config()

        # update running wingmen (tower is None while a config (re)loads or failed to load)
        if self.config_service.tower:
            for wingman in self.config_service.tower.wingmen:
                await wingman.update_settings(
                    settings=self.config_manager.settings_config
                )

    def save_settings_to_disk(self):
        """Persist current settings to disk without triggering provider updates."""
        self.config_manager.save_settings_config()

    async def set_audio_devices(
        self, input_device: Optional[int] = None, output_device: Optional[int] = None
    ):
        input_settings = None
        output_settings = None

        if input_device is not None:
            # get name and hostapi with id
            device = sd.query_devices(input_device)
            input_settings = AudioDeviceSettings(
                name=device["name"],
                hostapi=device["hostapi"],
            )

        if output_device is not None:
            # get name and hostapi with id
            device = sd.query_devices(output_device)
            output_settings = AudioDeviceSettings(
                name=device["name"],
                hostapi=device["hostapi"],
            )

        self.config_manager.settings_config.audio = AudioSettings(
            input=input_settings,
            output=output_settings,
        )

        await self.settings_events.publish(
            "audio_devices_changed", (input_device, output_device)
        )
        self.printr.print("Audio devices changed.", server_only=True)

    def _get_audio_settings_indexed(self, write: bool = True) -> AudioSettings:
        input_device = None
        output_device = None
        if self.config_manager.settings_config.audio:
            input_settings_orig = input_settings = (
                self.config_manager.settings_config.audio.input
            )
            output_settings_orig = output_settings = (
                self.config_manager.settings_config.audio.output
            )

            # check input
            if input_settings is not None:
                input_name = None
                input_hostapi = None

                if isinstance(input_settings, int):
                    # if integer - check if audio device exists
                    if input_settings < len(sd.query_devices()):
                        input_device = input_settings
                        device = sd.query_devices(input_settings)
                        if not device["max_input_channels"]:
                            if write:
                                self.printr.print(
                                    "Configured input device is not an input device. Using default.",
                                    toast=ToastType.NORMAL,
                                    color=LogType.WARNING,
                                    server_only=True,
                                )
                            input_device = None
                        else:
                            input_name = sd.query_devices()[input_settings]["name"]
                            input_hostapi = sd.query_devices()[input_settings][
                                "hostapi"
                            ]
                            input_settings = AudioDeviceSettings(
                                name=input_name, hostapi=input_hostapi
                            )
                            if write:
                                self.printr.print(
                                    f"Using input device '{input_name}'.",
                                    color=LogType.INFO,
                                    server_only=True,
                                )
                    else:
                        if write:
                            self.printr.print(
                                "Configured input device not found. Using default.",
                                toast=ToastType.NORMAL,
                                color=LogType.WARNING,
                                server_only=True,
                            )
                        input_device = None
                elif isinstance(input_settings, AudioDeviceSettings):
                    # get id with name and hostapi
                    for device in sd.query_devices():
                        if (
                            device["max_input_channels"] > 0
                            and device["name"] == input_settings.name
                            and device["hostapi"] == input_settings.hostapi
                        ):
                            if write:
                                device_name = device["name"]
                                self.printr.print(
                                    f"Using input device '{device_name}'.",
                                    color=LogType.INFO,
                                    server_only=True,
                                )
                            input_device = device["index"]
                            break
                    if input_device is None:
                        if write:
                            self.printr.print(
                                f"Configured input device '{input_settings.name}' not found. Using default.",
                                toast=ToastType.NORMAL,
                                color=LogType.WARNING,
                                server_only=True,
                            )
            elif write:
                self.printr.print(
                    "No input device set. Using default.",
                    color=LogType.INFO,
                    server_only=True,
                )

            # check output
            if output_settings is not None:
                output_name = None
                output_hostapi = None

                if isinstance(output_settings, int):
                    # if integer - check if audio device exists
                    if output_settings < len(sd.query_devices()):
                        output_device = output_settings
                        device = sd.query_devices(output_settings)
                        if not device["max_output_channels"]:
                            if write:
                                self.printr.print(
                                    "Configured output device is not an output device. Using default.",
                                    toast=ToastType.NORMAL,
                                    color=LogType.WARNING,
                                    server_only=True,
                                )
                            output_device = None
                        else:
                            output_name = sd.query_devices()[output_settings]["name"]
                            output_hostapi = sd.query_devices()[output_settings][
                                "hostapi"
                            ]
                            output_settings = AudioDeviceSettings(
                                name=output_name, hostapi=output_hostapi
                            )
                            if write:
                                self.printr.print(
                                    f"Using output device '{output_name}'.",
                                    color=LogType.INFO,
                                    server_only=True,
                                )
                    else:
                        if write:
                            self.printr.print(
                                "Configured output device not found. Using default.",
                                toast=ToastType.NORMAL,
                                color=LogType.WARNING,
                                server_only=True,
                            )
                        output_device = None
                # check if instance of AudioDeviceSettings
                elif isinstance(output_settings, AudioDeviceSettings):
                    # get id with name and hostapi
                    for device in sd.query_devices():
                        if (
                            device["max_output_channels"] > 0
                            and device["name"] == output_settings.name
                            and device["hostapi"] == output_settings.hostapi
                        ):
                            if write:
                                device_name = device["name"]
                                self.printr.print(
                                    f"Using output device '{device_name}'.",
                                    color=LogType.INFO,
                                    server_only=True,
                                )
                            output_device = device["index"]
                            break
                    if output_device is None:
                        if write:
                            self.printr.print(
                                f"Configured audio output device '{output_settings.name}' not found. Using default.",
                                toast=ToastType.NORMAL,
                                color=LogType.WARNING,
                                server_only=True,
                            )
            elif write:
                self.printr.print(
                    "No output device set. Using default.",
                    color=LogType.INFO,
                    server_only=True,
                )

            # overwrite settings with new structure, if needed
            if write and (
                input_settings_orig != input_settings
                or output_settings_orig != output_settings
            ):
                self.config_manager.settings_config.audio = AudioSettings(
                    input=input_settings, output=output_settings
                )
                self.config_manager.save_settings_config()
                self.printr.print("Audio settings updated.", server_only=True)
        return AudioSettings(input=input_device, output=output_device)
