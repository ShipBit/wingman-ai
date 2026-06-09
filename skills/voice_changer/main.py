import time
from random import randrange
from typing import TYPE_CHECKING
from api.interface import (
    SettingsConfig,
    SkillConfig,
    VoiceSelection,
    WingmanInitializationError,
)
from skills.skill_base import Skill, command_action

if TYPE_CHECKING:
    from wingmen.wingman_context import WingmanContext


class VoiceChanger(Skill):

    def __init__(
        self,
        config: SkillConfig,
        settings: SettingsConfig,
        wingman: "WingmanContext",
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
        # Voices are applied to the current provider via ctx.tts.set_voice() at
        # voice-switch time (which rebuilds the TTS instance). No pre-init needed.

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
            self.wingman.run_in_thread(self._generate_new_context)

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

    @command_action(
        label="Switch voice now",
        description="Immediately switch to a random configured voice, regardless of the timed schedule.",
        respond="speak",
    )
    async def switch_voice_now(self) -> str:
        voices = self._get_voices()
        if not voices:
            return "No voices are configured to switch to."
        return await self._switch_voice(voices)

    async def _initiate_change(self):
        messages = []
        voices = self._get_voices()
        if voices:
            messages.append(self._switch_voice(voices))
        if self._get_context_prompt():
            messages.append(self._switch_personality())
        if self._get_clear_history():
            await self.wingman.conversation.reset()

        # sort out empty messages
        messages = [await message for message in messages if message]

        if messages:
            self.log.info("\n".join(messages))

    async def _switch_voice(self, voices: list[VoiceSelection]) -> str:
        """Pick a (different) configured voice and set it on the current provider.

        The sanctioned ctx.tts.set_voice applies the voice to the wingman's CURRENT
        TTS provider only — no provider switching. Configs are migrated so the voice
        list only contains voices for the active provider.
        """
        # Only voices for the active provider are usable (no cross-provider switching).
        current_provider = self.wingman.config.features.tts_provider
        voices = [v for v in voices if v.provider == current_provider]
        if not voices:
            return "No configured voice matches the current TTS provider."

        # choose a voice different from the current one
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
            self.log.error("Voice switching failed due to missing voice settings.")
            return "Voice switching failed due to missing voice settings."

        return await self.wingman.tts.set_voice(voice_setting.voice)

    async def _switch_personality(self) -> str:
        # if no next context is available, generate a new one
        if not self.context_personality_next:
            await self._generate_new_context()

        self.context_personality = self.context_personality_next
        self.context_personality_next = ""

        self.wingman.run_in_thread(self._generate_new_context)

        return "Switched personality context."

    async def _generate_new_context(self):
        context_prompt = self._get_context_prompt()
        if not context_prompt:
            return

        system = """
            Generate new context based on the input in the "You"-perspective.
            Like "You are a grumpy..." or "You are an enthusiastic..." and so on.
            Only output the personality description without additional context or commentary.
        """
        self.context_personality_next = await self.wingman.ai.generate(
            context_prompt, system=system, auto_shorten=True
        )

    async def get_prompt(self) -> str | None:
        prompts = []
        if self.config.prompt:
            prompts.append(self.config.prompt)
        if self._get_context_prompt() and self.context_personality:
            prompts.append(self.context_personality)
        return " ".join(prompts) if prompts else None
