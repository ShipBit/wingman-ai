"""
Conversation Manager Service

Manages conversation history (messages), pending tool calls, system context building,
and instant response generation for Wingmen.
"""

import json
import random
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from openai.types.chat import (
    ChatCompletionMessage,
    ChatCompletionMessageToolCall,
    ParsedFunction,
)
from api.enums import LogType, ConversationProvider, TtsProvider, WingmanProTtsProvider
from services.printr import Printr

if TYPE_CHECKING:
    from api.interface import WingmanConfig
    from services.capability_registry import CapabilityRegistry

printr = Printr()


class ConversationManager:
    """Manages conversation messages, context building, and instant responses.

    Responsibilities:
    - Message history management
    - Pending tool call tracking
    - System context/prompt generation
    - Instant response phrase generation
    - Skill hook integration
    """

    def __init__(self, skills: list, settings, wingman_name: str = "Wingman"):
        """Initialize the conversation manager.

        Args:
            skills (list): List of skills that may have message hooks.
            settings: Configuration settings (for debug mode).
            wingman_name (str): Name of the wingman (for context building).
        """
        self.skills = skills
        self.settings = settings
        self.wingman_name = wingman_name
        self.messages = []
        self.pending_tool_calls = []

    async def add_user_message(self, content: str, remember_messages: int = None):
        """Adds a user message to the conversation history after cleanup.

        Args:
            content (str): The message content to add.
            remember_messages (int, optional): Number of user messages to keep. If None, no cleanup.
        """
        # Call skill hooks (only for prepared/activated skills)
        for skill in self.skills:
            if skill.is_prepared:
                await skill.on_add_user_message(content)

        # Cleanup old messages if needed
        if remember_messages is not None:
            await self.cleanup(remember_messages)

        msg = {"role": "user", "content": content}
        self.messages.append(msg)

    async def add_assistant_message(
        self, message: ChatCompletionMessage, tool_calls: list = None
    ) -> None:
        """Adds an assistant message (with potential tool calls) to the conversation history.

        Args:
            message (ChatCompletionMessage): The message to add.
            tool_calls (list): The tool calls associated with the message.
        """
        # Call skill hooks (only for prepared/activated skills)
        for skill in self.skills:
            if skill.is_prepared:
                await skill.on_add_assistant_message(
                    message.content, message.tool_calls
                )

        # Do not tamper with this message as it will lead to 400 errors!
        self.messages.append(message)

        # Adding dummy tool responses to prevent corrupted message history on parallel requests
        if tool_calls:
            for tool_call in tool_calls:
                if not tool_call.id:
                    continue
                # Adding a dummy tool response to get updated later
                self.add_tool_response(tool_call, "Loading..", completed=False)

    async def add_simple_assistant_message(self, content: str):
        """Adds a simple assistant message (without tool calls) to the conversation history.

        Args:
            content (str): The message content to add.
        """
        # Call skill hooks (only for prepared/activated skills)
        for skill in self.skills:
            if skill.is_prepared:
                await skill.on_add_assistant_message(content, [])

        msg = {"role": "assistant", "content": content}
        self.messages.append(msg)

    async def add_forced_tool_calls(
        self,
        commands: list,
        conversation_provider: ConversationProvider,
        wingman_pro_deployment: str = None,
    ):
        """Adds forced assistant command calls to the conversation history.

        This is used for instant activation commands that should appear in the
        conversation history as if the LLM called them. The tool calls are marked
        as completed immediately with "OK" responses.

        Args:
            commands (list[CommandConfig]): The commands to add as forced tool calls.
            conversation_provider (ConversationProvider): The provider type (for ID generation).
            wingman_pro_deployment (str, optional): The deployment name for WingmanPro.
        """
        if not commands:
            return

        message = ChatCompletionMessage(
            content="",
            role="assistant",
            tool_calls=[],
        )

        for command in commands:
            tool_id = None
            if conversation_provider == ConversationProvider.OPENAI:
                tool_id = f"call_{str(uuid.uuid4()).replace('-', '')}"
            elif conversation_provider == ConversationProvider.WINGMAN_PRO:
                # Check if it's a GPT model
                if wingman_pro_deployment and "gpt" in wingman_pro_deployment.lower():
                    tool_id = f"call_{str(uuid.uuid4()).replace('-', '')}"
            elif conversation_provider == ConversationProvider.GOOGLE:
                tool_id = f"function-call-{''.join(random.choices('0123456789', k=20))}"

            # early exit for unsupported providers/models
            if not tool_id:
                return

            tool_call = ChatCompletionMessageToolCall(
                id=tool_id,
                function=ParsedFunction(
                    name="execute_command",
                    arguments=json.dumps({"command_name": command.name}),
                ),
                type="function",
            )
            message.tool_calls.append(tool_call)

        # Add message to conversation
        await self.add_assistant_message(message, message.tool_calls)
        # Mark all tool calls as completed with "OK" response
        if message.tool_calls:
            for tool_call in message.tool_calls:
                await self.update_tool_response(tool_call.id, "OK")

    def add_tool_response(
        self,
        tool_call: ChatCompletionMessageToolCall,
        response: str,
        completed: bool = True,
    ):
        """Adds a tool response to the conversation history.

        Args:
            tool_call (ChatCompletionMessageToolCall): The tool call to add the response for.
            response (str): The response content.
            completed (bool): Whether the tool call is completed. If False, it's added to pending_tool_calls.
        """
        msg = {"role": "tool", "content": response}
        if tool_call.id is not None:
            msg["tool_call_id"] = tool_call.id
        if tool_call.function.name is not None:
            msg["name"] = tool_call.function.name
        self.messages.append(msg)

        if tool_call.id and not completed:
            self.pending_tool_calls.append(tool_call.id)

    async def update_tool_response(self, tool_call_id: str, response: str) -> bool:
        """Updates a tool response in the conversation history.

        This also moves the message block to the end of the history if all tool responses are completed.

        Args:
            tool_call_id (str): The identifier of the tool call to update the response for.
            response (str): The new response to set.

        Returns:
            bool: True if the response was updated, False if the tool call was not found.
        """
        if not tool_call_id:
            return False

        completed = False
        index = len(self.messages)

        # Go through message history to find and update the tool call
        for message in reversed(self.messages):
            index -= 1
            if (
                self._get_message_role(message) == "tool"
                and message.get("tool_call_id") == tool_call_id
            ):
                message["content"] = str(response)
                if tool_call_id in self.pending_tool_calls:
                    self.pending_tool_calls.remove(tool_call_id)
                break
        if not index:
            return False

        # Find the assistant message that triggered the tool call
        for message in reversed(self.messages[:index]):
            index -= 1
            if self._get_message_role(message) == "assistant":
                break

        # Check if all tool calls are completed
        completed = True
        if self.messages[index].tool_calls:
            for tool_call in self.messages[index].tool_calls:
                if tool_call.id in self.pending_tool_calls:
                    completed = False
                    break
        if not completed:
            return True

        # Find the first user message(s) that triggered this assistant message
        index -= 1  # skip the assistant message
        for message in reversed(self.messages[:index]):
            index -= 1
            if self._get_message_role(message) != "user":
                index += 1
                break

        # Built message block to move
        start_index = index
        end_index = start_index
        reached_tool_call = False
        for message in self.messages[start_index:]:
            if not reached_tool_call and self._get_message_role(message) == "tool":
                reached_tool_call = True
            if reached_tool_call and self._get_message_role(message) == "user":
                end_index -= 1
                break
            end_index += 1
        if end_index == len(self.messages):
            end_index -= 1  # loop ended at the end of the message history, so we have to go back one index
        message_block = self.messages[start_index : end_index + 1]

        # Check if the message block is already at the end
        if end_index == len(self.messages) - 1:
            return True

        # Move message block to the end
        del self.messages[start_index : end_index + 1]
        self.messages.extend(message_block)

        if self.settings.debug_mode:
            await printr.print_async(
                "Moved message block to the end.", color=LogType.INFO
            )

        return True

    async def cleanup(self, remember_messages: int):
        """Cleans up the conversation history by removing old messages beyond the keep limit.

        Args:
            remember_messages (int): Number of user messages to keep.

        Returns:
            int: Number of messages deleted.
        """
        if remember_messages is None or len(self.messages) == 0:
            return 0  # Configuration not set, nothing to delete.

        # Find the cutoff index where to end deletion, making sure to only count 'user' messages
        # towards the limit starting with newest messages.
        cutoff_index = len(self.messages)
        user_message_count = 0
        for message in reversed(self.messages):
            if self._get_message_role(message) == "user":
                user_message_count += 1
                if user_message_count == remember_messages:
                    break  # Found the cutoff point.
            cutoff_index -= 1

        # If messages below the keep limit, don't delete anything.
        if user_message_count < remember_messages:
            return 0

        total_deleted_messages = cutoff_index  # Messages to delete.

        # Remove the pending tool calls that are no longer needed.
        for message in self.messages[:cutoff_index]:
            if (
                self._get_message_role(message) == "tool"
                and message.get("tool_call_id") in self.pending_tool_calls
            ):
                self.pending_tool_calls.remove(message.get("tool_call_id"))
                if self.settings.debug_mode:
                    await printr.print_async(
                        f"Removing pending tool call {message.get('tool_call_id')} due to message history clean up.",
                        color=LogType.WARNING,
                    )

        # Perform the deletion.
        del self.messages[:cutoff_index]

        if self.settings.debug_mode and total_deleted_messages > 0:
            await printr.print_async(
                f"Removed {total_deleted_messages} messages from conversation history.",
                color=LogType.INFO,
            )

        return total_deleted_messages

    def reset(self):
        """Resets the conversation history and pending tool calls."""
        self.messages.clear()
        self.pending_tool_calls.clear()

    def get_messages_copy(self) -> list:
        """Returns a copy of the messages list.

        Returns:
            list: A shallow copy of the messages list.
        """
        return self.messages.copy()

    # ─────────────────── Context Building ─────────────────── #

    async def build_system_context(
        self,
        config: "WingmanConfig",
        capability_registry: "CapabilityRegistry",
        tower_config_name: Optional[str] = None,
    ) -> str:
        """Build the complete system prompt with backstory, skills, TTS instructions, and metadata.

        Args:
            config: Wingman configuration with prompts and settings
            capability_registry: Registry containing active skills and MCPs
            tower_config_name: Name of the config directory (e.g., "Star Citizen")

        Returns:
            Complete system context string
        """
        # Build skill prompts (only for activated skills)
        skill_prompts = ""
        active_skill_names = set()

        # Get active skills from capability registry's skill registry
        if hasattr(capability_registry, "skill_registry"):
            active_skill_names = capability_registry.skill_registry.active_skill_names

        for skill in self.skills:
            if skill.name not in active_skill_names:
                continue

            skill_prompt = skill.config.prompt or ""
            if not skill_prompt and skill.get_tools():
                # Auto-generate prompt from tool descriptions
                tool_descriptions = []
                for tool in skill.get_tools():
                    tool_descriptions.append(
                        f"- {tool.get('function', {}).get('name', 'unknown')}: "
                        f"{tool.get('function', {}).get('description', 'No description')}"
                    )
                skill_prompt = f"You have access to these tools:\n" + "\n".join(
                    tool_descriptions
                )

            if skill_prompt:
                skill_prompts += f"\n\n## {skill.config.display_name}\n{skill_prompt}"

        # Build TTS-specific prompts
        tts_prompt = ""
        if config.features.tts_provider == TtsProvider.ELEVENLABS:
            if (
                hasattr(config, "elevenlabs")
                and config.elevenlabs.use_tts_prompt
                and config.elevenlabs.tts_prompt
            ):
                # Use custom prompt if configured
                tts_prompt = config.elevenlabs.tts_prompt
            elif (
                hasattr(config, "elevenlabs")
                and config.elevenlabs.tts_use_voice_effects
            ):
                # Use default voice effects prompt
                tts_prompt = self._get_elevenlabs_prompt()
        elif config.features.tts_provider == TtsProvider.INWORLD or (
            config.features.tts_provider == TtsProvider.WINGMAN_PRO
            and hasattr(config, "wingman_pro")
            and config.wingman_pro.tts_provider == WingmanProTtsProvider.INWORLD
        ):
            if (
                hasattr(config, "inworld")
                and config.inworld.use_tts_prompt
                and config.inworld.tts_prompt
            ):
                # Use custom prompt if configured
                tts_prompt = config.inworld.tts_prompt
            else:
                # Use default Inworld emotions prompt
                tts_prompt = self._get_inworld_prompt()
        elif config.features.tts_provider == TtsProvider.OPENAI_COMPATIBLE:
            if (
                hasattr(config, "openai_compatible_tts")
                and config.openai_compatible_tts.use_tts_prompt
                and config.openai_compatible_tts.tts_prompt
            ):
                # Use custom prompt if configured
                tts_prompt = config.openai_compatible_tts.tts_prompt
            elif (
                hasattr(config, "openai_compatible_tts")
                and config.openai_compatible_tts.supports_audio_markups
            ):
                # Use default markups prompt
                tts_prompt = self._get_openai_compatible_prompt()

        # Add TTS header if there's a prompt
        if tts_prompt:
            tts_prompt = f"\n\n## Text-to-Speech Instructions\n{tts_prompt}"

        # Build user metadata context
        user_context = self._build_user_metadata(config, tower_config_name)

        # Assemble final context
        context = config.prompts.system_prompt.format(
            backstory=config.prompts.backstory,
            skills=skill_prompts,
            ttsprompt=tts_prompt,
            user_context=user_context,
        )

        return context

    def _build_user_metadata(
        self,
        config: "WingmanConfig",
        tower_config_name: Optional[str] = None,
    ) -> str:
        """Build user metadata for system context.

        Includes timezone, config name, username, and wingman name.

        Args:
            config: Wingman configuration
            tower_config_name: Name of the config directory

        Returns:
            Formatted metadata string
        """
        context_parts = []
        backstory = config.prompts.backstory or ""
        backstory_lower = backstory.lower()

        # Date and timezone
        try:
            now = datetime.now()
            local_tz = now.astimezone().tzinfo
            timezone_name = local_tz.tzname(now) if local_tz else "Unknown"

            context_parts.append(
                f"Current date and time: {now.strftime('%Y-%m-%d %H:%M:%S')} ({timezone_name})"
            )
        except Exception:
            pass

        # Config/context name (helps LLM understand game/domain context)
        if tower_config_name:
            context_parts.append(f"Current context/game: {tower_config_name}")

        # Username (only if not explicitly mentioned in backstory)
        if self.settings.user_name:
            user_name_lower = self.settings.user_name.lower()
            if user_name_lower not in backstory_lower:
                context_parts.append(f"User's name: {self.settings.user_name}")

        # Wingman name
        if self.wingman_name:
            context_parts.append(f"Your name: {self.wingman_name}")

        if context_parts:
            return "\n".join(context_parts)
        return "No additional context available."

    def _get_elevenlabs_prompt(self) -> str:
        """Get ElevenLabs TTS prompt for voice effects."""
        return """You can use special TTS sound effects within your answers by wrapping them in asterisks like this:
*clears throat* or *sighs*.
Using sound effects makes your answers more realistic and alive.
Always use appropriate sound effects if they match the context and emotion of your answer.
Only use short sound effects that can be spoken in less than a second.
Do not use asterisks for other purposes."""

    def _get_inworld_prompt(self) -> str:
        """Get Inworld TTS prompt for emotions."""
        return """You can express emotions in your speech using Inworld emotion markups.
Wrap emotion names in angle brackets like <anger>, <joy>, <sadness>, etc.
The emotion will be applied to all text that follows it until a new emotion is specified.
Examples:
- "<anger>I can't believe this happened!"
- "<joy>That's wonderful news!"
- "<sadness>I'm sorry to hear that."
Use emotions naturally to make your responses more expressive and human-like.
Do not use angle brackets for other purposes."""

    def _get_openai_compatible_prompt(self) -> str:
        """Get OpenAI-compatible TTS prompt for audio markups."""
        return """Your TTS provider supports audio markups for enhanced speech.
You can use special annotations to control how text is spoken.
Consult your TTS provider's documentation for supported markup syntax.
Use markups sparingly to enhance important parts of your response."""

        # ─────────────────── Instant Responses ─────────────────── #

        # Instant response feature removed in v2.1.0 for simplification

        # get_random_filler removed in v2.1.0

        # Keep only last 2 used indices
        if len(self.last_used_instant_responses) > 2:
            self.last_used_instant_responses = self.last_used_instant_responses[-2:]

        # Get a random response that wasn't recently used
        random_index = random.randint(0, len(self.instant_responses) - 1)
        while random_index in self.last_used_instant_responses:
            random_index = random.randint(0, len(self.instant_responses) - 1)

        self.last_used_instant_responses.append(random_index)
        return self.instant_responses[random_index]
        return self.messages.copy()

    def _get_message_role(self, message) -> str:
        """Gets the role of a message, handling both dict and object formats.

        Args:
            message: The message to get the role from.

        Returns:
            str: The role of the message.
        """
        if isinstance(message, dict):
            return message.get("role", "")
        return getattr(message, "role", "")
