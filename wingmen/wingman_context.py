"""Controlled interface for skills (the `self.wingman` a Skill receives).

A fully closed, feature-driven surface: skills read everything through curated
capabilities and can only change what is safe. The underlying Wingman is private
(name-mangled) — there is no raw passthrough. This is API hygiene + guidance, not a
security sandbox (skills run in-process with full Python).
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from api.interface import WingmanConfig
    from wingmen.facade import (
        SkillAi, SkillAudio, SkillCommands, SkillTools, SkillTts,
        SkillLocalAiView, SkillMemory, SkillConversation, SkillSecrets, SkillSkills,
        SkillSettings,
    )
    from wingmen.wingman import Wingman


# Removed v2 members -> the sanctioned v3 capability to use instead (spec §8). Touching
# any of these on self.wingman raises a FacadeError naming the replacement.
_REMOVED_MEMBERS = {
    "llm_call": "Use self.wingman.ai.generate(...).",
    "actual_llm_call": "Use self.wingman.ai.generate(...).",
    "audio_player": "Use self.wingman.audio.* (is_playing, play, stop, on_playback_*).",
    "audio_library": "Use self.wingman.audio.play(...) / .stop(...).",
    "tool_skills": "Use self.wingman.tools.* (source/has/invoke) or self.wingman.skills.active().",
    "mcp_registry": "Use self.wingman.tools.servers() / .source(name) / .invoke(name, args).",
    "skill_registry": "Use self.wingman.skills.active() / .has(name).",
    "registry": "Use self.wingman.tools.* (names/has/source/describe/all/servers/invoke).",
    "tower": "Use self.wingman.commands.save().",
    "secret_keeper": "Use self.wingman.secrets.retrieve(name).",
    "messages": "Use self.wingman.conversation.history().",
    "get_command": "Use self.wingman.commands.get(name).",
    "get_context": "Removed (internal, no consumer).",
    "local_ai_service": "Use self.wingman.local_ai.",
    "persistent_memory_service": "Use self.wingman.memory.",
    "play_to_user": "Use self.wingman.tts.speak(text, interrupt=...).",
    "generate_image": "Use self.wingman.ai.generate_image(prompt).",
    "get_conversation_history": "Use self.wingman.conversation.history().",
    "add_user_message": "Use self.wingman.conversation.add_user(content).",
    "add_assistant_message": "Use self.wingman.conversation.add_assistant(content).",
    "reset_conversation_history": "Use self.wingman.conversation.reset().",
    "retrieve_secret": "Use self.wingman.secrets.retrieve(name).",
    "threaded_execution": "Use self.wingman.run_in_thread(fn, *args).",
    "switch_tts_provider": "Removed; use self.wingman.tts.set_voice(...) (no provider switching).",
}


class WingmanContext:
    """What skills see (`self.wingman`). Feature namespaces only — nothing raw."""

    def __init__(self, wingman: "Wingman"):
        # Name-mangled: skills cannot reach the raw Wingman via ctx._wingman by accident.
        self.__wingman = wingman
        self.__ai = None
        self.__local_ai = None
        self.__tts = None
        self.__audio = None
        self.__commands = None
        self.__tools = None
        self.__conversation = None
        self.__memory = None
        self.__secrets = None
        self.__skills = None
        self.__settings = None

    # --- guided failure for removed v2 members (spec §8: helpful, not silent) ---

    def __getattr__(self, name: str) -> Any:
        # __getattr__ only fires for names not found normally (the sub-facades are real
        # properties, so they never land here). A v2 skill touching a removed member gets
        # a FacadeError naming the replacement instead of a bare AttributeError.
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        replacement = _REMOVED_MEMBERS.get(name)
        if replacement is not None:
            from wingmen.facade import FacadeError
            raise FacadeError(
                f"`self.wingman.{name}` was removed in the v3 Skill API. {replacement} "
                f"See skills/MIGRATING-TO-V3.md."
            )
        raise AttributeError(name)

    # --- identity + config (read-only) ---

    @property
    def name(self) -> str:
        return self.__wingman.name

    @property
    def config(self) -> "WingmanConfig":
        """Live, read-only view of the wingman config. Writing raises FacadeError —
        use a sanctioned capability (ctx.tts.set_voice, ctx.commands.*, ...)."""
        from wingmen.facade import ReadOnlyConfigView
        return ReadOnlyConfigView(self.__wingman.config)

    @property
    def settings(self) -> "SkillSettings":
        if self.__settings is None:
            from wingmen.facade import SkillSettings
            self.__settings = SkillSettings(self.__wingman)
        return self.__settings

    # --- feature sub-facades ---

    @property
    def ai(self) -> "SkillAi":
        if self.__ai is None:
            from wingmen.facade import SkillAi
            self.__ai = SkillAi(self.__wingman)
        return self.__ai

    @property
    def local_ai(self) -> "SkillLocalAiView":
        if self.__local_ai is None:
            from wingmen.facade import SkillLocalAiView
            from services.skill_local_ai import SkillLocalAI
            # SkillLocalAI only reads local_ai_service/name/persistent_memory_service,
            # all present on the raw Wingman — so the context stays fully closed.
            self.__local_ai = SkillLocalAiView(SkillLocalAI(self.__wingman))
        return self.__local_ai

    @property
    def tts(self) -> "SkillTts":
        if self.__tts is None:
            from wingmen.facade import SkillTts
            self.__tts = SkillTts(self.__wingman)
        return self.__tts

    @property
    def audio(self) -> "SkillAudio":
        if self.__audio is None:
            from wingmen.facade import SkillAudio
            self.__audio = SkillAudio(self.__wingman)
        return self.__audio

    @property
    def commands(self) -> "SkillCommands":
        if self.__commands is None:
            from wingmen.facade import SkillCommands
            self.__commands = SkillCommands(self.__wingman)
        return self.__commands

    @property
    def tools(self) -> "SkillTools":
        if self.__tools is None:
            from wingmen.facade import SkillTools
            self.__tools = SkillTools(self.__wingman)
        return self.__tools

    @property
    def conversation(self) -> "SkillConversation":
        if self.__conversation is None:
            from wingmen.facade import SkillConversation
            self.__conversation = SkillConversation(self.__wingman)
        return self.__conversation

    @property
    def memory(self) -> "SkillMemory":
        if self.__memory is None:
            from wingmen.facade import SkillMemory
            from services.skill_local_ai import SkillLocalAI
            self.__memory = SkillMemory(SkillLocalAI(self.__wingman))
        return self.__memory

    @property
    def secrets(self) -> "SkillSecrets":
        if self.__secrets is None:
            from wingmen.facade import SkillSecrets
            self.__secrets = SkillSecrets(self.__wingman)
        return self.__secrets

    @property
    def skills(self) -> "SkillSkills":
        if self.__skills is None:
            from wingmen.facade import SkillSkills
            self.__skills = SkillSkills(self.__wingman)
        return self.__skills

    # --- utility ---

    def run_in_thread(self, function, *args):
        """Run a blocking callable off the event loop."""
        return self.__wingman.threaded_execution(function, *args)
