import json
import time
import copy
from os import path
from random import randrange
from typing import TYPE_CHECKING
from api.interface import (
    SettingsConfig,
    SkillConfig,
    VoiceSelection,
    WingmanInitializationError,
    ElevenlabsVoiceConfig,
)
from api.enums import (
    LogType,
    WingmanInitializationErrorType,
    TtsProvider,
    WingmanProTtsProvider,
    SoundEffect,
)
from skills.skill_base import Skill, tool

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class RadioChatter(Skill):

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

        self.file_path = path.join(self.get_generated_files_dir(), "data")

        self.last_message = None
        self.radio_status = False
        self.loaded = False
        self._chatter_starting = False  # Track if chatter initialization is in progress

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        # Validate properties (don't cache values)
        self.retrieve_custom_property_value("prompt", errors)
        self.retrieve_custom_property_value("force_radio_sound", errors)
        self.retrieve_custom_property_value("auto_start", errors)
        self.retrieve_custom_property_value("print_chatter", errors)
        self.retrieve_custom_property_value("radio_knowledge", errors)
        self.retrieve_custom_property_value("radio_sounds", errors)
        self.retrieve_custom_property_value("use_beeps", errors)

        # Validate intervals
        interval_min = self.retrieve_custom_property_value("interval_min", errors)
        if interval_min is not None and interval_min < 1:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Invalid value for 'interval_min'. Expected a number of one or larger.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
        interval_max = self.retrieve_custom_property_value("interval_max", errors)
        if (
            interval_max is not None
            and interval_max < 1
            or (interval_min is not None and interval_max < interval_min)
        ):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Invalid value for 'interval_max'. Expected a number greater than or equal to 'interval_min'.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )

        # Validate messages
        messages_min = self.retrieve_custom_property_value("messages_min", errors)
        if messages_min is not None and messages_min < 1:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Invalid value for 'messages_min'. Expected a number of one or larger.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
        messages_max = self.retrieve_custom_property_value("messages_max", errors)
        if (
            messages_max is not None
            and messages_max < 1
            or (messages_min is not None and messages_max < messages_min)
        ):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Invalid value for 'messages_max'. Expected a number greater than or equal to 'messages_min'.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )

        # Validate participants
        participants_min = self.retrieve_custom_property_value(
            "participants_min", errors
        )
        if participants_min is not None and participants_min < 1:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Invalid value for 'participants_min'. Expected a number of one or larger.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
        participants_max = self.retrieve_custom_property_value(
            "participants_max", errors
        )
        if (
            participants_max is not None
            and participants_max < 1
            or (participants_min is not None and participants_max < participants_min)
        ):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Invalid value for 'participants_max'. Expected a number greater than or equal to 'participants_min'.",
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

            # Initialize all providers
            initiated_providers = []
            for voice in voices:
                voice_provider = voice.provider
                if voice_provider not in initiated_providers:
                    initiated_providers.append(voice_provider)

                    if voice_provider == TtsProvider.OPENAI and not self.wingman.openai:
                        await self.wingman.validate_and_set_openai(errors)
                    elif (
                        voice_provider == TtsProvider.AZURE
                        and not self.wingman.openai_azure
                    ):
                        await self.wingman.validate_and_set_azure(errors)
                    elif (
                        voice_provider == TtsProvider.ELEVENLABS
                        and not self.wingman.elevenlabs
                    ):
                        await self.wingman.validate_and_set_elevenlabs(errors)
                    elif (
                        voice_provider == TtsProvider.WINGMAN_PRO
                        and not self.wingman.wingman_pro
                    ):
                        await self.wingman.validate_and_set_wingman_pro()
                    elif (
                        voice_provider == TtsProvider.INWORLD
                        and not self.wingman.inworld
                    ):
                        await self.wingman.validate_and_set_inworld(errors)

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

    def _get_interval_min(self) -> int:
        """Retrieve fresh interval_min at runtime."""
        errors: list[WingmanInitializationError] = []
        interval = self.retrieve_custom_property_value("interval_min", errors)
        return interval if interval else 10

    def _get_interval_max(self) -> int:
        """Retrieve fresh interval_max at runtime."""
        errors: list[WingmanInitializationError] = []
        interval = self.retrieve_custom_property_value("interval_max", errors)
        return interval if interval else 30

    def _get_messages_min(self) -> int:
        """Retrieve fresh messages_min at runtime."""
        errors: list[WingmanInitializationError] = []
        messages = self.retrieve_custom_property_value("messages_min", errors)
        return messages if messages else 1

    def _get_messages_max(self) -> int:
        """Retrieve fresh messages_max at runtime."""
        errors: list[WingmanInitializationError] = []
        messages = self.retrieve_custom_property_value("messages_max", errors)
        return messages if messages else 3

    def _get_participants_min(self) -> int:
        """Retrieve fresh participants_min at runtime."""
        errors: list[WingmanInitializationError] = []
        participants = self.retrieve_custom_property_value("participants_min", errors)
        return participants if participants else 1

    def _get_participants_max(self) -> int:
        """Retrieve fresh participants_max at runtime."""
        errors: list[WingmanInitializationError] = []
        participants = self.retrieve_custom_property_value("participants_max", errors)
        return participants if participants else 2

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
        errors: list[WingmanInitializationError] = []
        return self.retrieve_custom_property_value("radio_knowledge", errors) or False

    def _get_auto_start(self) -> bool:
        """Retrieve fresh auto_start at runtime."""
        errors: list[WingmanInitializationError] = []
        return self.retrieve_custom_property_value("auto_start", errors) or False

    async def prepare(self) -> None:
        await super().prepare()
        self.loaded = True
        # Start monitoring loop that will auto-start if enabled
        self.threaded_execution(self._monitor_auto_start)

    async def unload(self) -> None:
        await super().unload()
        self.loaded = False
        self.radio_status = False
        self._chatter_starting = False

    def randrange(self, start, stop=None):
        if start == stop:
            return start
        random = randrange(start, stop)
        return random

    @tool(
        name="turn_on_radio",
        description="Turn the radio on to pick up ambient chatter on open frequencies. Creates immersive background radio communication. Use when user wants radio ambience or communication atmosphere.",
    )
    def turn_on_radio(self) -> str:
        """Turn the radio on."""
        if self.radio_status or self._chatter_starting:
            return "Radio is already on."
        else:
            self.threaded_execution(self._init_chatter)
            return "Radio is now on."

    @tool(
        name="turn_off_radio",
        description="Turn the radio off to stop ambient chatter. Use when user wants silence or to disable radio communication sounds.",
    )
    def turn_off_radio(self) -> str:
        """Turn the radio off."""
        if self.radio_status:
            self.radio_status = False
            return "Radio is now off."
        else:
            return "Radio is already off."

    @tool(name="radio_status", description="Get the status (on/off) of the radio.")
    def get_radio_status(self) -> str:
        """Get the current radio status."""
        if self.radio_status:
            return "Radio is on."
        else:
            return "Radio is off."

    async def _monitor_auto_start(self) -> None:
        """Monitor auto_start setting and start radio when enabled."""
        while self.loaded:
            if (
                self._get_auto_start()
                and not self.radio_status
                and not self._chatter_starting
            ):
                # auto_start is enabled and radio is off and not already starting - start it
                self.threaded_execution(self._init_chatter)
            time.sleep(5)  # Check every 5 seconds

    async def _init_chatter(self) -> None:
        """Start the radio chatter."""

        self._chatter_starting = True
        self.radio_status = True
        interval_min = self._get_interval_min()
        time.sleep(max(5, interval_min))  # sleep for min 5s else min interval
        self._chatter_starting = False

        while self.is_active():
            await self._generate_chatter()
            interval_min = self._get_interval_min()
            interval_max = self._get_interval_max()
            interval = self.randrange(interval_min, interval_max)
            time.sleep(interval)

    def is_active(self) -> bool:
        return self.radio_status and self.loaded

    async def _generate_chatter(self):
        if not self.is_active():
            return

        messages_min = self._get_messages_min()
        messages_max = self._get_messages_max()
        participants_min = self._get_participants_min()
        participants_max = self._get_participants_max()
        prompt = self._get_prompt()

        count_message = self.randrange(messages_min, messages_max)
        count_participants = self.randrange(participants_min, participants_max)

        messages = [
            {
                "role": "system",
                "content": f"""
                    ## Must follow these rules ##
                    - There are {count_participants} participant(s) in the conversation/monolog
                    - The conversation/monolog must contain exactly {count_message} messages between the participants or in the monolog
                    - You may always and only return a valid json string without formatting in the following format:

                    ## JSON format ##
                    [
                        {{
                            "user": "Participant1 Name",
                            "content": "Message Content"
                        }},
                        {{
                            "user": "Participant2 Name",
                            "content": "Message Content"
                        }},
                        {{
                            "user": "Participant1 Name",
                            "content": "Message Content"
                        }},
                        ...
                    ]
                """,
            },
            {
                "role": "user",
                "content": str(prompt),
            },
        ]
        completion = await self.llm_call(messages)
        messages = (
            completion.choices[0].message.content
            if completion and completion.choices
            else ""
        )

        if not messages:
            return

        clean_messages = []
        voice_participant_mapping = {}
        try:
            messages = messages.strip()
            messages = json.loads(messages)
        except json.JSONDecodeError as e:
            await self.printr.print_async(
                f"Radio chatter message generation failed due to invalid JSON: {str(e)}",
                LogType.ERROR,
            )
            return

        for message in messages:
            if not message:
                continue

            if "user" not in message or "content" not in message:
                await self.printr.print_async(
                    f"Radio chatter message generation failed due to invalid JSON format: {messages}",
                    LogType.ERROR,
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
                sound_config.effects = [radio_sounds[self.randrange(len(radio_sounds))]]

            voice_participant_mapping[name] = (voice_index[i], sound_config)

        for message in clean_messages:
            name = message["user"]
            text = message["content"]

            if not self.is_active():
                return

            # wait for audio_player idling
            while self.wingman.audio_player.is_playing:
                time.sleep(2)

            if not self.is_active():
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
            self.threaded_execution(self.wingman.play_to_user, text, True, sound_config)
            if self._get_radio_knowledge():
                await self.wingman.add_assistant_message(
                    f"Background radio chatter: {text}"
                )
            max_wait = 10
            while not self.wingman.audio_player.is_playing or max_wait < 0:
                time.sleep(0.1)
                max_wait -= 0.1
            await self._switch_voice(
                original_voice_setting, elevenlabs_streaming, inworld_streaming
            )

        while self.wingman.audio_player.is_playing:
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
                index = self.randrange(len(voices)) - 1
                if index not in voice_index:
                    voice_index.append(index)
                    break

        return voice_index

    async def _switch_voice(
        self,
        voice_setting: VoiceSelection = None,
        elevenlabs_streaming: bool = False,
        inworld_streaming: bool = False,
    ) -> None:
        """Switch voice to the given voice setting."""

        if not voice_setting:
            return

        voice_provider = voice_setting.provider
        voice = voice_setting.voice
        voice_name = None
        error = False

        if voice_provider == TtsProvider.WINGMAN_PRO:
            if voice_setting.subprovider == WingmanProTtsProvider.OPENAI:
                voice_name = voice.value
                self.wingman.config.openai.tts_voice = voice
            elif voice_setting.subprovider == WingmanProTtsProvider.AZURE:
                voice_name = voice
                self.wingman.config.azure.tts.voice = voice
        elif voice_provider == TtsProvider.OPENAI:
            voice_name = voice.value
            self.wingman.config.openai.tts_voice = voice
        elif voice_provider == TtsProvider.ELEVENLABS:
            if isinstance(voice, str):
                # only needed for wingman config restore
                voice_id = voice.split("id=")[1].strip().strip("'")
                voice_name = (
                    voice.split("id=")[0].strip().split("=")[1].strip("'") or voice_id
                )
                voice = ElevenlabsVoiceConfig(id=voice_id, name=voice_name)
            if isinstance(voice, ElevenlabsVoiceConfig):
                self.wingman.config.elevenlabs.voice = voice
                voice_name = voice.name or voice.id
            else:
                error = True
            self.wingman.config.elevenlabs.output_streaming = elevenlabs_streaming
        elif voice_provider == TtsProvider.AZURE:
            voice_name = voice
            self.wingman.config.azure.tts.voice = voice
        elif voice_provider == TtsProvider.XVASYNTH:
            voice_name = voice.voice_name
            self.wingman.config.xvasynth.voice = voice
        elif voice_provider == TtsProvider.EDGE_TTS:
            voice_name = voice
            self.wingman.config.edge_tts.voice = voice
        elif voice_provider == TtsProvider.HUME:
            voice_name = voice.name
            self.wingman.config.hume.voice = voice
        elif voice_provider == TtsProvider.INWORLD:
            voice_name = voice
            self.wingman.config.inworld.voice_id = voice
            self.wingman.config.inworld.output_streaming = inworld_streaming
        else:
            error = True

        if error or not voice_name or not voice_provider:
            await self.printr.print_async(
                f"Voice switching failed due to an unknown voice provider/subprovider or different error. Provider: {voice_provider.value}",
                LogType.ERROR,
            )
            return

        if self.settings.debug_mode:
            await self.printr.print_async(
                f"Switching voice to {voice_name} ({voice_provider.value})"
            )

        self.wingman.config.features.tts_provider = voice_provider

    async def _get_original_voice_setting(self) -> VoiceSelection:
        voice_provider = self.wingman.config.features.tts_provider
        voice_subprovider = None
        voice = None

        if voice_provider == TtsProvider.EDGE_TTS:
            voice = self.wingman.config.edge_tts.voice
        elif voice_provider == TtsProvider.ELEVENLABS:
            voice = self.wingman.config.elevenlabs.voice
        elif voice_provider == TtsProvider.AZURE:
            voice = self.wingman.config.azure.tts.voice
        elif voice_provider == TtsProvider.XVASYNTH:
            voice = self.wingman.config.xvasynth.voice
        elif voice_provider == TtsProvider.OPENAI:
            voice = self.wingman.config.openai.tts_voice
        elif voice_provider == TtsProvider.WINGMAN_PRO:
            voice_subprovider = self.wingman.config.wingman_pro.tts_provider
            if (
                self.wingman.config.wingman_pro.tts_provider
                == WingmanProTtsProvider.OPENAI
            ):
                voice = self.wingman.config.openai.tts_voice
            elif (
                self.wingman.config.wingman_pro.tts_provider
                == WingmanProTtsProvider.AZURE
            ):
                voice = self.wingman.config.azure.tts.voice
        elif voice_provider == TtsProvider.INWORLD:
            voice = self.wingman.config.inworld.voice_id
        else:
            return None

        return VoiceSelection(
            provider=voice_provider, subprovider=voice_subprovider, voice=voice
        )
