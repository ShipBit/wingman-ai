import time
import copy
from os import path
from random import randrange
from typing import TYPE_CHECKING
from api.interface import (
    SettingsConfig,
    SkillConfig,
    WingmanConfig,
    WingmanInitializationError,
)
from api.enums import (
    LogType,
    WingmanInitializationErrorType,
    TtsProvider,
    OpenAiTtsVoice,
    WingmanProTtsProvider,
    SoundEffect,
)
from services.file import get_writable_dir
from services.printr import Printr
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.wingman import Wingman

printr = Printr()

class RadioChatter(Skill):

    def __init__(
        self,
        config: SkillConfig,
        wingman_config: WingmanConfig,
        settings: SettingsConfig,
        wingman: "Wingman",
    ) -> None:

        self.audio_player = wingman.audio_player
        self.file_path = get_writable_dir(path.join("skills", "radio_chatter", "data"))
        self.file_session = path.join(self.file_path, "session.txt")

        self.last_message = None
        self.radio_status = False

        self.prompt = None
        self.voices = []
        self.interval_min = None
        self.interval_max = None
        self.messages_min = None
        self.messages_max = None
        self.participants_min = None
        self.participants_max = None
        self.force_radio_sound = False
        self.auto_start = False

        super().__init__(
            config=config, wingman_config=wingman_config, settings=settings, wingman=wingman
        )

    def _set_session(self, session_id = None):
        if not session_id:
            session_id = randrange(1000000, 9999999)
        # write to file
        with open(self.file_session, "w", encoding="UTF-8") as f:
            f.write(str(session_id))

    def _get_session(self):
        # read from file
        with open(self.file_session, "r", encoding="UTF-8") as f:
            return int(f.read())

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        self.prompt = self.retrieve_custom_property_value(
            "prompt", errors
        )

        # prepare voices
        voices = self.retrieve_custom_property_value(
            "voices", errors
        )
        if voices:
            elvenlabs_voices = None

            # replace whitespace and split by comma
            voice_settings = voices.replace(" ", "").split(",")

            default_provider = self.wingman.tts_provider.value
            default_subprovider = None
            if self.wingman.tts_provider == TtsProvider.WINGMAN_PRO:
                default_subprovider = self.wingman.config.wingman_pro.tts_provider.value

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
                                message="Invalid format in 'voices' field. Expected format: 'voice' or 'provider.voice' or 'provider.subprovider.name'. Given: " + voice,
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
                            message="Invalid TTS provider in 'voices' field: " + voice_provider,
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
                    if not self.wingman.openai:
                        errors.append(
                            WingmanInitializationError(
                                wingman_name=self.wingman.name,
                                message="OpenAI could not be initialized. Please make sure an API key is set.",
                                error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                            )
                        )
                        break
                elif voice_provider == TtsProvider.AZURE and not self.wingman.openai_azure:
                    await self.wingman.validate_and_set_azure(errors)
                    if not self.wingman.openai_azure:
                        errors.append(
                            WingmanInitializationError(
                                wingman_name=self.wingman.name,
                                message="Azure could not be initialized. Please make sure an API key is set.",
                                error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                            )
                        )
                        break
                elif voice_provider == TtsProvider.ELEVENLABS and not self.wingman.elevenlabs:
                    await self.wingman.validate_and_set_elevenlabs(errors)
                    if not self.wingman.elevenlabs:
                        errors.append(
                            WingmanInitializationError(
                                wingman_name=self.wingman.name,
                                message="Elevenlabs could not be initialized. Please make sure an API key is set.",
                                error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                            )
                        )
                        break
                elif voice_provider == TtsProvider.WINGMAN_PRO and not self.wingman.wingman_pro:
                    await self.wingman.validate_and_set_wingman_pro(errors)
                    if not self.wingman.wingman_pro:
                        errors.append(
                            WingmanInitializationError(
                                wingman_name=self.wingman.name,
                                message="Wingman Pro could not be initialized. Please make sure you are logged in and have a valid Wingman Pro subscription.",
                                error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                            )
                        )
                        break

                # if subprovider invalid, throw error
                if voice_provider == TtsProvider.WINGMAN_PRO and voice_subprovider not in (member.value for member in WingmanProTtsProvider):
                    errors.append(
                        WingmanInitializationError(
                            wingman_name=self.wingman.name,
                            message=f"Invalid Wingman Pro sub provider in 'voices' field: {voice_subprovider.value} in {voice}",
                            error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                        )
                    )
                    break
                elif voice_provider != TtsProvider.WINGMAN_PRO and voice_subprovider is not None:
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
                        elvenlabs_voices = self.wingman.elevenlabs.get_available_voices()

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
                                message="Voice not found in Elevenlabs voices: " + voice_name,
                                error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                            )
                        )
                        break

                self.voices.append((voice_provider, voice_subprovider, voice_name, voice_id))

        self.interval_min = self.retrieve_custom_property_value(
            "interval_min", errors
        )
        if self.interval_min is not None and self.interval_min < 1:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Invalid value for 'interval_min'. Expected a number of one or larger.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
        self.interval_max = self.retrieve_custom_property_value(
            "interval_max", errors
        )
        if self.interval_max is not None and self.interval_max < 1 or (self.interval_min is not None and self.interval_max < self.interval_min):
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Invalid value for 'interval_max'. Expected a number greater than or equal to 'interval_min'.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
        self.messages_min = self.retrieve_custom_property_value(
            "messages_min", errors
        )
        if self.messages_min is not None and self.messages_min < 1:
            errors.append(
                WingmanInitializationError(
                    wingman_name=self.wingman.name,
                    message="Invalid value for 'messages_min'. Expected a number of one or larger.",
                    error_type=WingmanInitializationErrorType.INVALID_CONFIG,
                )
            )
        self.messages_max = self.retrieve_custom_property_value(
            "messages_max", errors
        )
        if self.messages_max is not None and self.messages_max < 1 or (self.messages_min is not None and self.messages_max < self.messages_min):
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
        if self.participants_max is not None and self.participants_max < 1 or (self.participants_min is not None and self.participants_max < self.participants_min):
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

        self.auto_start = self.retrieve_custom_property_value(
            "auto_start", errors
        )

        await self._prepare()
        return errors

    async def _prepare(self) -> None:
        self._set_session()
        if(self.auto_start):
            self.threaded_execution(self._init_chatter, self._get_session())

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
                }
            ),
            (
                "turn_off_radio",
                {
                    "type": "function",
                    "function": {
                        "name": "turn_off_radio",
                        "description": "Turn the radio off to no longer pick up pick up chatter on open frequencies.",
                    },
                }
            ),
            (
                "radio_status",
                {
                    "type": "function",
                    "function": {
                        "name": "radio_status",
                        "description": "Get the status (on/off) of the radio.",
                    },
                }
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
                    self._set_session()
                    self.threaded_execution(self._init_chatter, self._get_session())
                    function_response = "Radio is now on."
            elif tool_name == "turn_off_radio":
                if self.radio_status:
                    self._set_session()
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

    async def _init_chatter(self, session) -> None:
        """Start the radio chatter."""

        self.radio_status = True
        time.sleep(5) # just dont start right away

        while session == self._get_session() and self.radio_status:
            interval = randrange(self.interval_min, self.interval_max)
            time.sleep(interval)
            await self._generate_chatter(session)

        self.radio_status = False

    async def _generate_chatter(self, session):
        if session != self._get_session():
            return

        count_message = randrange(self.messages_min, self.messages_max)
        count_participants = randrange(self.participants_min, self.participants_max)

        messages = [
            {
                'role': 'system',
                'content': f"""
                    ## Must follow these rules
                    - There are {count_participants} participant(s) in the conversation, monologs are allowed
                    - The conversation must contain exactly {count_message} messages between the participants or in the monolog
                    - Each new line in your answer represents a new message

                    ## Sample response
                    Person 1: Message Content
                    Person 2: Message Content
                    Person 3: Message Content
                    Person 2: Message Content
                    ...
                """,
            },
            {
                'role': 'user',
                'content': str(self.prompt),
            },
        ]
        completion = await self.llm_call(messages)
        messages = completion.choices[0].message.content if completion and completion.choices else ""

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

        original_voice_provider = await self._get_original_voice_setting()
        original_sound_config = self.wingman.config.sound
        if self.force_radio_sound:
            custom_sound_config = copy.deepcopy(self.wingman.config.sound)
            custom_sound_config.play_beep = True
            custom_sound_config.play_beep_apollo = False
            custom_sound_effect_options = [SoundEffect.LOW_QUALITY_RADIO, SoundEffect.MEDIUM_QUALITY_RADIO, SoundEffect.HIGH_END_RADIO]

        voice_index = await self._get_random_voice_index(len(voice_participant_mapping))
        if not voice_index:
            return
        for i, name in enumerate(voice_participant_mapping):
            sound_config = original_sound_config
            if self.force_radio_sound:
                sound_config = copy.deepcopy(custom_sound_config)
                sound_config.effects = [custom_sound_effect_options[randrange(len(custom_sound_effect_options))]]

            voice_participant_mapping[name] = (voice_index[i], sound_config)

        for name, text in clean_messages:
            if session != self._get_session():
                return

            # wait for audio_player idleing
            while self.audio_player.is_playing:
                time.sleep(2)

            voice_index, sound_config = voice_participant_mapping[name]
            voice_tulple = self.voices[voice_index]

            await self._switch_voice(voice_tulple)
            self.wingman.config.sound = sound_config
            await printr.print_async(
                text=f"Background radio: {text}",
                color=LogType.INFO,
                source_name=self.wingman.name
            )
            self.threaded_execution(self.wingman.play_to_user, text, True)
            await self.wingman.add_assistant_message(f"Background radio chatter: {text}")
            time.sleep(2) # this simulates tts loading time TODO: find a better way to handle this
            await self._switch_voice(original_voice_provider)
            self.wingman.config.sound = original_sound_config

    async def _get_random_voice_index(self, count: int) -> list[int]:
        """Switch voice to a random voice from the list."""

        if count > len(self.voices):
            return []

        if count == len(self.voices):
            return list(range(len(self.voices)))

        voice_index = []
        for i in range(count):
            while True:
                index = randrange(len(self.voices))-1
                if index not in voice_index:
                    voice_index.append(index)
                    break

        return voice_index

    async def _switch_voice(self, voice_tulple) -> None:
        voice_provider, voice_subprovider, voice_name, voice_id = voice_tulple
        # set voice
        self.wingman.tts_provider = voice_provider
        if self.wingman.tts_provider == TtsProvider.EDGE_TTS:
            self.wingman.config.edge_tts.voice = voice_id
        elif self.wingman.tts_provider == TtsProvider.ELEVENLABS:
            self.wingman.config.elevenlabs.voice.id = voice_id
            self.wingman.config.elevenlabs.voice.name = voice_name
        elif self.wingman.tts_provider == TtsProvider.AZURE:
            self.wingman.config.azure.tts.voice = voice_id
        elif self.wingman.tts_provider == TtsProvider.XVASYNTH:
            self.wingman.config.xvasynth.voice = voice_id
        elif self.wingman.tts_provider == TtsProvider.OPENAI:
            self.wingman.config.openai.tts_voice = await self._get_openai_voice_by_name(voice_name)
        elif self.wingman.tts_provider == TtsProvider.WINGMAN_PRO:
            self.wingman.config.wingman_pro.tts_provider = voice_subprovider
            if self.wingman.config.wingman_pro.tts_provider == WingmanProTtsProvider.OPENAI:
                self.wingman.config.openai.tts_voice = await self._get_openai_voice_by_name(voice_name)
            elif self.wingman.config.wingman_pro.tts_provider == WingmanProTtsProvider.AZURE:
                self.wingman.config.azure.tts.voice = voice_id
        else:
            printr.print_async(
                f"Voice switching is not supported for the selected TTS provider: {self.wingman.tts_provider.value}.",
                LogType.WARNING,
            )

    async def _get_original_voice_setting(self) -> tuple:
        voice_provider = self.wingman.tts_provider
        voice_subprovider = None
        voice_name = None
        voice_id = None

        if self.wingman.tts_provider == TtsProvider.EDGE_TTS:
            voice_id = self.wingman.config.edge_tts.voice
        elif self.wingman.tts_provider == TtsProvider.ELEVENLABS:
            voice_id = self.wingman.config.elevenlabs.voice.id
            voice_name = self.wingman.config.elevenlabs.voice.name
        elif self.wingman.tts_provider == TtsProvider.AZURE:
            voice_id = self.wingman.config.azure.tts.voice
        elif self.wingman.tts_provider == TtsProvider.XVASYNTH:
            voice_id = self.wingman.config.xvasynth.voice
        elif self.wingman.tts_provider == TtsProvider.OPENAI:
            voice_name = self.wingman.config.openai.tts_voice.value
        elif self.wingman.tts_provider == TtsProvider.WINGMAN_PRO:
            voice_subprovider = self.wingman.config.wingman_pro.tts_provider
            if self.wingman.config.wingman_pro.tts_provider == WingmanProTtsProvider.OPENAI:
                voice_name = self.wingman.config.openai.tts_voice.value
            elif self.wingman.config.wingman_pro.tts_provider == WingmanProTtsProvider.AZURE:
                voice_id = self.wingman.config.azure.tts.voice

        return (voice_provider, voice_subprovider, voice_name, voice_id)

    async def _get_openai_voice_by_name(self, voice_name):
        return next(
            (voice for voice in OpenAiTtsVoice if voice.value.lower() == voice_name.lower()),
            voice_name,
        )
