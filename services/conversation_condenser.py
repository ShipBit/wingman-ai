"""Conversation condensation — summarizes history when it grows too large."""

import asyncio
from typing import TYPE_CHECKING

from api.enums import LogType, LogSource
from services.context_budget import KEEP_TURNS, ContextBudget
from services.file import get_prompt
from services.printr import Printr
from services.token_utils import count_tokens, truncate_to_tokens

if TYPE_CHECKING:
    from api.interface import WingmanConfig
    from services.conversation_manager import ConversationManager
    from services.local_ai_service import LocalAiService
    from services.persistent_memory import PersistentMemoryService

printr = Printr()

_CONDENSE_TIMEOUT = 300.0
"""A long history on a small local support model is summarized in many chunks,
one call each."""


# The text wrapped around the conversation before it goes to the support model.
#
# These are module constants because the internal eval suite imports them. The
# system prompt and this framing are one unit — the model reads them together —
# so measuring one without the other says nothing. They drifted apart once: the
# system prompt was rewritten to ask for a short fact sheet while the suffix here
# still said "list every fact ... include all names, preferences and creative
# content", which is the instruction that produced summaries as long as their
# source.
CONDENSE_SUMMARY_HEADER = (
    "EXISTING SUMMARY (incorporate and update — do not repeat verbatim):\n"
)
CONDENSE_CONVERSATION_HEADER = "CONVERSATION TO SUMMARIZE:\n"

# The only rule that belongs here rather than in the prompt file: it is about
# what must never leave the machine, and it has to hold for every prompt variant
# anyone tries in the eval suite.
CONDENSE_SUFFIX = (
    "\n\n---\n"
    "Never include secrets, API keys, credentials, passwords or tokens."
)

CONDENSE_MERGE_HEADER = "PARTIAL SUMMARIES TO MERGE:\n"
CONDENSE_MERGE_SUFFIX = (
    "\n\n---\n"
    "Merge these into one bullet list in the same format. Drop duplicates."
)


def condense_chunk_header(part: int, total: int) -> str:
    """Header for one chunk when the history does not fit in a single pass."""
    return f"CONVERSATION TO SUMMARIZE (part {part}/{total}):\n"




def find_cutoff(
    messages: list, keep_tokens: int, role_of, tokens_of, min_turns: int = 1
) -> int:
    """The index from which the history may be summarised.

    Keeps the most recent turns that fit in ``keep_tokens`` — always at least
    the latest ``min_turns``, however big they are. The automatic run passes
    ``KEEP_TURNS``: those turns stay complete whatever their size, and a
    summary of a price table is exactly the loss that is there to prevent. A turn starts at a user message, so the
    cut lands on a user message, and a tool group — ``assistant`` with
    ``tool_calls``, then the ``tool`` replies — always sits complete between two
    user messages. It cannot be torn apart.

    Tokens rather than a message count, because the two drift apart: with a
    skill that answers every question through three tool calls, twelve turns
    were 23,000 tokens and sat right under the trigger, so every condensation
    freed a couple of thousand tokens and the next one came two turns later. A
    token budget keeps the same amount of history whatever the play style, and
    leaves real headroom after each pass.

    The second loop: should the cut ever land on a ``tool`` reply, it walks
    forward until the whole group is inside the kept part. An orphaned ``tool``
    reply is not a cosmetic flaw but, depending on the model, a hard failure.
    Measured 2026-09-14: ``google/gemini-2.5-flash`` answers normally,
    ``openai/gpt-4.1-mini`` rejects the request with 400 ("No tool call found
    for function call output"). A mistake here would therefore be invisible on
    our default model and would only hit the users who picked another one.

    Returns 0 when there is nothing to summarise.
    """
    cutoff = 0
    kept_tokens = 0
    turns_kept = 0
    for i in range(len(messages) - 1, -1, -1):
        kept_tokens += tokens_of(messages[i])
        if role_of(messages[i]) != "user":
            continue
        if turns_kept < max(1, min_turns) or kept_tokens <= keep_tokens:
            cutoff = i
            turns_kept += 1
            continue
        break

    if cutoff <= 0 or cutoff >= len(messages):
        return 0

    while cutoff < len(messages) and role_of(messages[cutoff]) == "tool":
        cutoff += 1

    return cutoff if cutoff < len(messages) else 0


class ConversationCondenser:
    def __init__(
        self,
        conversation: "ConversationManager",
        config: "WingmanConfig",
        wingman_name: str,
    ):
        self._conversation = conversation
        self._config = config
        self._wingman_name = wingman_name
        self._is_condensing = False
        self._condense_task: asyncio.Task | None = None
        self._support_token_ratio: float = 1.35
        self._reported_fixed_bulk = False
        """Whether the user has been told that the prompt is big but the history
        is not. Once per stretch — reset when a condensation actually runs."""
        self._budget = ContextBudget(window=128_000)
        """Set by ``maybe_condense``; a manual run before the first turn uses this."""

    @property
    def summary(self) -> str:
        return self._conversation.conversation_summary

    @property
    def is_condensing(self) -> bool:
        return self._is_condensing

    def keep_tokens(self, force: bool = False) -> int:
        """How much recent history a condensation leaves verbatim: a quarter of
        the history limit, and never fewer than ``KEEP_TURNS`` turns (see
        ``find_cutoff``). A manual run keeps only the latest turn — the user
        asked for a clean slate."""
        if force:
            return 0
        return self._budget.keep_tokens

    def _tokens_of(self, msg) -> int:
        return count_tokens(self._conversation.message_text(msg))

    async def maybe_condense(
        self,
        local_ai_service: "LocalAiService",
        last_prompt_tokens: int,
        budget: ContextBudget,
    ):
        """Shorten the history once a request passed ``budget.history_limit``.

        Below the limit nothing happens: every tool response and every turn is
        still there, word for word. Above it, first the cheap step — old tool
        responses become placeholders, no model call — and only if the request
        would still be over three quarters of the limit, older turns are
        summarized by the support model, in the background.

        The support model's size plays no part in *when* this happens: it reads
        the history in chunks that fit its window. It used to — condensation
        fired once the history reached 70% of what the support model could read
        in one pass, which with a local 4,096-token model meant summarizing the
        chat every other turn.

        ``last_prompt_tokens`` is what the provider billed for the previous
        call; without it (first turn, a provider that reports no usage) the
        history's own estimate stands in.
        """
        if not self._config.features.condense_conversation:
            return
        if self._conversation.pending_tool_calls:
            return  # Never interrupt chained tool calls
        if self._is_condensing:
            return

        self._budget = budget
        prompt = max(last_prompt_tokens, self._conversation.estimate_tokens())
        if prompt <= budget.history_limit:
            return

        cutoff = find_cutoff(
            self._conversation.messages,
            budget.keep_tokens,
            self._conversation.get_message_role,
            self._tokens_of,
            min_turns=KEEP_TURNS,
        )
        freed = 0
        if cutoff > 0:
            freed = await self._conversation.clear_tool_responses(cutoff)
        if prompt - freed <= budget.history_limit * 0.75:
            return

        history = self._conversation.estimate_tokens()
        if cutoff <= 0 or history <= budget.keep_tokens:
            # The request is big, but not because of the history: system prompt,
            # memory, tool definitions. Summarizing cannot shrink those.
            if not self._reported_fixed_bulk:
                self._reported_fixed_bulk = True
                await printr.print_async(
                    f"The last request was ~{prompt:,} tokens, but only ~{history:,} "
                    f"of that is conversation history. The rest is the system prompt, "
                    f"memory and tool definitions (skills, MCP servers), which "
                    f"summarizing cannot shrink. Disable tools you do not use to bring "
                    f"it down.",
                    color=LogType.WARNING,
                    source_name=self._wingman_name,
                    source=LogSource.WINGMAN,
                )
            return
        if not local_ai_service or not local_ai_service.is_ready():
            await printr.print_async(
                "The conversation is over its size limit, but no support model is "
                "ready to summarize it. Older messages stay until the model's own "
                "limit is reached.",
                color=LogType.WARNING,
                server_only=True,
                source_name=self._wingman_name,
                source=LogSource.WINGMAN,
            )
            return

        # Runs in background so user is never blocked.
        # Store the task reference to prevent garbage collection mid-execution.
        self._condense_task = asyncio.create_task(
            self.condense(local_ai_service=local_ai_service)
        )
        self._condense_task.add_done_callback(
            lambda _: setattr(self, "_condense_task", None)
        )

    async def condense(
        self,
        local_ai_service: "LocalAiService",
        persistent_memory_service: "PersistentMemoryService | None" = None,
        background_tasks: set[asyncio.Task] | None = None,
        force: bool = False,
    ):
        """Condense older conversation messages into a running summary using local AI.

        This preserves the most recent messages verbatim while summarizing older ones,
        saving tokens without losing important context. Tool call/response pairs are
        never split.

        Args:
            local_ai_service: The local AI service to use for summarization.
            persistent_memory_service: Unused; memory has its own checkpoints.
            background_tasks: Unused.
            force: If True, skip the threshold check (used for manual trigger).
        """
        # On the manual trigger (force), surface skips as self-vanishing toasts —
        # otherwise it looks like the button did nothing. Automatic background
        # runs stay server-only to avoid toast spam.
        if self._is_condensing:
            if force:
                printr.toast_info("Conversation summarization is already running.")
            await printr.print_async(
                "Condensation skipped — already in progress.",
                color=LogType.WARNING,
                server_only=True,
                source_name=self._wingman_name,
                source=LogSource.WINGMAN,
            )
            return
        if not local_ai_service or not local_ai_service.is_ready():
            if force:
                printr.toast_warning(
                    "Cannot summarize the conversation — local AI is not ready."
                )
            await printr.print_async(
                "Condensation skipped — local AI service not available.",
                color=LogType.WARNING,
                server_only=True,
                source_name=self._wingman_name,
                source=LogSource.WINGMAN,
            )
            return

        keep_tokens = self.keep_tokens(force=force)
        total_msg_count = len(self._conversation.messages)

        # Need at least one finished turn beyond the one we keep
        if total_msg_count < 2:
            if force:
                printr.toast_info(
                    "Nothing to summarize yet — the conversation is still too short."
                )
            await printr.print_async(
                f"Condensation skipped — only {total_msg_count} messages.",
                color=LogType.LOCALMODEL,
                source_name=self._wingman_name,
                source=LogSource.WINGMAN,
            )
            return

        self._is_condensing = True
        _condensation_stats: dict = {}

        # Broadcast start
        from api.commands import ConversationCondensationCommand

        if printr._connection_manager:
            await printr._connection_manager.broadcast(
                ConversationCondensationCommand(
                    wingman_name=self._wingman_name,
                    status="started",
                )
            )

        await printr.print_async(
            "Conversation condensation started.",
            color=LogType.INFO,
            server_only=True,
            source_name=self._wingman_name,
            source=LogSource.WINGMAN,
        )

        try:
            # Wait for any pending tool calls to finish
            for _ in range(30):  # max 15 seconds
                if not self._conversation.pending_tool_calls:
                    break
                await asyncio.sleep(0.5)
            else:
                await printr.print_async(
                    "Condensation aborted — tool calls still pending after 15s.",
                    color=LogType.WARNING,
                    server_only=True,
                    source_name=self._wingman_name,
                    source=LogSource.WINGMAN,
                )
                return

            cutoff_index = find_cutoff(
                self._conversation.messages,
                keep_tokens,
                self._conversation.get_message_role,
                self._tokens_of,
                min_turns=1 if force else KEEP_TURNS,
            )

            if cutoff_index <= 0:
                if force:
                    printr.toast_info(
                        "Nothing to summarize yet — the conversation is still too short."
                    )
                await printr.print_async(
                    f"Condensation skipped — nothing older than the kept "
                    f"~{keep_tokens:,} tokens (total={len(self._conversation.messages)} messages).",
                    color=LogType.LOCALMODEL,
                    source_name=self._wingman_name,
                    source=LogSource.WINGMAN,
                )
                return

            to_condense = self._conversation.messages[:cutoff_index]

            condensed_text = self._conversation._messages_to_text(to_condense)
            if not condensed_text.strip():
                await printr.print_async(
                    "Condensation skipped — messages produced no text content.",
                    color=LogType.LOCALMODEL,
                    source_name=self._wingman_name,
                    source=LogSource.WINGMAN,
                )
                return

            # Estimate original token count
            estimated_original_tokens = sum(
                count_tokens(self._conversation._message_text_content(m))
                for m in to_condense
            )

            # Build the summarization prompt
            existing_summary_section = ""
            if self._conversation.conversation_summary:
                existing_summary_section = (
                    CONDENSE_SUMMARY_HEADER
                    + self._conversation.conversation_summary
                    + "\n\n"
                )

            system_prompt = get_prompt("condense-conversation")
            budget = local_ai_service.get_token_budget(system_prompt)

            user_prompt_prefix = (
                existing_summary_section + CONDENSE_CONVERSATION_HEADER
            )
            user_prompt_suffix = CONDENSE_SUFFIX
            prefix_suffix_tokens = count_tokens(user_prompt_prefix) + count_tokens(
                user_prompt_suffix
            )

            # How much conversation text fits in one pass?
            available_tokens = budget.max_input_tokens - prefix_suffix_tokens

            # Apply tokenizer ratio to decide if chunking is needed.
            corrected_text_tokens = int(
                count_tokens(condensed_text) * self._support_token_ratio
            )
            corrected_available = int(available_tokens / self._support_token_ratio)

            if corrected_text_tokens > available_tokens:
                # Chunk: summarize in segments, then merge
                support_result = await asyncio.wait_for(
                    self._chunked_support(
                        condensed_text,
                        system_prompt,
                        existing_summary_section,
                        corrected_available,
                        local_ai_service,
                    ),
                    timeout=_CONDENSE_TIMEOUT,
                )
            else:
                user_prompt = (
                    f"{user_prompt_prefix}{condensed_text}{user_prompt_suffix}"
                )
                from services.skill_local_ai import SamplingPreset

                support_result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: local_ai_service.support(
                            text=user_prompt,
                            system_prompt=system_prompt,
                            preset=SamplingPreset.BALANCED,
                        ),
                    ),
                    timeout=_CONDENSE_TIMEOUT,
                )

            summary = support_result.text if support_result else None

            # Calibrate tokenizer ratio from real model usage
            if support_result and support_result.prompt_tokens > 0:
                cl100k_input = (
                    budget.system_tokens
                    + count_tokens(condensed_text)
                    + prefix_suffix_tokens
                )
                if cl100k_input > 0:
                    self._support_token_ratio = (
                        support_result.prompt_tokens / cl100k_input
                    )

            # Detect truncated output
            if support_result and support_result.truncated:
                await printr.print_async(
                    f"Condensation output was truncated (finish_reason=length). "
                    f"Model used {support_result.prompt_tokens} prompt tokens, "
                    f"generated {support_result.completion_tokens} tokens. "
                    f"Token ratio calibrated to {self._support_token_ratio:.2f}.",
                    color=LogType.WARNING,
                    server_only=True,
                    source_name=self._wingman_name,
                    source=LogSource.WINGMAN,
                )

            if not summary:
                await printr.print_async(
                    "Conversation condensation failed — local AI returned no result.",
                    color=LogType.WARNING,
                    server_only=True,
                    source_name=self._wingman_name,
                    source=LogSource.WINGMAN,
                )
                return

            # Clean pending tool calls being removed
            for msg in to_condense:
                if (
                    self._conversation.get_message_role(msg) == "tool"
                    and msg.get("tool_call_id")
                    in self._conversation.pending_tool_calls
                ):
                    self._conversation.pending_tool_calls.remove(
                        msg.get("tool_call_id")
                    )

            # Replace old messages
            del self._conversation.messages[:cutoff_index]
            self._conversation.conversation_summary = summary

            estimated_summary_tokens = count_tokens(summary)
            estimated_tokens_saved = max(
                0, estimated_original_tokens - estimated_summary_tokens
            )

            self._reported_fixed_bulk = False
            remaining_tokens = self._conversation.estimate_tokens()
            await printr.print_async(
                f"Conversation condensed: {cutoff_index} older messages "
                f"(~{estimated_original_tokens:,} tokens) became a summary of "
                f"~{estimated_summary_tokens:,} tokens. {len(self._conversation.messages)} "
                f"recent messages (~{remaining_tokens:,} tokens) kept verbatim.",
                color=LogType.LOCALMODEL,
                source_name=self._wingman_name,
                source=LogSource.WINGMAN,
            )
            printr.print(
                f"Condensation token ratio: {self._support_token_ratio:.2f}.",
                color=LogType.INFO,
                server_only=True,
            )

            # Record stats for the broadcast in finally
            _condensation_stats = {
                "messages_condensed": cutoff_index,
                "messages_remaining": len(self._conversation.messages),
                "summary_length": len(summary),
                "estimated_tokens_saved": estimated_tokens_saved,
                "summary_text": summary,
            }

        except asyncio.TimeoutError:
            await printr.print_async(
                "Condensation timed out — local model took too long.",
                color=LogType.WARNING,
                server_only=True,
                source_name=self._wingman_name,
                source=LogSource.WINGMAN,
            )
        except Exception as e:
            await printr.print_async(
                f"Conversation condensation error: {e}",
                color=LogType.ERROR,
                server_only=True,
                source_name=self._wingman_name,
                source=LogSource.WINGMAN,
            )
        finally:
            self._is_condensing = False
            # Always broadcast finished so the client UI doesn't get stuck.
            # Include summary_text if condensation produced one (even if a
            # later step failed), so the client can show the view-history button.
            if printr._connection_manager:
                try:
                    await printr._connection_manager.broadcast(
                        ConversationCondensationCommand(
                            wingman_name=self._wingman_name,
                            status="finished",
                            **_condensation_stats,
                        )
                    )
                except Exception as e:
                    await printr.print_async(
                        f"Failed to broadcast condensation finish: {e}",
                        color=LogType.WARNING,
                        server_only=True,
                        source_name=self._wingman_name,
                        source=LogSource.WINGMAN,
                    )

    async def _chunked_support(
        self,
        full_text: str,
        system_prompt: str,
        existing_summary_section: str,
        chunk_max_tokens: int,
        local_ai_service: "LocalAiService",
    ) -> "SupportResult":
        """Process text that exceeds the model's context window by chunking.

        Each chunk is processed independently, then results are merged into
        one final summary. Returns a SupportResult from the merge step.
        """
        from providers.llama_cpp_provider import SupportResult
        from services.skill_local_ai import SamplingPreset

        budget = local_ai_service.get_token_budget(system_prompt)

        # Convert token budget to approximate char limit for splitting
        # (splitting needs char positions; we use ~4 chars/token as a rough guide,
        # then verify with count_tokens)
        approx_chunk_chars = chunk_max_tokens * 4
        chunks = []
        remaining = full_text
        while remaining:
            if count_tokens(remaining) <= chunk_max_tokens:
                chunks.append(remaining)
                break
            # Try to split at a newline boundary
            split_at = remaining.rfind("\n", 0, approx_chunk_chars)
            if split_at <= 0:
                split_at = approx_chunk_chars
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip()

        loop = asyncio.get_event_loop()
        chunk_summaries = []
        for i, chunk in enumerate(chunks):
            user_prompt = (
                f"{existing_summary_section if i == 0 else ''}"
                f"{condense_chunk_header(i + 1, len(chunks))}{chunk}"
                f"{CONDENSE_SUFFIX}"
            )

            # Safety: if chunk input exceeds budget, truncate chunk text
            chunk_text_tokens = count_tokens(chunk)
            prompt_overhead = count_tokens(user_prompt) - chunk_text_tokens
            if prompt_overhead + chunk_text_tokens > budget.max_input_tokens:
                safe_text_tokens = budget.max_input_tokens - prompt_overhead
                if safe_text_tokens > 0:
                    chunk = truncate_to_tokens(chunk, safe_text_tokens)
                    user_prompt = (
                        f"{existing_summary_section if i == 0 else ''}"
                        f"{condense_chunk_header(i + 1, len(chunks))}{chunk}"
                        f"{CONDENSE_SUFFIX}"
                    )
                await printr.print_async(
                    f"Part {i + 1}/{len(chunks)} of the conversation was too long for the "
                    f"support model and was cut from ~{chunk_text_tokens:,} to "
                    f"~{max(0, safe_text_tokens):,} tokens before summarizing. The cut "
                    f"part is not in the summary.",
                    color=LogType.WARNING,
                    source_name=self._wingman_name,
                    source=LogSource.WINGMAN,
                )

            result = await loop.run_in_executor(
                None,
                lambda p=user_prompt: local_ai_service.support(
                    text=p,
                    system_prompt=system_prompt,
                    preset=SamplingPreset.BALANCED,
                ),
            )
            if result.text:
                chunk_summaries.append(result.text)

                # Calibrate tokenizer ratio from real model usage.
                cl100k_input = count_tokens(system_prompt) + count_tokens(user_prompt)
                if result.prompt_tokens > 0 and cl100k_input > 0:
                    self._support_token_ratio = result.prompt_tokens / cl100k_input

                if result.truncated:
                    await printr.print_async(
                        f"The summary of part {i + 1}/{len(chunks)} hit the support "
                        f"model's output limit and ends early "
                        f"(~{result.completion_tokens:,} tokens written from "
                        f"~{result.prompt_tokens:,} read).",
                        color=LogType.WARNING,
                        source_name=self._wingman_name,
                        source=LogSource.WINGMAN,
                    )

        if not chunk_summaries:
            return SupportResult(text=None)
        if len(chunk_summaries) == 1:
            return SupportResult(text=chunk_summaries[0])

        # Merge all chunk summaries into one final summary
        combined = "\n\n".join(
            f"Part {i + 1}:\n{s}" for i, s in enumerate(chunk_summaries)
        )
        merge_prompt = (
            f"{existing_summary_section}"
            f"{CONDENSE_MERGE_HEADER}{combined}"
            f"{CONDENSE_MERGE_SUFFIX}"
        )

        # Safety: truncate combined summaries if they exceed budget
        if count_tokens(merge_prompt) > budget.max_input_tokens:
            combined_tokens = count_tokens(combined)
            overhead = count_tokens(merge_prompt) - combined_tokens
            safe_combined = budget.max_input_tokens - overhead
            if safe_combined > 0:
                combined = truncate_to_tokens(combined, safe_combined)
                merge_prompt = (
                    f"{existing_summary_section}"
                    f"{CONDENSE_MERGE_HEADER}{combined}"
                    f"{CONDENSE_MERGE_SUFFIX}"
                )
            await printr.print_async(
                f"The partial summaries were too long to merge in one call and were "
                f"cut from ~{combined_tokens:,} to ~{max(0, safe_combined):,} tokens. "
                f"The cut part is not in the summary.",
                color=LogType.WARNING,
                source_name=self._wingman_name,
                source=LogSource.WINGMAN,
            )

        return await loop.run_in_executor(
            None,
            lambda: local_ai_service.support(
                text=merge_prompt,
                system_prompt=system_prompt,
                preset=SamplingPreset.BALANCED,
            ),
        )
