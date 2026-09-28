"""Manages the conversation message list, tool responses, and history cleanup."""

import json
import random
import re
import uuid
from bisect import bisect_right
from typing import TYPE_CHECKING, Callable, Mapping, Optional

from openai.types.chat import (
    ChatCompletionMessage,
    ChatCompletionMessageToolCall,
    ParsedFunction,
)

from api.enums import ConversationProvider, LogSource, LogType
from services.printr import Printr
from services.token_utils import count_tokens

if TYPE_CHECKING:
    from api.interface import CommandConfig, SettingsConfig, WingmanConfig

printr = Printr()

# How long tool output stays in the history, counted in user messages that have
# arrived since the tool ran. The output of the last KEEP_TOOL_TURNS turns is never
# touched: the pilot asks "which of those is cheapest?" or "put one more stop
# into the table" a few messages later, and the model needs the real data for
# that, not a guess. Older output may stay too, as long as it adds up to no more
# than _OLD_BUDGET tokens and is no older than _MAX_AGE turns.
KEEP_TOOL_TURNS = 4
_OLD_BUDGET = 12_000
_MAX_AGE = 10

# What is left of a response once it is cleared.
_CLEARED_NOTE = (
    "[Tool output removed from history (~{original} tokens{tool}). "
    "Call the tool again if it is needed.]"
)
_CLEARED_NOTE_RE = re.compile(
    r"^\[Tool output removed from history \(~(\d+) tokens[^)]*\)\. "
    r"Call the tool again if it is needed\.\]$"
)


class ConversationManager:
    """Owns the conversation message list, tool-response bookkeeping, and
    history cleanup / trimming logic.
    """

    def __init__(
        self,
        config: "WingmanConfig",
        settings: "SettingsConfig",
        wingman_name: str,
    ):
        self._config = config
        self._settings = settings
        self._wingman_name = wingman_name
        self.messages: list = []
        self.pending_tool_calls: list[str] = []
        self.conversation_summary: str = ""

        # Skill state — set once via set_skill_context(); avoids per-call kwargs
        self._skills: list = []
        self._skill_registry = None
        self._tool_skills: dict = {}

    def set_skill_context(
        self,
        skills: list,
        skill_registry,
        tool_skills: dict,
    ) -> None:
        """Wire current skill state into the manager.

        Called by WingmanSkillManager after init/enable/disable so per-call
        methods don't need to receive it as arguments.
        """
        self._skills = skills
        self._skill_registry = skill_registry
        self._tool_skills = tool_skills

    # ------------------------------------------------------------------
    # GPT / assistant response helpers
    # ------------------------------------------------------------------

    async def add_gpt_response(
        self,
        message,
        tool_calls,
    ) -> tuple[bool, bool]:
        """Adds a message from GPT to the conversation history as well as
        adding dummy tool responses for any tool calls.

        Args:
            message (dict | ChatCompletionMessage): The message to add.
            tool_calls (list): The tool calls associated with the message.
        """
        # call skill hooks (only for prepared/activated skills)
        for skill in self._skills:
            if skill.is_prepared:
                await skill.on_add_assistant_message(
                    message.content, message.tool_calls
                )

        # do not tamper with this message as it will lead to 400 errors!
        self.messages.append(message)

        # adding dummy tool responses to prevent corrupted message history on parallel requests
        # and checks if waiting response should be played
        unique_tools = {}
        is_waiting_response_needed = False
        is_summarize_needed = False

        if tool_calls:
            for tool_call in tool_calls:
                if not tool_call.id:
                    continue
                # adding a dummy tool response to get updated later
                self.add_tool_response(tool_call, "Loading..", False)

                function_name = tool_call.function.name

                # Meta-tools (search_skills, activate_skill, etc.) always need a follow-up
                # LLM call so it can use the newly activated tools
                if self._skill_registry and self._skill_registry.is_meta_tool(function_name):
                    is_summarize_needed = True
                elif function_name in self._tool_skills:
                    skill = self._tool_skills[function_name]
                    if await skill.is_waiting_response_needed(function_name):
                        is_waiting_response_needed = True
                    if await skill.is_summarize_needed(function_name):
                        is_summarize_needed = True

                unique_tools[function_name] = True

            if len(unique_tools) == 1 and "execute_command" in unique_tools:
                is_waiting_response_needed = True

        return is_waiting_response_needed, is_summarize_needed

    # ------------------------------------------------------------------
    # Tool response management
    # ------------------------------------------------------------------

    def add_tool_response(
        self, tool_call, response: str, completed: bool = True
    ):
        """Adds a tool response to the conversation history.

        Args:
            tool_call (dict|ChatCompletionMessageToolCall): The tool call to add the dummy response for.
            response (str): The response content.
            completed (bool): Whether the tool call is complete.
        """
        msg = {"role": "tool", "content": response}
        if tool_call.id is not None:
            msg["tool_call_id"] = tool_call.id
        if tool_call.function.name is not None:
            msg["name"] = tool_call.function.name
        self.messages.append(msg)

        if tool_call.id and not completed:
            self.pending_tool_calls.append(tool_call.id)

    async def update_tool_response(self, tool_call_id, response) -> bool:
        """Updates a tool response in the conversation history.

        Args:
            tool_call_id (str): The identifier of the tool call to update the response for.
            response (str): The new response to set.

        Returns:
            bool: True if the response was updated, False if the tool call was not found.
        """
        if not tool_call_id:
            return False

        index = len(self.messages)

        # go through message history to find and update the tool call
        for message in reversed(self.messages):
            index -= 1
            if (
                self.get_message_role(message) == "tool"
                and message.get("tool_call_id") == tool_call_id
            ):
                message["content"] = str(response)
                if tool_call_id in self.pending_tool_calls:
                    self.pending_tool_calls.remove(tool_call_id)
                return True

        return False

    @staticmethod
    def message_chars(msg) -> int:
        """How long a message is as JSON — the unit the Wingman Pro backend
        measures a request in. Assistant replies are kept as the SDK's objects,
        the rest as dicts."""
        if isinstance(msg, Mapping):
            return len(json.dumps(msg, ensure_ascii=False, default=str))
        dump = getattr(msg, "model_dump_json", None)
        if dump:
            return len(dump(exclude_none=True))
        return len(str(msg))

    def drop_oldest_turns(self, chars_to_free: int) -> int:
        """Remove whole turns from the front until ``chars_to_free`` are gone.

        The last resort when a request would be too big to send: without
        condensation nothing else shortens the history (see
        ``trim_tool_responses``). A turn starts at a user message, so a tool call
        and its responses always go together. The latest turn is never touched,
        even if that frees less than asked — it holds the question being answered.

        Returns how many messages were removed.
        """
        if chars_to_free <= 0:
            return 0
        user_indices = [
            i for i, m in enumerate(self.messages) if self.get_message_role(m) == "user"
        ]
        if len(user_indices) < 2:
            return 0

        cut = 0
        freed = 0
        start = 0
        for next_turn in user_indices[1:]:
            freed += sum(self.message_chars(m) for m in self.messages[start:next_turn])
            cut = start = next_turn
            if freed >= chars_to_free:
                break

        del self.messages[:cut]
        return cut

    def _tool_call_names(self) -> dict[str, str]:
        """``tool_call_id`` → function name, from the assistant messages."""
        names: dict[str, str] = {}
        for msg in self.messages:
            calls = (
                msg.get("tool_calls")
                if isinstance(msg, Mapping)
                else getattr(msg, "tool_calls", None)
            )
            for call in calls or []:
                if isinstance(call, Mapping):
                    call_id = call.get("id")
                    name = (call.get("function") or {}).get("name")
                else:
                    call_id = getattr(call, "id", None)
                    function = getattr(call, "function", None)
                    name = getattr(function, "name", None)
                if call_id and name:
                    names[call_id] = name
        return names

    async def trim_tool_responses(self, is_condensing: bool = False):
        """Clear tool output the conversation has moved well past.

        A skill can hand back an 8,000-token price table. The model needs it for
        more than the one answer: a few messages later the pilot asks for one
        more stop on the trading route, or wants the overlay table back the way
        it was. So the output of the last ``KEEP_TOOL_TURNS`` user turns always stays
        complete. Only after that is it replaced by a one-line placeholder that
        names the size and the tool.

        Clearing happens in batches, not one turn at a time. Older output stays
        until it adds up to more than ``_OLD_BUDGET`` tokens or one response is
        more than ``_MAX_AGE`` turns old; then everything older than
        ``KEEP_TOOL_TURNS`` goes in one pass. Rewriting a message invalidates the
        provider's prompt cache from that message on, so clearing one response
        per turn would break the cache every turn. A batch breaks it once every
        few turns and keeps more data around in between.

        With ``condense_conversation`` off nothing is cleared: the user turned
        off the automatic shortening of the history, and this is part of it.
        Single responses are still capped when they come in
        (``skill_max_input_tokens``), which is a separate setting.

        Args:
            is_condensing: Whether condensation is currently running (suppresses
                broadcast to avoid interfering with its own cycle).
        """
        features = getattr(self._config, "features", None)
        if features is not None and not features.condense_conversation:
            return

        user_indices = [
            i for i, m in enumerate(self.messages) if self.get_message_role(m) == "user"
        ]
        old: list[tuple[int, int]] = []  # (message index, tokens)
        old_tokens = 0
        oldest_age = 0
        for index, msg in enumerate(self.messages):
            if self.get_message_role(msg) != "tool":
                continue
            if msg.get("tool_call_id") in self.pending_tool_calls:
                continue
            content = msg.get("content", "")
            if not content or not isinstance(content, str):
                continue
            if _CLEARED_NOTE_RE.match(content):
                continue
            age = len(user_indices) - bisect_right(user_indices, index)
            if age < KEEP_TOOL_TURNS:
                continue
            tokens = count_tokens(content)
            old.append((index, tokens))
            old_tokens += tokens
            oldest_age = max(oldest_age, age)

        if not old or (old_tokens <= _OLD_BUDGET and oldest_age <= _MAX_AGE):
            return

        tool_names = self._tool_call_names()
        total_tokens_saved = 0
        cleared_tools: dict[str, int] = {}
        for index, tokens in old:
            msg = self.messages[index]
            name = tool_names.get(msg.get("tool_call_id")) or msg.get("name")
            msg["content"] = _CLEARED_NOTE.format(
                original=tokens, tool=f" from {name}" if name else ""
            )
            total_tokens_saved += max(0, tokens - count_tokens(msg["content"]))
            cleared_tools[name or "unknown tool"] = cleared_tools.get(name or "unknown tool", 0) + 1

        # Every clearing is logged, whatever its size: the model loses data here,
        # and "why did it forget the price?" has to be answerable from the log.
        tools = ", ".join(
            f"{name} ×{count}" if count > 1 else name
            for name, count in cleared_tools.items()
        )
        await printr.print_async(
            f"Removed {len(old)} tool responses older than {KEEP_TOOL_TURNS} turns "
            f"from the history (~{total_tokens_saved:,} tokens): {tools}. The tool "
            f"data of the last {KEEP_TOOL_TURNS} turns stays complete.",
            color=LogType.INFO,
            source=LogSource.WINGMAN,
            source_name=self._wingman_name,
        )

        # Notify the client when significant trimming occurs so the UI can
        # show a "Show history" indicator explaining the token drop.
        # Skip if condensation is already running to avoid interfering with
        # its own started/finished broadcast cycle.
        if (
            total_tokens_saved > 1000
            and printr._connection_manager
            and not is_condensing
        ):
            from api.commands import ConversationCondensationCommand

            if self.conversation_summary:
                summary = (
                    f"{self.conversation_summary}\n\n---\n\n"
                    f"[Older tool responses removed — ~{total_tokens_saved:,} tokens saved]"
                )
            else:
                summary = (
                    f"Tool responses older than {KEEP_TOOL_TURNS} turns were removed "
                    f"from the history.\n"
                    f"~{total_tokens_saved:,} tokens saved.\n\n"
                    f"The tool data of the last {KEEP_TOOL_TURNS} turns stays complete. "
                    f"Older data is removed once it piles up, to keep the "
                    f"conversation context efficient."
                )

            await printr._connection_manager.broadcast(
                ConversationCondensationCommand(
                    wingman_name=self._wingman_name,
                    status="finished",
                    estimated_tokens_saved=total_tokens_saved,
                    summary_text=summary,
                )
            )

    # ------------------------------------------------------------------
    # User / assistant message management
    # ------------------------------------------------------------------

    async def add_user_message(
        self,
        content: str,
        images: list[tuple[str, str]] = None,
        condense_fn: Optional[Callable] = None,
    ):
        """Shortens the conversation history if needed and adds a user message to it.

        Args:
            content (str): The message content to add.
            images (list[tuple[str, str]]): Optional list of (base64_data, mime_type) tuples to attach.
            condense_fn: Optional async callable invoked after cleanup (``_maybe_condense_history``).
        """
        # call skill hooks (only for prepared/activated skills)
        for skill in self._skills:
            if skill.is_prepared:
                await skill.on_add_user_message(content)

        if images:
            msg_content = []
            for img_b64, mime in images:
                msg_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{img_b64}",
                        "detail": "auto",
                    },
                })
            msg_content.append({"type": "text", "text": content})
            msg = {"role": "user", "content": msg_content}
        else:
            msg = {"role": "user", "content": content}
        if condense_fn:
            await condense_fn()
        self.messages.append(msg)

    async def add_assistant_message(
        self, content: str
    ):
        """Adds an assistant message to the conversation history.

        Args:
            content (str): The message content to add.
        """
        # call skill hooks (only for prepared/activated skills)
        for skill in self._skills:
            if skill.is_prepared:
                await skill.on_add_assistant_message(content, [])

        msg = {"role": "assistant", "content": content}
        self.messages.append(msg)

    async def add_forced_assistant_command_calls(
        self,
        commands: list["CommandConfig"],
    ):
        """Adds forced assistant command calls to the conversation history.

        Args:
            commands (list[CommandConfig]): The commands to add.
        """

        if not commands:
            return

        message = ChatCompletionMessage(
            content="",
            role="assistant",
            tool_calls=[],
        )
        tool_id_to_command = {}
        for command in commands:
            tool_id = None
            if (
                self._config.features.conversation_provider
                == ConversationProvider.OPENAI
            ) or (
                # Wingman Pro serves OpenAI models through the gateway, so the
                # tool call ids are OpenAI-shaped. This used to sniff the model
                # name for "gpt", which stopped working when the config started
                # holding an alias ("default", "fast") instead.
                self._config.features.conversation_provider
                == ConversationProvider.WINGMAN_PRO
            ):
                tool_id = f"call_{str(uuid.uuid4()).replace('-', '')}"
            elif (
                self._config.features.conversation_provider
                == ConversationProvider.GOOGLE
            ):
                if (
                    self._config.google.conversation_model.startswith("gemini-3")
                    or self._config.google.conversation_model == "gemini-flash-latest"
                    or self._config.google.conversation_model == "gemini-pro-latest"
                    or self._config.google.conversation_model
                    == "gemini-flash-lite-latest"
                ):
                    # gemini 3+ (latest = 3+) needs a thought signature like this, but we cant fake it:
                    # {
                    #     'model_extra': {
                    #         'extra_content': {
                    #             'google': {
                    #                 'thought_signature': 'EjQKMgFyyNp8mNe4bQmQhOua7gGMH0C9RubFWewy6BzYZJs5f4RqDb8CaiR4gjLxoM1iQqP4'
                    #             }
                    #         }
                    #     }
                    # }
                    return
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
            tool_id_to_command[tool_id] = command

        await self.add_gpt_response(
            message, message.tool_calls
        )
        for tool_call in message.tool_calls:
            command = tool_id_to_command[tool_call.id]
            await self.update_tool_response(
                tool_call.id, command.additional_context or "OK"
            )

    # ------------------------------------------------------------------
    # History cleanup and token estimation
    # ------------------------------------------------------------------

    def estimate_tokens(self) -> int:
        """Estimate the total token count of the current conversation history."""
        return sum(count_tokens(self._message_text_content(m)) for m in self.messages)

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    async def reset(self):
        """Resets the conversation message list and summary.

        Note: skill/MCP registry resets and memory extraction are the
        responsibility of the caller (the Wingman) since ConversationManager
        does not own those services.
        """
        self.messages = []
        self.conversation_summary = ""

    # ------------------------------------------------------------------
    # Message serialisation helpers
    # ------------------------------------------------------------------

    def get_conversation_messages(self, strip_nulls: bool = True) -> list[dict]:
        """Return the conversation messages as a list of plain dicts for debugging."""

        def _strip_none(obj):
            if isinstance(obj, dict):
                return {k: _strip_none(v) for k, v in obj.items() if v is not None}
            if isinstance(obj, list):
                return [_strip_none(item) for item in obj]
            return obj

        result = []
        for msg in self.messages:
            if hasattr(msg, "model_dump"):
                d = msg.model_dump()
            else:
                d = msg
            if strip_nulls:
                d = _strip_none(d)
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # Text extraction / conversion helpers
    # ------------------------------------------------------------------

    def _extract_text_content(self, content) -> str:
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

    def _message_text_content(self, msg) -> str:
        """Extract text content from a message for token estimation."""
        if isinstance(msg, Mapping):
            return self._extract_text_content(msg.get("content", "")) or ""
        elif hasattr(msg, "content"):
            return self._extract_text_content(msg.content) or ""
        return ""

    def _messages_to_text(self, messages: list) -> str:
        """Convert a list of conversation messages to plain text for summarization."""
        lines = []
        for msg in messages:
            role = self.get_message_role(msg)
            content = ""
            if isinstance(msg, Mapping):
                content = self._extract_text_content(msg.get("content", ""))
            elif hasattr(msg, "content"):
                content = self._extract_text_content(msg.content) or ""

            if role == "user":
                lines.append(f"User: {content}")
            elif role == "assistant":
                if content:
                    lines.append(f"Assistant: {content}")
                # Include tool call info
                tool_calls = None
                if isinstance(msg, Mapping):
                    tool_calls = msg.get("tool_calls")
                elif hasattr(msg, "tool_calls"):
                    tool_calls = msg.tool_calls
                if tool_calls:
                    for tc in tool_calls:
                        fn = (
                            tc.function
                            if hasattr(tc, "function")
                            else tc.get("function", {})
                        )
                        name = fn.name if hasattr(fn, "name") else fn.get("name", "?")
                        args = (
                            fn.arguments
                            if hasattr(fn, "arguments")
                            else fn.get("arguments", "")
                        )
                        lines.append(f"  [Tool call: {name}({args})]")
            elif role == "tool":
                tool_name = (
                    msg.get("name", "tool") if isinstance(msg, Mapping) else "tool"
                )
                lines.append(f"  [Tool result ({tool_name}): {content[:200]}]")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Role helper
    # ------------------------------------------------------------------

    def get_message_role(self, message) -> str:
        """Helper method to get the role of the message regardless of its type."""
        if isinstance(message, Mapping):
            return message.get("role")
        elif hasattr(message, "role"):
            return message.role
        else:
            raise TypeError(
                f"Message is neither a mapping nor has a 'role' attribute: {message}"
            )
