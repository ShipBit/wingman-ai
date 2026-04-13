"""System prompt assembly from template, skill prompts, TTS prompts, memory injection."""

import re
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from api.enums import (
    LogSource,
    LogType,
    TtsProvider,
    WingmanProTtsProvider,
)
from services.printr import Printr
from services.token_utils import count_tokens, truncate_to_tokens

if TYPE_CHECKING:
    from api.interface import SettingsConfig, WingmanConfig
    from services.persistent_memory import PersistentMemoryService
    from services.skill_registry import SkillRegistry
    from skills.skill_base import Skill

printr = Printr()


class ContextBuilder:
    def __init__(
        self,
        config: "WingmanConfig",
        settings: "SettingsConfig",
        wingman_name: str,
    ):
        self._config = config
        self._settings = settings
        self._wingman_name = wingman_name
        self._last_compiled_context: str = ""
        self._memory_recall_notified: bool = False

    async def build(
        self,
        skills: list["Skill"],
        skill_registry: "SkillRegistry",
        conversation_summary: str,
        persistent_memory_service: Optional["PersistentMemoryService"],
        messages: list,
        config_dir_name: Optional[str] = None,
    ) -> str:
        """Build the context and return it as a string.

        With progressive disclosure, only includes prompts from ACTIVATED skills.
        Skill prompts are auto-generated from @tool descriptions if no custom prompt is set.
        """
        skill_prompts = ""
        active_skill_names = skill_registry.active_skill_names

        for skill in skills:
            # Only include prompts from activated skills (in progressive mode)
            if skill.name not in active_skill_names:
                continue

            # Get custom prompt if set
            prompt = await skill.get_prompt()

            # Auto-generate prompt from tool descriptions if no custom prompt
            if not prompt:
                tools_desc = skill.get_tools_description()
                if tools_desc:
                    prompt = f"Available tools:\n{tools_desc}"

            if prompt:
                skill_prompts += "\n\n" + skill.name + "\n\n" + prompt

        # Get TTS prompt based on active TTS provider and user preference
        tts_prompt = ""
        if self._config.features.tts_provider == TtsProvider.ELEVENLABS:
            if (
                self._config.elevenlabs.use_tts_prompt
                and self._config.elevenlabs.tts_prompt
            ):
                tts_prompt = self._config.elevenlabs.tts_prompt
        elif self._config.features.tts_provider == TtsProvider.INWORLD or (
            self._config.features.tts_provider == TtsProvider.WINGMAN_PRO
            and self._config.wingman_pro.tts_provider == WingmanProTtsProvider.INWORLD
        ):
            if self._config.inworld.use_tts_prompt and self._config.inworld.tts_prompt:
                tts_prompt = self._config.inworld.tts_prompt
        elif self._config.features.tts_provider == TtsProvider.OPENAI_COMPATIBLE:
            if (
                self._config.openai_compatible_tts.use_tts_prompt
                and self._config.openai_compatible_tts.tts_prompt
            ):
                tts_prompt = self._config.openai_compatible_tts.tts_prompt

        # Add TTS header only if there's a prompt
        if tts_prompt:
            tts_prompt = "# TEXT-TO-SPEECH\n" + tts_prompt

        # Build user context with environment metadata
        user_context = self.build_user_context(config_dir_name=config_dir_name)

        # Sanity check: truncate if someone bypasses the client's 2048-token limit
        MAX_BACKSTORY_TOKENS = 2048
        backstory = self._config.prompts.backstory

        if backstory and count_tokens(backstory) > MAX_BACKSTORY_TOKENS:
            original_tokens = count_tokens(backstory)
            backstory = truncate_to_tokens(backstory, MAX_BACKSTORY_TOKENS)
            await printr.print_async(
                f"[{self._wingman_name}] Backstory will be truncated to {MAX_BACKSTORY_TOKENS} tokens for conversations (is {original_tokens}). "
                f"Your saved backstory is unchanged. Consider shortening it.",
                color=LogType.WARNING,
                source_name=self._wingman_name,
                source=LogSource.SYSTEM,
            )

        # Build conversation summary section
        conversation_summary_section = ""
        if conversation_summary:
            conversation_summary_section = (
                "# CONVERSATION SUMMARY\n"
                "The following is a summary of earlier parts of this conversation. "
                "Treat it as factual context — the user and you discussed these topics previously.\n\n"
                + conversation_summary
            )

        # Persistent memory injection
        persistent_memory_context = ""
        if persistent_memory_service and messages:
            # Use the most recent user message as the query
            last_user_msg = ""
            for msg in reversed(messages):
                role = (
                    msg.get("role")
                    if isinstance(msg, dict)
                    else getattr(msg, "role", None)
                )
                raw_content = (
                    msg.get("content", "")
                    if isinstance(msg, dict)
                    else getattr(msg, "content", "")
                )
                # Extract plain text from multimodal content (images etc.)
                content = self._extract_text_content(raw_content) if raw_content else ""
                if role == "user" and content:
                    last_user_msg = content
                    break
            if last_user_msg:
                try:
                    persistent_memory_context = (
                        await persistent_memory_service.build_memory_context(
                            last_user_msg
                        )
                    )
                    if persistent_memory_context and not self._memory_recall_notified:
                        self._memory_recall_notified = True
                        # Count restored fact lines (lines starting with "- ")
                        fact_count = sum(
                            1
                            for line in persistent_memory_context.splitlines()
                            if line.startswith("- ")
                        )
                        if fact_count > 0:
                            await printr.print_async(
                                f"Memory: {fact_count} {'memory' if fact_count == 1 else 'memories'} recalled",
                                color=LogType.MEMORY,
                                source_name=self._wingman_name,
                            )
                except Exception:
                    pass  # Don't let memory failures break conversation

        context = self._config.prompts.system_prompt.format(
            backstory=backstory,
            skills=skill_prompts,
            ttsprompt=tts_prompt,
            user_context=user_context,
            conversation_summary=conversation_summary_section,
        )

        # If the system prompt template doesn't include {conversation_summary},
        # append the summary at the end so it's never lost.
        if (
            conversation_summary_section
            and "{conversation_summary}" not in self._config.prompts.system_prompt
        ):
            context += "\n\n" + conversation_summary_section

        # Append persistent memory context
        if persistent_memory_context:
            context += "\n\n" + persistent_memory_context

        # Persistent memory tool instructions
        if persistent_memory_service:
            context += (
                "\n\n# PERSISTENT MEMORY\n"
                "You have persistent memory. Important facts and past conversation summaries "
                "are provided in the [Memory] sections above (if any). "
                "You can use the `memory_remember`, `memory_recall`, and `memory_forget` tools when the user "
                "explicitly asks you to remember, recall, or forget something. "
                "You don't need to use `memory_remember` for routine information — that is handled automatically."
            )

        self._last_compiled_context = context
        return context

    def get_last_context(self) -> str:
        """Return the last compiled system context (cached from the most recent LLM call)."""
        return self._last_compiled_context

    def build_user_context(
        self,
        config_dir_name: Optional[str] = None,
    ) -> str:
        """Build user context metadata for the system prompt.

        Includes timezone, config context, username, and wingman name.
        """
        context_parts = []
        backstory = self._config.prompts.backstory or ""
        backstory_lower = backstory.lower()

        # Date and timezone information
        try:
            now = datetime.now().astimezone()
            local_tz = now.tzinfo
            tz_name = str(local_tz)
            # Get UTC offset in a readable format
            utc_offset = now.strftime("%z")
            # Format as +HH:MM or -HH:MM
            if len(utc_offset) >= 5:
                utc_offset = f"{utc_offset[:3]}:{utc_offset[3:]}"
            # Include current date for relative date references ("last Sunday", "tomorrow", etc.)
            current_date = now.strftime(
                "%A, %B %d, %Y"
            )  # e.g., "Tuesday, December 09, 2025"
            context_parts.append(f"- Current date: {current_date}")
            context_parts.append(f"- Timezone: {tz_name} (UTC{utc_offset})")
        except Exception:
            context_parts.append("- Timezone: Unknown")

        # Config/context name (e.g., "Star Citizen", "Elite Dangerous")
        # This helps the LLM understand which game/context tools are relevant for
        if config_dir_name:
            context_parts.append(f"- Active context: {config_dir_name}")

        # Username (only if not explicitly named in backstory)
        if self._settings.user_name:
            # Check if username is mentioned in backstory as a standalone word
            name_pattern = r"\b" + re.escape(self._settings.user_name.lower()) + r"\b"
            if not re.search(name_pattern, backstory_lower):
                context_parts.append(
                    f"- User's name (default): {self._settings.user_name}"
                )

        # Wingman name - always include as it's useful context
        # The system prompt already tells LLM to prioritize backstory names
        if self._wingman_name:
            context_parts.append(f"- Your name (default): {self._wingman_name}")

        if context_parts:
            return "\n".join(context_parts)
        return "No additional context available."

    async def add_context(self, messages: list, context: str) -> None:
        """Insert the compiled context as the system message at the start of messages."""
        messages.insert(0, {"role": "system", "content": context})

    def reset_memory_notification(self) -> None:
        """Reset the memory recall notification flag (e.g., on conversation reset)."""
        self._memory_recall_notified = False

    @staticmethod
    def _extract_text_content(content) -> str:
        """Extract text from message content, handling both string and multimodal list formats."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            # Multimodal content: extract text parts only
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(part.get("text", ""))
                elif isinstance(part, str):
                    parts.append(part)
            return " ".join(parts)
        return ""
