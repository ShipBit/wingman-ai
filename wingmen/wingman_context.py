"""Controlled interface for skills. Limits what plugins can access."""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletion
    from api.enums import TtsProvider
    from api.interface import SoundConfig, WingmanConfig, SettingsConfig
    from services.audio_player import AudioPlayer
    from wingmen.wingman import Wingman


class WingmanContext:
    """What skills see. Controlled API surface — no internal leaking."""

    def __init__(self, wingman: "Wingman"):
        self._wingman = wingman

    # --- Properties ---

    @property
    def name(self) -> str:
        return self._wingman.name

    @property
    def config(self) -> "WingmanConfig":
        return self._wingman.config

    @property
    def settings(self) -> "SettingsConfig":
        return self._wingman.settings

    @property
    def audio_player(self) -> "AudioPlayer":
        return self._wingman.audio_player

    @property
    def tower(self):
        return self._wingman.tower

    @property
    def secret_keeper(self):
        return self._wingman.secret_keeper

    # --- Conversation ---

    async def llm_call(self, messages: list[dict], tools: list[dict] | None = None) -> "ChatCompletion | None":
        """Make an LLM call. Replaces actual_llm_call()."""
        return await self._wingman.actual_llm_call(messages, tools)

    def get_conversation_history(self) -> list[dict]:
        """Get a shallow copy of the conversation history.

        Note: message objects are shared with the live conversation state.
        Do not mutate individual messages.
        """
        return list(self._wingman.conversation.messages)

    async def add_user_message(self, content: str):
        await self._wingman.add_user_message(content)

    async def add_assistant_message(self, content: str):
        await self._wingman.conversation.add_assistant_message(content)

    async def reset_conversation_history(self):
        await self._wingman.reset_conversation_history()

    # --- Audio ---

    async def play_to_user(self, text: str, no_interrupt: bool = False,
                           sound_config: "Optional[SoundConfig]" = None):
        await self._wingman.play_to_user(text, no_interrupt, sound_config)

    # --- Image generation ---

    async def generate_image(self, text: str) -> str:
        return await self._wingman.generate_image(text)

    # --- Secrets ---

    async def retrieve_secret(self, secret_name: str, errors: list = None) -> str | None:
        return await self._wingman.retrieve_secret(secret_name, errors or [])

    # --- Utilities ---

    def threaded_execution(self, func, *args):
        self._wingman.threaded_execution(func, *args)

    async def get_context(self) -> str:
        return await self._wingman.context_builder.build(
            skills=self._wingman.skills,
            skill_registry=self._wingman.skill_registry,
            conversation_summary=self._wingman.condenser.summary,
            persistent_memory_service=self._wingman.persistent_memory_service,
            messages=self._wingman.conversation.messages,
            config_dir_name=self._wingman.tower.config_dir.name if self._wingman.tower and self._wingman.tower.config_dir and self._wingman.tower.config_dir.name else None,
        )

    # --- Provider switching (for voice_changer and similar) ---

    async def switch_tts_provider(self, provider: "TtsProvider",
                                  errors: list = None) -> bool:
        """Hot-swap the TTS provider at runtime.

        Updates config.features.tts_provider and creates a new TTS instance.
        Used by voice_changer skill.
        """
        from services.provider_factory import ProviderFactory
        old_provider = self._wingman.config.features.tts_provider
        self._wingman.config.features.tts_provider = provider
        factory = ProviderFactory(
            config=self._wingman.config,
            settings=self._wingman.settings,
            secret_keeper=self._wingman.secret_keeper,
            shared_providers=self._wingman._shared_providers,
            wingman_name=self._wingman.name,
        )
        _errors = errors or []
        new_tts = await factory.create_tts(_errors)
        if new_tts:
            self._wingman.tts = new_tts
            return True
        # Roll back config on failure
        self._wingman.config.features.tts_provider = old_provider
        return False

    # --- Commands ---

    def get_command(self, command_name: str):
        """Delegate to command_executor for skills that need direct command lookup."""
        return self._wingman.command_executor.get_command(command_name)

    # --- Backward compatibility (temporary) ---
    # These provide access to registries that some skills currently use.
    # They should be replaced with proper facade methods in a future iteration.

    @property
    def tool_skills(self) -> dict:
        # tool_skills lives directly on the Wingman instance, not on tool_executor
        return self._wingman.tool_skills

    @property
    def mcp_registry(self):
        return self._wingman.mcp_registry

    @property
    def skill_registry(self):
        return self._wingman.skill_registry

    # Expose messages property for backward compat (quick_commands reads it)
    @property
    def messages(self) -> list:
        return self._wingman.conversation.messages

    # Expose local AI services for SkillLocalAI facade
    @property
    def local_ai_service(self):
        return self._wingman.local_ai_service

    @property
    def persistent_memory_service(self):
        return self._wingman.persistent_memory_service
