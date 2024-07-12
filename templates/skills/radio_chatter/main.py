import time
import copy
from os import path
from random import randrange
from typing import TYPE_CHECKING
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from api.enums import (
    LogType,
    WingmanInitializationErrorType,
    TtsProvider,
    OpenAiTtsVoice,
    WingmanProTtsProvider,
    SoundEffect,
)
from services.file import get_writable_dir
from skills.skill_base import Skill

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

        self.file_path = get_writable_dir(path.join("skills", "radio_chatter", "data"))

        self.last_message = None
        self.radio_status = False
        self.loaded = False

        self.prompt = None
        self.voices = []
        self.interval_min = None
        self.interval_max = None
        self.messages_min = None
        self.messages_max = None
        self.participants_min = None
        self.participants_max = None
        self.force_radio_sound = False
        self.radio_sounds = []
        self.use_beeps = False
        self.auto_start = False
        self.volume = 1.0
        self.print_chatter = False
        self.radio_knowledge = False

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        self.prompt = self.retrieve_custom_property_value("prompt", errors)

        # prepare voices
        voices = self.retrieve_custom_property_value("voices", errors)
        if voices:
            elvenlabs_voices = None

            # replace whitespace and split by comma
            voice_settings = voices.replace(" ", "").split(",")

            default_provider = self.wingman.config.features.tts_provider.value
            default_subprovider = None
            if self.wingman.config.features.tts_provider == TtsProvider.WINGMAN_PRO:
                default_subprovider = self.wingman.config.wingman_pro.tts_provider.value
            if self.wingman.config.features.tts_provider == TtsProvider.XVASYNTH:
                default_subprovider = self.wingman.config.xvasynth.game_folder_name

            # TODO: this is way too complicated. We should just use the already configured TTS provider from the wingman and offer the voices for this provider.
            for voice in voice_settings:
                # split provider and voice name
                voice_provider = default_provider
                voice_subprovider = default_subprovider
                voice_name = voice
                voice_id = voice
                if voice.find("."):
                    voice_split = voice.split(".")
                    if len(voice_split) > 3:
                        errors.append(
                            WingmanInitializationError(
                                wingman_name=self.wingman.name,
                                message="Invalid format in 'voices' field. Expected format: 'voice' or 'provider.voice' or 'provider.subprovider.name'. Given: "
                                + voice,
                                error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                            )
                        )
                        break
                    else:
                        if len(voice_split) == 3:
                            voice_provider = voice_split[0].lower()
                            voice_subprovider = voice_split[1].lower()
                            voice_name = voice_split[2]
                            voice_id = voice_name
                        elif len(voice_split) == 2:
                            voice_provider = voice_split[0].lower()
                            voice_subprovider = None
                            voice_name = voice_split[1]
                            voice_id = voice_name
                        else:
                            voice_name = voice_split[0]
                            voice_id = voice_name

                # if provider not in enum (TtsProvider), throw error
                if voice_provider not in (member.value for member in TtsProvider):
                    errors.append(
                        WingmanInitializationError(
                            wingman_name=self.wingman.name,
                            message="Invalid TTS provider in 'voices' field: "
                            + voice_provider,
                            error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                        )
                    )
                    break
                else:
                    for member in TtsProvider:
                        if member.value == voice_provider:
                            voice_provider = member
                            break

                # check if api key is set for provider -> will open prompt if not set
                if voice_provider == TtsProvider.OPENAI and not self.wingman.openai:
                    await self.wingman.validate_and_set_openai(errors)
                    if len(errors) > 0:
                        break
                elif (
                    voice_provider == TtsProvider.AZURE
                    and not self.wingman.openai_azure
                ):
                    await self.wingman.validate_and_set_azure(errors)
                    if len(errors) > 0:
                        break
                elif (
                    voice_provider == TtsProvider.ELEVENLABS
                    and not self.wingman.elevenlabs
                ):
                    await self.wingman.validate_and_set_elevenlabs(errors)
                    if len(errors) > 0:
                        break
                elif (
                    voice_provider == TtsProvider.WINGMAN_PRO
                    and not self.wingman.wingman_pro
                ):
                    await self.wingman.validate_and_set_wingman_pro(errors)
                    if len(errors) > 0:
                        break
                elif (
                    voice_provider == TtsProvider.XVASYNTH
                    and not self.wingman.xvasynth
                ):
                    await self.wingman.validate_and_set_xvasynth(errors)
                    if len(errors) > 0:
                        break
                # if subprovider invalid, throw error
                if (
                    voice_provider == TtsProvider.WINGMAN_PRO
                    and voice_subprovider
                    not in (member.value for member in WingmanProTtsProvider)
                ):
                    errors.append(
                        WingmanInitializationError(
                            wingman_name=self.wingman.name,
                            message=f"Invalid Wingman Pro sub provider in 'voices' field: {voice_subprovider.value} in {voice}",
                            error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                        )
                    )
                    break
                elif (
                    voice_provider != TtsProvider.WINGMAN_PRO
                    and voice_provider != TtsProvider.XVASYNTH
                    and voice_subprovider is not None
                ):
                    errors.append(
                        WingmanInitializationError(
                            wingman_name=self.wingman.name,
                            message=f"Sub provider not supported for TTS provider: {voice_provider.value} in {voice}",
                            error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                        )
                    )
                    break
                elif voice_provider == TtsProvider.WINGMAN_PRO:
                    for member in WingmanProTtsProvider:
                        if member.value == voice_subprovider:
                            voice_subprovider = member
                            break

                for member in TtsProvider:
                    if member.value == voice_provider:
                        voice_provider = member
                        break

                # special handling for elevenlabs to sync voice id and name
                if voice_provider == TtsProvider.ELEVENLABS:
                    # load available voices once
                    if elvenlabs_voices is None:
                        elvenlabs_voices = (
                            self.wingman.elevenlabs.get_available_voices()
                        )

                    found = False
                    for elevenlabs_voice in elvenlabs_voices:
                        if elevenlabs_voice.voiceID == voice_id:
                            voice_name = elevenlabs_voice.name
                            found = True
                            break
                        if elevenlabs_voice.name == voice_name:
                            voice_id = elevenlabs_voice.voiceID
                            found = True
                            break

                    if not found:
                        errors.append(
                            WingmanInitializationError(
                                wingman_name=self.wingman.name,
                                message="Voice not found in Elevenlabs voices: "
                                + voice_name,
                                error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                            )
                        )
                        break

                self.voices.append(
                    (voice_provider, voice_subprovider, voice_name, voice_id)
                )

        self.interval_min = self.retrieve_custom_property_value("interval_min", errors)
        if self.interval_min is not None and self.interval_min < 1:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Invalid value for 'interval_min'. Expected a number of one or larger.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
        self.interval_max = self.retrieve_custom_property_value("interval_max", errors)
        if (
            self.interval_max is not None
            and self.interval_max < 1
            or (self.interval_min is not None and self.interval_max < self.interval_min)
        ):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Invalid value for 'interval_max'. Expected a number greater than or equal to 'interval_min'.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
        self.messages_min = self.retrieve_custom_property_value("messages_min", errors)
        if self.messages_min is not None and self.messages_min < 1:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Invalid value for 'messages_min'. Expected a number of one or larger.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
        self.messages_max = self.retrieve_custom_property_value("messages_max", errors)
        if (
            self.messages_max is not None
            and self.messages_max < 1
            or (self.messages_min is not None and self.messages_max < self.messages_min)
        ):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Invalid value for 'messages_max'. Expected a number greater than or equal to 'messages_min'.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
        self.participants_min = self.retrieve_custom_property_value(
            "participants_min", errors
        )
        if self.participants_min is not None and self.participants_min < 1:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Invalid value for 'participants_min'. Expected a number of one or larger.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
        self.participants_max = self.retrieve_custom_property_value(
            "participants_max", errors
        )
        if (
            self.participants_max is not None
            and self.participants_max < 1
            or (
                self.participants_min is not None
                and self.participants_max < self.participants_min
            )
        ):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Invalid value for 'participants_max'. Expected a number greater than or equal to 'participants_min'.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )

        if not self.voices or self.participants_max > len(self.voices):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Not enough voices available for the configured number of max participants.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )

        self.force_radio_sound = self.retrieve_custom_property_value(
            "force_radio_sound", errors
        )

        self.auto_start = self.retrieve_custom_property_value("auto_start", errors)

        self.volume = self.retrieve_custom_property_value("volume", errors) or 0.5
        if self.volume < 0 or self.volume > 1:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Invalid value for 'volume'. Expected a number between 0 and 1.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
        self.print_chatter = self.retrieve_custom_property_value(
            "print_chatter", errors
        )
        self.radio_knowledge = self.retrieve_custom_property_value(
            "radio_knowledge", errors
        )
        radio_sounds = self.retrieve_custom_property_value("radio_sounds", errors)
        # split by comma
        if radio_sounds:
            radio_sounds = radio_sounds.lower().replace(" ", "").split(",")
            if "low" in radio_sounds:
                self.radio_sounds.append(SoundEffect.LOW_QUALITY_RADIO)
            if "medium" in radio_sounds:
                self.radio_sounds.append(SoundEffect.MEDIUM_QUALITY_RADIO)
            if "high" in radio_sounds:
                self.radio_sounds.append(SoundEffect.HIGH_END_RADIO)
        if not self.radio_sounds:
            self.force_radio_sound = False
        self.use_beeps = self.retrieve_custom_property_value("use_beeps", errors)

        return errors

    async def prepare(self) -> None:
        self.loaded = True
        if self.auto_start:
            self.threaded_execution(self._init_chatter)

    async def unload(self) -> None:
        self.loaded = False
        self.radio_status = False

    def randrange(self, start, stop=None):
        if start == stop:
            return start
        random = randrange(start, stop)
        return random

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = [
            (
                "turn_on_radio",
                {
                    "type": "function",
                    "function": {
                        "name": "turn_on_radio",
                        "description": "Turn the radio on to pick up some chatter on open frequencies.",
                    },
                },
            ),
            (
                "turn_off_radio",
                {
                    "type": "function",
                    "function": {
                        "name": "turn_off_radio",
                        "description": "Turn the radio off to no longer pick up pick up chatter on open frequencies.",
                    },
                },
            ),
            (
                "radio_status",
                {
                    "type": "function",
                    "function": {
                        "name": "radio_status",
                        "description": "Get the status (on/off) of the radio.",
                    },
                },
            ),
        ]
        return tools

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        function_response = ""
        instant_response = ""

        if tool_name in ["turn_on_radio", "turn_off_radio", "radio_status"]:
            if self.settings.debug_mode:
                self.start_execution_benchmark()

            if tool_name == "turn_on_radio":
                if self.radio_status:
                    function_response = "Radio is already on."
                else:
                    self.threaded_execution(self._init_chatter)
                    function_response = "Radio is now on."
            elif tool_name == "turn_off_radio":
                if self.radio_status:
                    self.radio_status = False
                    function_response = "Radio is now off."
                else:
                    function_response = "Radio is already off."
            elif tool_name == "radio_status":
                if self.radio_status:
                    function_response = "Radio is on."
                else:
                    function_response = "Radio is off."

            if self.settings.debug_mode:
                await self.print_execution_time()

        return function_response, instant_response

    async def _init_chatter(self) -> None:
        """Start the radio chatter."""

        self.radio_status = True
        time.sleep(max(5, self.interval_min))  # sleep for min 5s else min interval

        while self.is_active():
            await self._generate_chatter()
            interval = self.randrange(self.interval_min, self.interval_max)
            time.sleep(interval)

    def is_active(self) -> bool:
        return self.radio_status and self.loaded

    async def _generate_chatter(self):
        if not self.is_active():
            return

        count_message = self.randrange(self.messages_min, self.messages_max)
        count_participants = self.randrange(
            self.participants_min, self.participants_max
        )

        messages = [
            {
                "role": "system",
                "content": f"""
                    ## Must follow these rules
                    - There are {count_participants} participant(s) in the conversation/monolog
                    - The conversation/monolog must contain exactly {count_message} messages between the participants or in the monolog
                    - Each new line in your answer represents a new message
                    - Use matching call signs for the participants

                    ## Sample response
                    Name1: Message Content
                    Name2: Message Content
                    Name3: Message Content
                    Name2: Message Content
                    ...
                """,
            },
            {
                "role": "user",
                "content": str(self.prompt),
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
        for message in messages.split("\n"):
            if not message:
                continue

            # get name before first ":"
            name = message.split(":")[0].strip()
            text = message.split(":", 1)[1].strip()

            if name not in voice_participant_mapping:
                voice_participant_mapping[name] = None

            clean_messages.append((name, text))

        original_voice_setting = await self._get_original_voice_setting()
        original_sound_config = copy.deepcopy(self.wingman.config.sound)

        # copy for volume and effects
        custom_sound_config = copy.deepcopy(self.wingman.config.sound)
        custom_sound_config.play_beep = self.use_beeps
        custom_sound_config.play_beep_apollo = False
        custom_sound_config.volume = custom_sound_config.volume * self.volume

        voice_index = await self._get_random_voice_index(len(voice_participant_mapping))
        if not voice_index:
            return
        for i, name in enumerate(voice_participant_mapping):
            sound_config = original_sound_config
            if self.force_radio_sound:
                sound_config = copy.deepcopy(custom_sound_config)
                sound_config.effects = [
                    self.radio_sounds[self.randrange(len(self.radio_sounds))]
                ]

            voice_participant_mapping[name] = (voice_index[i], sound_config)

        for name, text in clean_messages:
            if not self.is_active():
                return

            # wait for audio_player idleing
            while self.wingman.audio_player.is_playing:
                time.sleep(2)

            if not self.is_active():
                return

            voice_index, sound_config = voice_participant_mapping[name]
            voice_tulple = self.voices[voice_index]

            await self._switch_voice(voice_tulple)
            if self.print_chatter:
                await self.printr.print_async(
                    text=f"Background radio ({name}): {text}",
                    color=LogType.INFO,
                    source_name=self.wingman.name,
                )
            self.threaded_execution(self.wingman.play_to_user, text, True, sound_config)
            if self.radio_knowledge:
                await self.wingman.add_assistant_message(
                    f"Background radio chatter: {text}"
                )
            while not self.wingman.audio_player.is_playing:
                time.sleep(0.1)
            await self._switch_voice(original_voice_setting)

        while self.wingman.audio_player.is_playing:
            time.sleep(1)  # stay in function call until last message got played

    async def _get_random_voice_index(self, count: int) -> list[int]:
        """Switch voice to a random voice from the list."""

        if count > len(self.voices):
            return []

        if count == len(self.voices):
            return list(range(len(self.voices)))

        voice_index = []
        for i in range(count):
            while True:
                index = self.randrange(len(self.voices)) - 1
                if index not in voice_index:
                    voice_index.append(index)
                    break

        return voice_index

    async def _switch_voice(self, voice_tuple) -> None:
        voice_provider, voice_subprovider, voice_name, voice_id = voice_tuple
        # set voice
        self.wingman.config.features.tts_provider = voice_provider
        if voice_provider == TtsProvider.EDGE_TTS:
            self.wingman.config.edge_tts.voice = voice_id
        elif voice_provider == TtsProvider.ELEVENLABS:
            self.wingman.config.elevenlabs.voice.id = voice_id
            self.wingman.config.elevenlabs.voice.name = voice_name
        elif voice_provider == TtsProvider.AZURE:
            self.wingman.config.azure.tts.voice = voice_id
        elif voice_provider == TtsProvider.XVASYNTH:
            # Note, XVASynth needs to have had its path (xvasynth_path) and language (if different from defaults) set at least once in the GUI for the wingman for it to work, or someday with global settings config edits
            self.wingman.config.xvasynth.game_folder_name = voice_subprovider
            self.wingman.config.xvasynth.voice = voice_id
        elif voice_provider == TtsProvider.OPENAI:
            self.wingman.config.openai.tts_voice = await self._get_openai_voice_by_name(
                voice_name
            )
        elif voice_provider == TtsProvider.WINGMAN_PRO:
            self.wingman.config.wingman_pro.tts_provider = voice_subprovider
            if (
                self.wingman.config.wingman_pro.tts_provider
                == WingmanProTtsProvider.OPENAI
            ):
                self.wingman.config.openai.tts_voice = (
                    await self._get_openai_voice_by_name(voice_name)
                )
            elif (
                self.wingman.config.wingman_pro.tts_provider
                == WingmanProTtsProvider.AZURE
            ):
                self.wingman.config.azure.tts.voice = voice_id
        else:
            self.printr.print_async(
                f"Voice switching is not supported for the selected TTS provider: {voice_provider.value}.",
                LogType.WARNING,
            )

    async def _get_original_voice_setting(self) -> tuple:
        voice_provider = self.wingman.config.features.tts_provider
        voice_subprovider = None
        voice_name = None
        voice_id = None

        if voice_provider == TtsProvider.EDGE_TTS:
            voice_id = self.wingman.config.edge_tts.voice
        elif voice_provider == TtsProvider.ELEVENLABS:
            voice_id = self.wingman.config.elevenlabs.voice.id
            voice_name = self.wingman.config.elevenlabs.voice.name
        elif voice_provider == TtsProvider.AZURE:
            voice_id = self.wingman.config.azure.tts.voice
        elif voice_provider == TtsProvider.XVASYNTH:
            self.wingman.config.xvasynth.game_folder_name = voice_subprovider
            self.wingman.config.xvasynth.voice = voice_id
        elif voice_provider == TtsProvider.OPENAI:
            voice_name = self.wingman.config.openai.tts_voice.value
        elif voice_provider == TtsProvider.WINGMAN_PRO:
            voice_subprovider = self.wingman.config.wingman_pro.tts_provider
            if (
                self.wingman.config.wingman_pro.tts_provider
                == WingmanProTtsProvider.OPENAI
            ):
                voice_name = self.wingman.config.openai.tts_voice.value
            elif (
                self.wingman.config.wingman_pro.tts_provider
                == WingmanProTtsProvider.AZURE
            ):
                voice_id = self.wingman.config.azure.tts.voice

        return (voice_provider, voice_subprovider, voice_name, voice_id)

    async def _get_openai_voice_by_name(self, voice_name):
        return next(
            (
                voice
                for voice in OpenAiTtsVoice
                if voice.value.lower() == voice_name.lower()
            ),
            voice_name,
        )
