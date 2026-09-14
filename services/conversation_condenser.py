"""Conversation condensation — summarizes history when it grows too large."""

import asyncio
from typing import TYPE_CHECKING

from api.enums import LocalAiMode, LogType, LogSource
from services.file import get_prompt
from services.printr import Printr
from services.token_utils import count_tokens, truncate_to_tokens

if TYPE_CHECKING:
    from api.interface import WingmanConfig
    from services.conversation_manager import ConversationManager
    from services.local_ai_service import LocalAiService
    from services.persistent_memory import PersistentMemoryService

printr = Printr()

_CONDENSE_TIMEOUT = 120.0

# How much conversation is allowed to pile up before it gets summarised, in
# tokens. The real limit is the smaller of this and what the support model can
# take in one pass.
#
# It used to be only the model's capacity, which worked while that model always
# had a 4096-token window. A cloud support model has a million: the trigger would
# never fire, the history would never be condensed, and the *chat* model's
# context would overflow instead — the opposite of what condensation is for.
#
# Local stays where it was: with n_ctx 4096 the capacity works out around 3000
# tokens, so this ceiling never binds and behaviour is unchanged. Cloud gets the
# larger number because there is no reason to throw detail away early when the
# model can hold it — each summarisation round loses something.
#
# Cloud sat at 16,000 until 2026-09-14, which the trigger below turns into about
# 8,300 real tokens: the first summary after roughly an hour of play, three or
# four per session. That number is from the time when every turn paid full price
# for the whole history.
#
# Since the memory block moved behind the history (see context_builder), the
# history is a stable prefix and the provider caches it: measured 10 hits out of
# 10 covering 98% of the tokens, so a tenth of the price for the repeated part.
# 40,000 now costs about what 4,000 used to, and buys around two and a half
# hours of conversation before anything gets summarised.
#
# Not higher, for three reasons: every turn pays for the whole history, cached
# or not; the answer stops getting better past some point and only gets slower;
# and the pathological case — a 78k-token table from a skill — has to stay
# capped.
_MAX_CONVERSATION_TOKENS = 6_000
_MAX_CONVERSATION_TOKENS_CLOUD = 40_000

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


def find_cutoff(messages: list, keep_recent: int, role_of) -> int:
    """The index from which the history may be summarised.

    Keeps the last ``keep_recent`` user messages and everything between them.
    The cut therefore lands on a user message, and a tool group — ``assistant``
    with ``tool_calls``, then the ``tool`` replies — always sits complete between
    two user messages. It cannot be torn apart.

    That is what the second loop is for: should the cut ever land on a ``tool``
    reply, it walks forward until the whole group is inside the kept part. An
    orphaned ``tool`` reply is not a cosmetic flaw but, depending on the model, a
    hard failure. Measured 2026-09-14: ``google/gemini-2.5-flash`` answers
    normally, ``openai/gpt-4.1-mini`` rejects the request with 400 ("No tool call
    found for function call output"). A mistake here would therefore be invisible
    on our default model and would only hit the users who picked another one.

    Returns 0 when there is nothing to summarise.
    """
    kept = 0
    cutoff = len(messages)
    for i in range(len(messages) - 1, -1, -1):
        if role_of(messages[i]) == "user":
            kept += 1
            if kept == keep_recent:
                cutoff = i
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

    @property
    def summary(self) -> str:
        return self._conversation.conversation_summary

    @property
    def is_condensing(self) -> bool:
        return self._is_condensing

    def get_support_capacity(self, local_ai_service: "LocalAiService") -> int:
        """How many conversation tokens one summarisation pass may cover.

        The smaller of two numbers: what the support model can physically take
        (system prompt and output budget already subtracted), and the ceiling we
        set ourselves in ``_MAX_CONVERSATION_TOKENS``. Without the second, a
        cloud model's million-token window would mean the history never gets
        condensed at all.
        """
        system_prompt = get_prompt("condense-conversation")
        budget = local_ai_service.get_token_budget(system_prompt)
        # Subtract framing overhead (prefix/suffix around the conversation text)
        framing_overhead = 80
        model_capacity = max(0, budget.max_input_tokens - framing_overhead)

        cloud = local_ai_service.settings.mode == LocalAiMode.CLOUD
        ceiling = _MAX_CONVERSATION_TOKENS_CLOUD if cloud else _MAX_CONVERSATION_TOKENS
        return min(ceiling, model_capacity)

    async def maybe_condense(self, local_ai_service: "LocalAiService"):
        """Check if condensation should run and fire it as a background task.

        Uses a token-based trigger: condenses when the conversation approaches
        70% of what the support model can handle in a single pass, so we
        avoid chunking. Also has a message count safety cap.

        The cl100k_base token estimate is multiplied by _support_token_ratio
        (calibrated from real support model usage) to account for tokenizer
        differences between the estimation tokenizer and the actual model.
        """
        if not self._config.features.condense_conversation:
            return
        if not local_ai_service or not local_ai_service.is_ready():
            return
        if self._conversation.pending_tool_calls:
            return  # Never interrupt chained tool calls
        if self._is_condensing:
            return

        # Token-based trigger: condense when conversation reaches 70% of
        # what the support model can handle in one pass.
        # Apply _support_token_ratio to correct for tokenizer differences
        # between cl100k_base (used for estimation) and the actual model.
        capacity = self.get_support_capacity(local_ai_service)
        cl100k_tokens = self._conversation.estimate_tokens()
        conversation_tokens = int(cl100k_tokens * self._support_token_ratio)
        token_trigger = conversation_tokens >= int(capacity * 0.7)

        # Message count safety cap
        user_msg_count = sum(
            1
            for m in self._conversation.messages
            if self._conversation.get_message_role(m) == "user"
        )
        message_trigger = (
            user_msg_count >= self._config.features.condense_max_messages
        )

        if not token_trigger and not message_trigger:
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
            persistent_memory_service: Optional service for extracting memories.
            background_tasks: Optional set to track background tasks for memory extraction.
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

        keep_recent = (
            self._config.features.condense_keep_recent
            if not force
            else min(self._config.features.condense_keep_recent, 2)
        )
        total_msg_count = len(self._conversation.messages)

        # Need at least something to condense beyond what we keep
        if total_msg_count <= keep_recent:
            if force:
                printr.toast_info(
                    "Nothing to summarize yet — the conversation is still too short."
                )
            await printr.print_async(
                f"Condensation skipped — only {total_msg_count} messages, need more than {keep_recent} to condense.",
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
                keep_recent,
                self._conversation.get_message_role,
            )

            if cutoff_index <= 0:
                await printr.print_async(
                    f"Condensation skipped — cutoff_index={cutoff_index}, nothing to condense "
                    f"(keep_recent={keep_recent}, total={len(self._conversation.messages)}).",
                    color=LogType.LOCALMODEL,
                    source_name=self._wingman_name,
                    source=LogSource.WINGMAN,
                )
                return

            to_condense = self._conversation.messages[:cutoff_index]

            # Extract memories from messages about to be condensed (background, non-blocking)
            if persistent_memory_service:
                try:
                    task = asyncio.create_task(
                        persistent_memory_service.extract_memories(
                            to_condense, generate_summary=True
                        )
                    )
                    if background_tasks is not None:
                        background_tasks.add(task)
                        task.add_done_callback(background_tasks.discard)
                except Exception:
                    pass  # Don't let memory extraction block condensation

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

            await printr.print_async(
                f"Condensed {cutoff_index} messages into summary "
                f"({len(summary)} chars, ~{estimated_summary_tokens} tokens). "
                f"{len(self._conversation.messages)} messages remaining. "
                f"~{estimated_tokens_saved} tokens saved. "
                f"Token ratio: {self._support_token_ratio:.2f}.",
                color=LogType.INFO,
                server_only=True,
                source_name=self._wingman_name,
                source=LogSource.WINGMAN,
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
                    f"Chunk {i + 1}/{len(chunks)} exceeded context budget, truncated to fit.",
                    color=LogType.WARNING,
                    server_only=True,
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
                        f"Chunk {i + 1}/{len(chunks)} output truncated "
                        f"(prompt={result.prompt_tokens}, "
                        f"completion={result.completion_tokens}).",
                        color=LogType.WARNING,
                        server_only=True,
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
            overhead = count_tokens(merge_prompt) - count_tokens(combined)
            safe_combined = budget.max_input_tokens - overhead
            if safe_combined > 0:
                combined = truncate_to_tokens(combined, safe_combined)
                merge_prompt = (
                    f"{existing_summary_section}"
                    f"{CONDENSE_MERGE_HEADER}{combined}"
                    f"{CONDENSE_MERGE_SUFFIX}"
                )
            await printr.print_async(
                f"Merge input exceeded context budget, truncated to fit.",
                color=LogType.WARNING,
                server_only=True,
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
