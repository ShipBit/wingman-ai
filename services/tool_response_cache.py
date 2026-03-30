import asyncio
import json

from api.enums import LogType, LogSource
from services.printr import Printr
from services.token_utils import count_tokens, truncate_to_tokens

printr = Printr()

# Prompt name loaded via get_prompt() — separate from conversation condensation prompts
TOOL_RESPONSE_PROMPT_NAME = "support-tool-response"


class ToolResponseCompressor:
    """Compresses large tool responses using the local AI summarization model.

    When a tool response exceeds COMPRESS_THRESHOLD tokens, it is:
    1. Chunked (JSON-aware or newline-boundary)
    2. Summarized via the local LLM (batched, capped at MAX_SUMMARIZE_CHUNKS)
    3. The conversation gets the compressed summary instead of the full response
    """

    COMPRESS_THRESHOLD = 4000
    CHUNK_TARGET_TOKENS = 400
    MAX_SUMMARIZE_CHUNKS = 30
    SKIP_SUMMARIZE_THRESHOLD = 100  # chunks — above this, skip LLM summarization

    def should_compress(self, response_text: str) -> bool:
        return count_tokens(response_text) >= self.COMPRESS_THRESHOLD

    async def compress(
        self,
        response_text: str,
        local_ai_service,
        wingman_name: str = "",
        tool_name: str = "",
    ) -> str:
        """Compress a tool response via local AI summarization.

        Returns the compressed text to store in conversation history.
        """
        original_tokens = count_tokens(response_text)

        token_label = (
            f"~{original_tokens // 1000}k"
            if original_tokens >= 1000
            else f"~{original_tokens}"
        )
        tool_info = f" from '{tool_name}'" if tool_name else ""
        await printr.print_async(
            f"Compressing massive tool response{tool_info} with {token_label} tokens "
            f"before sending it to the LLM. If this is coming from a custom "
            f"skill, please contact the author and ask them to optimize token usage.",
            color=LogType.LOCALMODEL,
            source_name=wingman_name,
            source=LogSource.WINGMAN,
        )

        # 1. Chunk
        chunks = self.chunk_text(response_text)
        total_chunks = len(chunks)

        # 2. Summarize
        if total_chunks > self.SKIP_SUMMARIZE_THRESHOLD:
            summary = truncate_to_tokens(response_text, 800)
            capped = True
            await printr.print_async(
                f"Tool response too large for LLM summarization "
                f"({total_chunks} chunks). Using truncated head.",
                color=LogType.INFO,
                server_only=True,
                source_name=wingman_name,
                source=LogSource.WINGMAN,
            )
        else:
            summarize_count = min(total_chunks, self.MAX_SUMMARIZE_CHUNKS)
            capped = total_chunks > self.MAX_SUMMARIZE_CHUNKS
            summary = await self._summarize_chunks(
                chunks[:summarize_count], local_ai_service
            )
            if not summary:
                summary = truncate_to_tokens(response_text, 500)

            if capped:
                remaining = total_chunks - summarize_count
                await printr.print_async(
                    f"Summarized {summarize_count}/{total_chunks} chunks. "
                    f"Remaining {remaining} chunks truncated.",
                    color=LogType.INFO,
                    server_only=True,
                    source_name=wingman_name,
                    source=LogSource.WINGMAN,
                )

        summary_tokens = count_tokens(summary)

        await printr.print_async(
            f"Tool response compressed "
            f"(~{original_tokens} → ~{summary_tokens} tokens).",
            color=LogType.LOCALMODEL,
            source_name=wingman_name,
            source=LogSource.WINGMAN,
        )

        # 3. Format compressed response for conversation
        cap_note = ""
        if capped:
            cap_note = (
                f"\n[Note: Summary covers first portion. "
                f"Full response was ~{original_tokens} tokens.]"
            )

        return (
            f"[COMPRESSED TOOL RESPONSE — original ~{original_tokens} tokens "
            f"→ ~{summary_tokens} tokens]\n"
            f"{summary}{cap_note}"
        )

    # ── chunking ────────────────────────────────────────────────

    def chunk_text(self, text: str) -> list[str]:
        """Split text into chunks suitable for summarization.

        Strategy:
        1. Try JSON-aware splitting (array elements / dict keys)
        2. Sub-chunk oversized elements
        3. Fallback: newline-boundary splitting at ~CHUNK_TARGET_TOKENS
        """
        try:
            data = json.loads(text)
            chunks = []
            if isinstance(data, list):
                for item in data:
                    item_text = json.dumps(item, indent=2, ensure_ascii=False)
                    if count_tokens(item_text) <= self.CHUNK_TARGET_TOKENS:
                        chunks.append(item_text)
                    else:
                        chunks.extend(self._split_by_tokens(item_text))
                if chunks:
                    return chunks
            elif isinstance(data, dict):
                for key, value in data.items():
                    item_text = json.dumps({key: value}, indent=2, ensure_ascii=False)
                    if count_tokens(item_text) <= self.CHUNK_TARGET_TOKENS:
                        chunks.append(item_text)
                    else:
                        chunks.extend(self._split_by_tokens(item_text))
                if chunks:
                    return chunks
        except (json.JSONDecodeError, TypeError):
            pass

        return self._split_by_tokens(text)

    def _split_by_tokens(self, text: str) -> list[str]:
        """Split text at newline boundaries at ~CHUNK_TARGET_TOKENS."""
        approx_chunk_chars = self.CHUNK_TARGET_TOKENS * 4
        chunks = []
        remaining = text
        while remaining:
            if count_tokens(remaining) <= self.CHUNK_TARGET_TOKENS:
                chunks.append(remaining)
                break
            split_at = remaining.rfind("\n", 0, approx_chunk_chars)
            if split_at <= 0:
                split_at = approx_chunk_chars
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip()
        return chunks

    # ── summarization ───────────────────────────────────────────

    async def _summarize_chunks(
        self,
        chunks: list[str],
        local_ai_service,
    ) -> str | None:
        """Summarize chunks by batching as many as fit per LLM call.

        Instead of one LLM call per chunk, packs multiple chunks into each
        prompt up to the context budget. This dramatically reduces round-trips.
        Token budget is obtained from ``local_ai_service.get_token_budget()``.
        """
        from services.file import get_prompt

        system_prompt = get_prompt(TOOL_RESPONSE_PROMPT_NAME)
        budget = local_ai_service.get_token_budget(system_prompt)

        # Overhead tokens for the prompt wrapper (excluding actual data)
        wrapper_overhead = count_tokens(
            "DATA TO SUMMARIZE:\n\n\n---\n"
            "Summarize the above data. Preserve all key facts, "
            "numbers, names, IDs, and status values:"
        )
        data_budget = budget.max_input_tokens - wrapper_overhead
        if data_budget <= 0:
            return None

        # Group chunks into batches that fit within data_budget
        batches: list[str] = []
        current_batch_parts: list[str] = []
        current_batch_tokens = 0

        for chunk in chunks:
            chunk_tokens = count_tokens(chunk)
            if (
                current_batch_parts
                and current_batch_tokens + chunk_tokens > data_budget
            ):
                batches.append("\n\n".join(current_batch_parts))
                current_batch_parts = []
                current_batch_tokens = 0
            if chunk_tokens > data_budget:
                chunk = truncate_to_tokens(chunk, data_budget)
                chunk_tokens = count_tokens(chunk)
            current_batch_parts.append(chunk)
            current_batch_tokens += chunk_tokens

        if current_batch_parts:
            batches.append("\n\n".join(current_batch_parts))

        loop = asyncio.get_event_loop()
        batch_summaries: list[str] = []

        for i, batch_text in enumerate(batches):
            user_prompt = (
                f"DATA TO SUMMARIZE:\n"
                f"{batch_text}\n\n---\n"
                "Summarize the above data. Preserve all key facts, "
                "numbers, names, IDs, and status values:"
            )

            try:
                result = await loop.run_in_executor(
                    None,
                    lambda p=user_prompt: local_ai_service.support(
                        text=p,
                        system_prompt=system_prompt,
                    ),
                )
                if result and result.text:
                    batch_summaries.append(result.text)
            except Exception:
                pass

        if not batch_summaries:
            return None
        if len(batch_summaries) == 1:
            return batch_summaries[0]

        # Merge batch summaries into one
        combined = "\n\n".join(
            f"Part {i + 1}:\n{s}" for i, s in enumerate(batch_summaries)
        )
        merge_prompt = (
            f"PARTIAL SUMMARIES TO MERGE:\n{combined}\n\n"
            "Merge into a single coherent summary. Keep all key facts:"
        )

        # Safety: truncate if merge input exceeds budget
        merge_tokens = count_tokens(merge_prompt)
        if merge_tokens > budget.max_input_tokens:
            combined = truncate_to_tokens(
                combined, budget.max_input_tokens - 100
            )
            merge_prompt = (
                f"PARTIAL SUMMARIES TO MERGE:\n{combined}\n\n"
                "Merge into a single coherent summary. Keep all key facts:"
            )

        try:
            result = await loop.run_in_executor(
                None,
                lambda: local_ai_service.support(
                    text=merge_prompt,
                    system_prompt=system_prompt,
                ),
            )
            if result and result.text:
                return result.text
        except Exception:
            pass

        return "\n".join(batch_summaries)
