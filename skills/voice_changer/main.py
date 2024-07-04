import time
from random import randrange
from typing import TYPE_CHECKING
from api.interface import SettingsConfig, SkillConfig, WingmanInitializationError
from api.enums import (
    LogType,
    WingmanInitializationErrorType,
    TtsProvider,
    OpenAiTtsVoice,
    WingmanProTtsProvider,
)
from skills.skill_base import Skill

if TYPE_CHECKING:
    from wingmen.open_ai_wingman import OpenAiWingman


class VoiceChanger(Skill):

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "OpenAiWingman",
    ) -> None:
        super().__init__(config=config, settings=settings, wingman=wingman)

        self.voice_switching = True
        self.voices = []
        self.voice_timespan = 0
        self.voice_last_message = None
        self.voice_current_index = None
        self.clear_history = False

        self.context_generation = True
        self.context_prompt = None
        self.context_personality = ""
        self.context_personality_next = ""

        self.active = False

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        self.voice_timespan = self.retrieve_custom_property_value(
            "voice_changer_interval", errors
        )
        if not self.voice_timespan or self.voice_timespan < 0:
            self.voice_switching = False

        self.clear_history = self.retrieve_custom_property_value(
            "voice_changer_clearhistory", errors
        )

        self.context_prompt = self.retrieve_custom_property_value(
            "voice_changer_personalityprompt", errors
        )
        if not self.context_prompt:
            self.context_generation = False

        # prepare voices
        voices = self.retrieve_custom_property_value("voice_changer_voices", errors)
        if not voices:
            self.voice_switching = False
        else:
            elvenlabs_voices = None

            # replace whitespace and split by comma
            voice_settings = voices.replace(" ", "").split(",")

            default_provider = self.wingman.config.features.tts_provider.value
            default_subprovider = None
            if self.wingman.config.features.tts_provider == TtsProvider.WINGMAN_PRO:
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

        return errors

    async def prepare(self) -> None:
        self.active = True

        # prepare first personality
        if self.context_generation:
            self.threaded_execution(self._generate_new_context)

    async def unload(self) -> None:
        self.active = False

    async def on_add_user_message(self, message: str):
        if not self.active:
            return

        if self.voice_last_message is None:
            await self._initiate_change()
            self.voice_last_message = time.time()
            return

        last_message_diff = time.time() - self.voice_last_message
        last_message_diff = round(last_message_diff, 0)
        self.voice_last_message = time.time()

        if last_message_diff >= self.voice_timespan:
            await self._initiate_change()

    async def _initiate_change(self):
        messages = []
        if self.voice_switching:
            messages.append(self._switch_voice())
        if self.context_generation:
            messages.append(self._switch_personality())
        if self.clear_history:
            self.wingman.reset_conversation_history()

        # sort out empty messages
        messages = [await message for message in messages if message]

        if messages:
            await self.printr.print_async(
                text="\n".join(messages),
                color=LogType.INFO,
                source_name=self.wingman.name,
            )

    async def _switch_voice(self) -> str:
        """Switch voice to a random voice from the list."""

        message = ""

        # choose voice
        while True:
            index = randrange(len(self.voices)) - 1
            if (
                self.voice_current_index is None
                or len(self.voices) == 1
                or index != self.voice_current_index
            ):
                self.voice_current_index = index

                voice_provider, voice_subprovider, voice_name, voice_id = self.voices[
                    index
                ]

                message = f"Switched {self.wingman.name}'s voice to {voice_name} ({voice_provider.value}"
                if voice_subprovider:
                    message += f"/{voice_subprovider.value}"
                message += ")."
                break

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
            self.wingman.config.xvasynth.voice = voice_id
        elif voice_provider == TtsProvider.OPENAI:
            self.wingman.config.openai.tts_voice = (
                await self.__get_openai_voice_by_name(voice_name)
            )
        elif voice_provider == TtsProvider.WINGMAN_PRO:
            self.wingman.config.wingman_pro.tts_provider = voice_subprovider
            if (
                self.wingman.config.wingman_pro.tts_provider
                == WingmanProTtsProvider.OPENAI
            ):
                self.wingman.config.openai.tts_voice = (
                    await self.__get_openai_voice_by_name(voice_name)
                )
            elif (
                self.wingman.config.wingman_pro.tts_provider
                == WingmanProTtsProvider.AZURE
            ):
                self.wingman.config.azure.tts.voice = voice_id
        else:
            self.printr.print_async(
                f"Voice switching is not supported for the selected TTS provider: {self.wingman.tts_provider.value}.",
                LogType.WARNING,
            )

        return message

    async def __get_openai_voice_by_name(self, voice_name: str):
        return next(
            (
                voice
                for voice in OpenAiTtsVoice
                if voice.value.lower() == voice_name.lower()
            ),
            None,
        )

    async def _switch_personality(self) -> str:
        # if no next context is available, generate a new one
        if not self.context_personality_next:
            await self._generate_new_context()

        self.context_personality = self.context_personality_next
        self.context_personality_next = ""

        self.threaded_execution(self._generate_new_context)

        return "Switched personality context."

    async def _generate_new_context(self):
        messages = [
            {
                "role": "system",
                "content": """
                    Generate new context based on the input in the \"You\"-perspective.
                    Like \"You are a grumpy...\" or \"You are an enthusiastic...\" and so on.
                    Only output the personality description without additional context or commentary.
                """,
            },
            {
                "role": "user",
                "content": self.context_prompt,
            },
        ]
        completion = await self.llm_call(messages)
        generated_context = (
            completion.choices[0].message.content
            if completion and completion.choices
            else ""
        )

        self.context_personality_next = generated_context

    async def get_prompt(self) -> str | None:
        prompts = []
        if self.config.prompt:
            prompts.append(self.config.prompt)
        if self.context_generation:
            prompts.append(self.context_personality)
        return " ".join(prompts) if prompts else None
