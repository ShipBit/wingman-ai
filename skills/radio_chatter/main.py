import json
import re
import time
import copy
from os import path
import random
from typing import TYPE_CHECKING
from api.interface import (
    SettingsConfig,
    SkillConfig,
    VoiceSelection,
    WingmanInitializationError,
)
from api.enums import (
    LogType,
    WingmanInitializationErrorType,
    TtsProvider,
    WingmanProTtsProvider,
    SoundEffect,
)
from services.file import get_prompt
from skills.skill_base import Skill, command_action, tool

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext


class RadioChatter(Skill):

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "WingmanContext",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

        self.file_path = path.join(self.get_generated_files_dir(), "data")

        self.last_message = None
        self.radio_status = False
        self.loaded = False
        # Bumped on every start/stop so an older chatter loop notices it was replaced
        self.run_id = 0

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        # Validate properties (don't cache values)
        self.retrieve_custom_property_value("prompt", errors)
        self.retrieve_custom_property_value("force_radio_sound", errors)
        self.retrieve_custom_property_value("auto_start", errors)
        self.retrieve_custom_property_value("print_chatter", errors)
        # self.retrieve_custom_property_value("radio_knowledge", errors)
        self.retrieve_custom_property_value("radio_sounds", errors)
        self.retrieve_custom_property_value("use_beeps", errors)

        # Validate range sliders
        interval_range = self.retrieve_custom_property_value("interval_range", errors)
        if interval_range and isinstance(interval_range, list) and len(interval_range) == 2:
            if interval_range[0] < 1 or interval_range[1] < interval_range[0]:
                errors.append(
                    WingmanInitializationError(
                        wingman_name=self.wingman.name,
                        message="Invalid interval range. Min must be >= 1 and max must be >= min.",
                        error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                    )
                )

        messages_range = self.retrieve_custom_property_value("messages_range", errors)
        if messages_range and isinstance(messages_range, list) and len(messages_range) == 2:
            if messages_range[0] < 1 or messages_range[1] < messages_range[0]:
                errors.append(
                    WingmanInitializationError(
                        wingman_name=self.wingman.name,
                        message="Invalid messages range. Min must be >= 1 and max must be >= min.",
                        error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                    )
                )

        participants_range = self.retrieve_custom_property_value("participants_range", errors)
        participants_max = None
        if participants_range and isinstance(participants_range, list) and len(participants_range) == 2:
            participants_max = int(participants_range[1])
            if participants_range[0] < 1 or participants_range[1] < participants_range[0]:
                errors.append(
                    WingmanInitializationError(
                        wingman_name=self.wingman.name,
                        message="Invalid participants range. Min must be >= 1 and max must be >= min.",
                        error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                    )
                )

        # Validate volume
        volume = self.retrieve_custom_property_value("volume", errors) or 0.5
        if volume < 0 or volume > 1:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Invalid value for 'volume'. Expected a number between 0 and 1.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )

        # Initialize providers for configured voices
        voices: list[VoiceSelection] = self.retrieve_custom_property_value(
            "voices", errors
        )
        if voices:
            # Check participants vs voices
            if participants_max and participants_max > len(voices):
                errors.append(
                    WingmanInitializationError(
                        wingman_name=self.wingman.name,
                        message="Not enough voices available for the configured number of max participants.",
                        error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                    )
                )

            # Provider initialization is handled at voice-switch time via tts.set_voice().

        return errors

    def _get_voices(self) -> list[VoiceSelection]:
        """Retrieve fresh voices list at runtime."""
        errors: list[WingmanInitializationError] = []
        voices = self.retrieve_custom_property_value("voices", errors)
        return voices if voices else []

    def _get_prompt(self) -> str | None:
        """Retrieve fresh prompt at runtime."""
        errors: list[WingmanInitializationError] = []
        return self.retrieve_custom_property_value("prompt", errors)

    def _get_range(self, prop_id: str, defaults: tuple[int, int]) -> tuple[int, int]:
        errors: list[WingmanInitializationError] = []
        val = self.retrieve_custom_property_value(prop_id, errors)
        if val and isinstance(val, list) and len(val) == 2:
            return (int(val[0]), int(val[1]))
        return defaults

    def _get_interval_min(self) -> int:
        return self._get_range("interval_range", (60, 600))[0]

    def _get_interval_max(self) -> int:
        return self._get_range("interval_range", (60, 600))[1]

    def _get_messages_min(self) -> int:
        return self._get_range("messages_range", (1, 5))[0]

    def _get_messages_max(self) -> int:
        return self._get_range("messages_range", (1, 5))[1]

    def _get_participants_min(self) -> int:
        return self._get_range("participants_range", (2, 3))[0]

    def _get_participants_max(self) -> int:
        return self._get_range("participants_range", (2, 3))[1]

    def _get_volume(self) -> float:
        """Retrieve fresh volume at runtime."""
        errors: list[WingmanInitializationError] = []
        volume = self.retrieve_custom_property_value("volume", errors)
        return volume if volume else 0.5

    def _get_radio_sounds(self) -> list[SoundEffect]:
        """Retrieve fresh radio sounds at runtime."""
        errors: list[WingmanInitializationError] = []
        radio_sounds = self.retrieve_custom_property_value("radio_sounds", errors)
        sounds = []
        if radio_sounds:
            radio_sounds = radio_sounds.lower().replace(" ", "").split(",")
            if "low" in radio_sounds:
                sounds.append(SoundEffect.LOW_QUALITY_RADIO)
            if "medium" in radio_sounds:
                sounds.append(SoundEffect.MEDIUM_QUALITY_RADIO)
            if "high" in radio_sounds:
                sounds.append(SoundEffect.HIGH_END_RADIO)
        return sounds

    def _get_force_radio_sound(self) -> bool:
        """Retrieve fresh force_radio_sound at runtime."""
        errors: list[WingmanInitializationError] = []
        return self.retrieve_custom_property_value("force_radio_sound", errors) or False

    def _get_use_beeps(self) -> bool:
        """Retrieve fresh use_beeps at runtime."""
        errors: list[WingmanInitializationError] = []
        return self.retrieve_custom_property_value("use_beeps", errors) or False

    def _get_print_chatter(self) -> bool:
        """Retrieve fresh print_chatter at runtime."""
        errors: list[WingmanInitializationError] = []
        return self.retrieve_custom_property_value("print_chatter", errors) or False

    def _get_radio_knowledge(self) -> bool:
        """Retrieve fresh radio_knowledge at runtime."""
        return False  # disabled for now

    def _get_auto_start(self) -> bool:
        """Retrieve fresh auto_start at runtime."""
        errors: list[WingmanInitializationError] = []
        return self.retrieve_custom_property_value("auto_start", errors) or False

    async def prepare(self) -> None:
        await super().prepare()
        self.loaded = True
        if self._get_auto_start() and not self.radio_status:
            self._start_chatter()

    async def unload(self) -> None:
        await super().unload()
        self.loaded = False
        self.radio_status = False
        self.run_id += 1

    def _start_chatter(self) -> None:
        """Mark the radio as on right away and start a loop owning this run id."""
        self.radio_status = True
        self.run_id += 1
        self.wingman.run_in_thread(self._init_chatter, self.run_id)

    def randint(self, start: int, stop: int) -> int:
        """Random number from start to stop, both inclusive."""
        if stop <= start:
            return start
        return random.randint(start, stop)

    @tool(
        name="turn_on_radio",
        description="Turn the radio on to pick up ambient chatter on open frequencies. Creates immersive background radio communication. Use when user wants radio ambience or communication atmosphere.",
    )
    @command_action(
        label="Turn radio on",
        description="Start ambient radio chatter on open frequencies.",
        respond="speak",
    )
    def turn_on_radio(self) -> str:
        """Turn the radio on."""
        if self.radio_status:
            return "Radio is already on."
        else:
            self._start_chatter()
            return "Radio is now on."

    @tool(
        name="turn_off_radio",
        description="Turn the radio off to stop ambient chatter. Use when user wants silence or to disable radio communication sounds.",
    )
    @command_action(
        label="Turn radio off",
        description="Stop ambient radio chatter.",
        respond="speak",
    )
    def turn_off_radio(self) -> str:
        """Turn the radio off."""
        if self.radio_status:
            self.radio_status = False
            self.run_id += 1
            return "Radio is now off."
        else:
            return "Radio is already off."

    @tool(name="radio_status", description="Get the status (on/off) of the radio.")
    @command_action(
        label="Radio status",
        description="Speak whether the radio is currently on or off.",
        respond="speak",
    )
    def get_radio_status(self) -> str:
        """Get the current radio status."""
        if self.radio_status:
            return "Radio is on."
        else:
            return "Radio is off."

    async def _speak(self, text: str, sound_config=None) -> None:
        """Async helper for threaded TTS with interrupt=False and optional sound_config."""
        await self.wingman.tts.speak(text, interrupt=False, sound_config=sound_config)

    async def _init_chatter(self, run_id: int) -> None:
        """Start the radio chatter."""
        interval_min = self._get_interval_min()
        time.sleep(max(5, interval_min))  # sleep for min 5s else min interval

        try:
            while self.is_active(run_id):
                try:
                    await self._generate_chatter(run_id)
                except Exception as e:
                    self.log.error(f"Radio chatter failed: {e}", server_only=True)
                interval_min = self._get_interval_min()
                interval_max = self._get_interval_max()
                interval = self.randint(interval_min, interval_max)
                time.sleep(max(1, interval))
        finally:
            # Only the newest loop may reset the flag
            if run_id == self.run_id:
                self.radio_status = False

    def is_active(self, run_id: int | None = None) -> bool:
        if run_id is not None and run_id != self.run_id:
            return False
        return self.radio_status and self.loaded

    async def _generate_chatter(self, run_id: int):
        if not self.is_active(run_id):
            return

        messages_min = self._get_messages_min()
        messages_max = self._get_messages_max()
        participants_min = self._get_participants_min()
        participants_max = self._get_participants_max()
        prompt = self._get_prompt()
        if not prompt or not prompt.strip():
            prompt = "Generate a dialog between random radio operators."

        count_message = self.randint(messages_min, messages_max)
        count_participants = self.randint(participants_min, participants_max)

        system = get_prompt("radio-chatter").format(
            count_participants=count_participants,
            count_messages=count_message,
            language=self.wingman.language.name,
        )
        # auto_shorten so a large radio prompt is truncated to the cap rather than
        # raising (which, in this background thread, would silently kill the loop).
        messages = await self.wingman.ai.generate(
            prompt, system=system, auto_shorten=True
        )

        if not messages:
            return

        clean_messages = []
        voice_participant_mapping = {}
        try:
            messages = messages.strip()
            if messages.startswith("```"):
                messages = re.sub(r"^```(?:json)?\s*|\s*```$", "", messages).strip()
            messages = json.loads(messages)
        except json.JSONDecodeError as e:
            self.log.error(
                f"Radio chatter message generation failed due to invalid JSON: {str(e)}"
            )
            return

        if not isinstance(messages, list):
            self.log.error(f"Radio chatter message generation returned no list: {messages}")
            return

        for message in messages:
            if not message:
                continue

            if (
                not isinstance(message, dict)
                or "user" not in message
                or "content" not in message
            ):
                self.log.error(
                    f"Radio chatter message generation failed due to invalid JSON format: {messages}"
                )
                return

            if message["user"] not in voice_participant_mapping:
                voice_participant_mapping[message["user"]] = None

            clean_messages.append(message)

        voices = self._get_voices()
        if not voices:
            return

        original_voice_setting = await self._get_original_voice_setting()
        elevenlabs_streaming = self.wingman.config.elevenlabs.output_streaming
        inworld_streaming = self.wingman.config.inworld.output_streaming
        pocket_tts_streaming = self.wingman.config.pocket_tts.output_streaming
        openai_compatible_streaming = (
            self.wingman.config.openai_compatible_tts.output_streaming
        )
        original_sound_config = copy.deepcopy(self.wingman.config.sound)

        # copy for volume and effects
        volume = self._get_volume()
        use_beeps = self._get_use_beeps()
        custom_sound_config = copy.deepcopy(self.wingman.config.sound)
        custom_sound_config.play_beep = use_beeps
        custom_sound_config.play_beep_apollo = False
        custom_sound_config.volume = custom_sound_config.volume * volume

        voice_index = await self._get_random_voice_index(
            len(voice_participant_mapping), voices
        )
        if not voice_index:
            return

        force_radio_sound = self._get_force_radio_sound()
        radio_sounds = self._get_radio_sounds()
        for i, name in enumerate(voice_participant_mapping):
            sound_config = original_sound_config
            if force_radio_sound and radio_sounds:
                sound_config = copy.deepcopy(custom_sound_config)
                sound_config.effects = [random.choice(radio_sounds)]

            voice_participant_mapping[name] = (voice_index[i], sound_config)

        for message in clean_messages:
            name = message["user"]
            text = message["content"]

            if not self.is_active(run_id):
                return

            # wait for audio_player idling
            while self.wingman.audio.is_playing and self.is_active(run_id):
                time.sleep(2)

            if not self.is_active(run_id):
                return

            voice_index, sound_config = voice_participant_mapping[name]
            voice_setting = voices[voice_index]

            await self._switch_voice(voice_setting)
            if self._get_print_chatter():
                await self.printr.print_async(
                    text=f"Background radio ({name}): {text}",
                    color=LogType.INFO,
                    source_name=self.wingman.name,
                )
            self.wingman.run_in_thread(self._speak, text, sound_config)
            if self._get_radio_knowledge():
                await self.wingman.conversation.add_assistant(
                    f"Background radio chatter: {text}"
                )
            max_wait = 10
            while not self.wingman.audio.is_playing and max_wait > 0:
                time.sleep(0.1)
                max_wait -= 0.1
            await self._switch_voice(
                original_voice_setting,
                elevenlabs_streaming,
                inworld_streaming,
                pocket_tts_streaming,
                openai_compatible_streaming,
            )

        while self.wingman.audio.is_playing:
            time.sleep(1)  # stay in function call until last message got played

    async def _get_random_voice_index(
        self, count: int, voices: list[VoiceSelection]
    ) -> list[int]:
        """Switch voice to a random voice from the list."""

        if count > len(voices):
            return []

        if count == len(voices):
            return list(range(len(voices)))

        voice_index = []
        for _ in range(count):
            while True:
                index = random.randrange(len(voices))
                if index not in voice_index:
                    voice_index.append(index)
                    break

        return voice_index

    async def _switch_voice(
        self,
        voice_setting: VoiceSelection = None,
        elevenlabs_streaming: bool = False,
        inworld_streaming: bool = False,
        pocket_tts_streaming: bool = False,
        openai_compatible_streaming: bool = False,
    ) -> None:
        """Switch voice to the given voice setting."""

        if not voice_setting:
            return

        # Cross-provider switching was removed: we can only set a voice that belongs to
        # the wingman's CURRENT TTS provider. Voices for other providers are skipped
        # (that participant just keeps the current voice) — chatter still plays.
        current_provider = self.wingman.config.features.tts_provider
        if voice_setting.provider != current_provider:
            if self.settings.debug_mode:
                self.log.info(
                    f"Radio: skipping voice for {getattr(voice_setting.provider, 'value', voice_setting.provider)} "
                    f"(current provider is {getattr(current_provider, 'value', current_provider)})",
                    server_only=True,
                )
            return

        if self.settings.debug_mode:
            self.log.info(
                f"Switching radio voice ({getattr(current_provider, 'value', current_provider)})",
                server_only=True,
            )

        await self.wingman.tts.set_voice(voice_setting.voice)

    async def _get_original_voice_setting(self) -> None|VoiceSelection:
        voice_provider = self.wingman.config.features.tts_provider
        voice_subprovider = None
        voice = None

        if voice_provider == TtsProvider.EDGE_TTS:
            voice = self.wingman.config.edge_tts.voice
        elif voice_provider == TtsProvider.ELEVENLABS:
            voice = self.wingman.config.elevenlabs.voice
        elif voice_provider == TtsProvider.XVASYNTH:
            voice = self.wingman.config.xvasynth.voice
        elif voice_provider == TtsProvider.OPENAI:
            voice = self.wingman.config.openai.tts_voice
        elif voice_provider == TtsProvider.WINGMAN_PRO:
            voice_subprovider = self.wingman.config.wingman_pro.tts_provider
            if voice_subprovider == WingmanProTtsProvider.AZURE:
                voice = self.wingman.config.wingman_pro.azure.voice
            else:
                voice = self.wingman.config.inworld.voice_id
        elif voice_provider == TtsProvider.INWORLD:
            voice = self.wingman.config.inworld.voice_id
        elif voice_provider == TtsProvider.POCKET_TTS:
            voice = self.wingman.config.pocket_tts.voice
        elif voice_provider == TtsProvider.OPENAI_COMPATIBLE:
            voice = self.wingman.config.openai_compatible_tts.voice
        else:
            return None

        return VoiceSelection(
            provider=voice_provider, subprovider=voice_subprovider, voice=voice
        )
