import time
from random import randrange
from typing import TYPE_CHECKING
from api.interface import (
    SettingsConfig,
    SkillConfig,
    VoiceSelection,
    WingmanInitializationError,
)
from api.enums import (
    LogType,
    TtsProvider,
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

        self.voice_last_message = None
        self.voice_current_index = None
        self.context_personality = ""
        self.context_personality_next = ""
        self.active = False

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        # Validate properties exist (don't cache values)
        self.retrieve_custom_property_value("voice_changer_interval", errors)
        self.retrieve_custom_property_value("voice_changer_clearhistory", errors)
        self.retrieve_custom_property_value("voice_changer_personalityprompt", errors)

        # Validate and initialize providers for all configured voices
        voices: list[VoiceSelection] = self.retrieve_custom_property_value(
            "voice_changer_voices", errors
        )
        if voices and len(voices) > 0:
            # Initialize all providers
            initiated_providers = []

            for voice in voices:
                voice_provider = voice.provider
                if voice_provider not in initiated_providers:
                    initiated_providers.append(voice_provider)

                    # initiate provider
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
                    elif (
                        voice_provider == TtsProvider.OPENAI_COMPATIBLE
                        and not self.wingman.openai_compatible_tts
                    ):
                        await self.wingman.validate_and_set_openai_compatible_tts(
                            errors
                        )

        return errors

    def _get_voices(self) -> list[VoiceSelection]:
        """Retrieve fresh voices list at runtime."""
        errors: list[WingmanInitializationError] = []
        voices = self.retrieve_custom_property_value("voice_changer_voices", errors)
        return voices if voices else []

    def _get_voice_timespan(self) -> int:
        """Retrieve fresh voice change interval at runtime."""
        errors: list[WingmanInitializationError] = []
        timespan = self.retrieve_custom_property_value("voice_changer_interval", errors)
        return timespan if timespan and timespan >= 0 else 0

    def _get_clear_history(self) -> bool:
        """Retrieve fresh clear history setting at runtime."""
        errors: list[WingmanInitializationError] = []
        return (
            self.retrieve_custom_property_value("voice_changer_clearhistory", errors)
            or False
        )

    def _get_context_prompt(self) -> str | None:
        """Retrieve fresh context prompt at runtime."""
        errors: list[WingmanInitializationError] = []
        return self.retrieve_custom_property_value(
            "voice_changer_personalityprompt", errors
        )

    async def prepare(self) -> None:
        await super().prepare()
        self.active = True

        # prepare first personality
        if self._get_context_prompt():
            self.threaded_execution(self._generate_new_context)

    async def unload(self) -> None:
        await super().unload()
        self.active = False

    async def on_add_user_message(self, message: str):
        if not self.active:
            return

        if self.voice_last_message is None:
            await self._initiate_change()
            self.voice_last_message = time.time()
            return

        voice_timespan = self._get_voice_timespan()
        if voice_timespan <= 0:
            return

        last_message_diff = time.time() - self.voice_last_message
        last_message_diff = round(last_message_diff, 0)
        self.voice_last_message = time.time()

        if last_message_diff >= voice_timespan:
            await self._initiate_change()

    async def _initiate_change(self):
        messages = []
        voices = self._get_voices()
        if voices:
            messages.append(self._switch_voice(voices))
        if self._get_context_prompt():
            messages.append(self._switch_personality())
        if self._get_clear_history():
            self.wingman.reset_conversation_history()

        # sort out empty messages
        messages = [await message for message in messages if message]

        if messages:
            await self.printr.print_async(
                text="\n".join(messages),
                color=LogType.INFO,
                source_name=self.wingman.name,
            )

    async def _switch_voice(self, voices: list[VoiceSelection]) -> str:
        """Switch voice to the given voice setting."""

        provider_name = None

        # choose voice
        while True:
            index = randrange(len(voices)) - 1
            if (
                self.voice_current_index is None
                or len(voices) == 1
                or index != self.voice_current_index
            ):
                self.voice_current_index = index
                voice_setting = voices[index]
                break

        if not voice_setting:
            await self.printr.print_async(
                "Voice switching failed due to missing voice settings.",
                LogType.ERROR,
            )
            return "Voice switching failed due to missing voice settings."

        voice_provider = voice_setting.provider
        voice = voice_setting.voice
        voice_name = None
        error = False

        if voice_provider == TtsProvider.WINGMAN_PRO:
            if voice_setting.subprovider == WingmanProTtsProvider.OPENAI:
                voice_name = voice.value
                provider_name = "Wingman Pro / OpenAI"
                self.wingman.config.openai.tts_voice = voice
            elif voice_setting.subprovider == WingmanProTtsProvider.AZURE:
                voice_name = voice
                provider_name = "Wingman Pro / Azure TTS"
                self.wingman.config.azure.tts.voice = voice
            elif voice_setting.subprovider == WingmanProTtsProvider.INWORLD:
                voice_name = voice
                provider_name = "Wingman Pro / Inworld"
                self.wingman.config.inworld.voice_id = voice
                self.wingman.config.inworld.output_streaming = False
        elif voice_provider == TtsProvider.OPENAI:
            voice_name = voice.value
            provider_name = "OpenAI"
            self.wingman.config.openai.tts_voice = voice
        elif voice_provider == TtsProvider.ELEVENLABS:
            voice_name = voice.name or voice.id
            provider_name = "Elevenlabs"
            self.wingman.config.elevenlabs.voice = voice
            self.wingman.config.elevenlabs.output_streaming = False
        elif voice_provider == TtsProvider.AZURE:
            voice_name = voice
            provider_name = "Azure TTS"
            self.wingman.config.azure.tts.voice = voice
        elif voice_provider == TtsProvider.XVASYNTH:
            voice_name = voice.voice_name
            provider_name = "XVASynth"
            self.wingman.config.xvasynth.voice = voice
        elif voice_provider == TtsProvider.EDGE_TTS:
            voice_name = voice
            provider_name = "Edge TTS"
            self.wingman.config.edge_tts.voice = voice
        elif voice_provider == TtsProvider.INWORLD:
            voice_name = voice
            self.wingman.config.inworld.voice_id = voice
            self.wingman.config.inworld.output_streaming = False
            provider_name = "InWorld"
        elif voice_provider == TtsProvider.POCKET_TTS:
            voice_name = voice
            self.wingman.config.pocket_tts.voice = voice
            self.wingman.config.pocket_tts.output_streaming = False
            provider_name = "PocketTTS"
        elif voice_provider == TtsProvider.OPENAI_COMPATIBLE:
            voice_name = voice
            self.wingman.config.openai_compatible_tts.voice = voice
            self.wingman.config.openai_compatible_tts.output_streaming = False
            provider_name = "OpenAI Compatible"
        else:
            error = True

        if error or not voice_name or not voice_provider:
            await self.printr.print_async(
                f"Voice switching failed due to an unknown voice provider/subprovider or different error. Provider: {voice_provider.value}",
                LogType.ERROR,
            )
            return f"Voice switching failed due to an unknown voice provider/subprovider. Provider: {voice_provider.value}"

        self.wingman.config.features.tts_provider = voice_provider
        if not provider_name:
            provider_name = voice_provider.value

        return f"Switched {self.wingman.name}'s voice to {voice_name} ({provider_name})"

    async def _switch_personality(self) -> str:
        # if no next context is available, generate a new one
        if not self.context_personality_next:
            await self._generate_new_context()

        self.context_personality = self.context_personality_next
        self.context_personality_next = ""

        self.threaded_execution(self._generate_new_context)

        return "Switched personality context."

    async def _generate_new_context(self):
        context_prompt = self._get_context_prompt()
        if not context_prompt:
            return

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
                "content": context_prompt,
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
        if self._get_context_prompt() and self.context_personality:
            prompts.append(self.context_personality)
        return " ".join(prompts) if prompts else None
