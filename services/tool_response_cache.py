import asyncio
import json
import math
import time
from dataclasses import dataclass, field

from api.enums import LogType, LogSource
from services.printr import Printr
from services.token_utils import count_tokens, truncate_to_tokens

printr = Printr()

# Prompt name loaded via get_prompt() — separate from conversation condensation prompts
TOOL_RESPONSE_PROMPT_NAME = "summarize-tool-response"


@dataclass
class CachedResponse:
    """A single cached tool response with its chunks and embeddings."""

    tool_call_id: str
    tool_name: str
    original_token_count: int
    chunks: list[str]
    embeddings: list[list[float]]
    summary: str
    timestamp: float


class ToolResponseCache:
    """In-memory cache for compressed tool responses with embedding-based retrieval.

    When a tool response exceeds COMPRESS_THRESHOLD tokens, it is:
    1. Chunked (JSON-aware or newline-boundary)
    2. Embedded via the local embed model for semantic retrieval
    3. Summarized via the local LLM (capped at MAX_SUMMARIZE_CHUNKS)
    4. Stored in cache; the conversation gets the compressed summary

    The cloud LLM can later call retrieve_tool_response_details to get
    specific chunks via cosine similarity on the stored embeddings.
    """

    COMPRESS_THRESHOLD = 4000
    CHUNK_TARGET_TOKENS = 400
    MAX_SUMMARIZE_CHUNKS = 30
    RETRIEVAL_TOP_K = 5
    RETRIEVAL_CHUNK_MAX = 500

    def __init__(self):
        self._cache: dict[str, CachedResponse] = {}

    # ── public API ──────────────────────────────────────────────

    def should_compress(self, response_text: str) -> bool:
        return count_tokens(response_text) >= self.COMPRESS_THRESHOLD

    def has_cached_responses(self) -> bool:
        return bool(self._cache)

    def clear(self):
        self._cache.clear()

    def evict(self, tool_call_id: str):
        self._cache.pop(tool_call_id, None)

    def evict_stale(self, messages: list[dict]):
        """Remove cached responses not referenced by any current message."""
        active_ids = {
            msg.get("tool_call_id")
            for msg in messages
            if msg.get("role") == "tool" and msg.get("tool_call_id")
        }
        stale = [k for k in self._cache if k not in active_ids]
        for k in stale:
            del self._cache[k]

    async def compress_and_cache(
        self,
        tool_call_id: str,
        tool_name: str,
        response_text: str,
        local_ai_service,
        n_ctx: int,
        wingman_name: str = "",
    ) -> str:
        """Compress a tool response and cache it.

        Returns the compressed text to store in conversation history.
        """
        original_tokens = count_tokens(response_text)

        await printr.print_async(
            f"Compressing tool response (~{original_tokens} tokens)...",
            color=LogType.INFO,
            source_name=wingman_name,
            source=LogSource.WINGMAN,
        )

        # 1. Chunk
        chunks = self.chunk_text(response_text)
        total_chunks = len(chunks)

        # 2. Embed all chunks (batch call — fast)
        truncated_for_embed = [
            truncate_to_tokens(c, 1800) for c in chunks
        ]
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None, lambda: local_ai_service.embed(truncated_for_embed)
        )
        if embeddings is None:
            embeddings = []

        # 3. Summarize (capped at MAX_SUMMARIZE_CHUNKS)
        summarize_chunks = chunks[: self.MAX_SUMMARIZE_CHUNKS]
        capped = total_chunks > self.MAX_SUMMARIZE_CHUNKS
        summary = await self._summarize_chunks(
            summarize_chunks, local_ai_service, n_ctx
        )
        if not summary:
            summary = truncate_to_tokens(response_text, 500)

        summary_tokens = count_tokens(summary)

        # 4. Cache
        self._cache[tool_call_id] = CachedResponse(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            original_token_count=original_tokens,
            chunks=chunks,
            embeddings=embeddings,
            summary=summary,
            timestamp=time.time(),
        )

        # 5. Log
        if capped:
            summarized_tokens = sum(
                count_tokens(c) for c in summarize_chunks
            )
            remaining = total_chunks - self.MAX_SUMMARIZE_CHUNKS
            await printr.print_async(
                f"Tool response compression: summarized "
                f"{self.MAX_SUMMARIZE_CHUNKS}/{total_chunks} chunks "
                f"(~{summarized_tokens}/{original_tokens} tokens). "
                f"Remaining {remaining} chunks embedded for retrieval only.",
                color=LogType.INFO,
                server_only=True,
                source_name=wingman_name,
                source=LogSource.WINGMAN,
            )

        await printr.print_async(
            f"Tool response compressed "
            f"(~{original_tokens} → ~{summary_tokens} tokens).",
            color=LogType.INFO,
            source_name=wingman_name,
            source=LogSource.WINGMAN,
        )

        # 6. Format compressed response for conversation
        cap_note = ""
        if capped:
            summarized_tokens = sum(
                count_tokens(c) for c in summarize_chunks
            )
            cap_note = (
                f"\n[Note: Summary covers first ~{summarized_tokens} tokens. "
                f"Full response (~{original_tokens} tokens) available via retrieval.]"
            )

        return (
            f"[COMPRESSED TOOL RESPONSE — original ~{original_tokens} tokens "
            f"→ ~{summary_tokens} tokens]\n"
            f"{summary}{cap_note}\n"
            f"[For specific details, use retrieve_tool_response_details "
            f'with cache_id="{tool_call_id}" and your query.]'
        )

    def retrieve(
        self, cache_id: str, query: str, local_ai_service
    ) -> str:
        """Retrieve relevant chunks from a cached response using cosine similarity."""
        if cache_id not in self._cache:
            return f"No cached response found for cache_id '{cache_id}'."

        cached = self._cache[cache_id]

        if not cached.embeddings or not query.strip():
            # No embeddings or empty query — return first chunks
            result_chunks = cached.chunks[: self.RETRIEVAL_TOP_K]
        else:
            query_embedding = local_ai_service.embed([query])
            if query_embedding is None or not query_embedding:
                result_chunks = cached.chunks[: self.RETRIEVAL_TOP_K]
            else:
                qvec = query_embedding[0]
                scored = [
                    (i, self.cosine_similarity(qvec, emb))
                    for i, emb in enumerate(cached.embeddings)
                    if i < len(cached.chunks)
                ]
                scored.sort(key=lambda x: x[1], reverse=True)
                top_indices = [
                    idx for idx, _ in scored[: self.RETRIEVAL_TOP_K]
                ]
                result_chunks = [cached.chunks[i] for i in top_indices]

        header = (
            f"Retrieved {len(result_chunks)} relevant chunks from "
            f"'{cached.tool_name}' response "
            f"(original ~{cached.original_token_count} tokens):\n\n"
        )
        formatted = "\n\n---\n\n".join(
            truncate_to_tokens(chunk, self.RETRIEVAL_CHUNK_MAX)
            for chunk in result_chunks
        )
        return header + formatted

    def get_tool_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "retrieve_tool_response_details",
                "description": (
                    "Retrieve specific details from a previously compressed "
                    "tool response using semantic search. Use this when you "
                    "need more detail than the summary provides."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cache_id": {
                            "type": "string",
                            "description": (
                                "The cache_id from a compressed tool response"
                            ),
                        },
                        "query": {
                            "type": "string",
                            "description": (
                                "What specific information you need "
                                "from the original response"
                            ),
                        },
                    },
                    "required": ["cache_id", "query"],
                },
            },
        }

    # ── chunking ────────────────────────────────────────────────

    def chunk_text(self, text: str) -> list[str]:
        """Split text into chunks suitable for embedding.

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
                    item_text = json.dumps(
                        item, indent=2, ensure_ascii=False
                    )
                    if count_tokens(item_text) <= self.CHUNK_TARGET_TOKENS:
                        chunks.append(item_text)
                    else:
                        chunks.extend(self._split_by_tokens(item_text))
                if chunks:
                    return chunks
            elif isinstance(data, dict):
                for key, value in data.items():
                    item_text = json.dumps(
                        {key: value}, indent=2, ensure_ascii=False
                    )
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
        n_ctx: int,
    ) -> str | None:
        """Summarize chunks using the local LLM, then merge into one summary."""
        from services.file import get_prompt

        system_prompt = get_prompt(TOOL_RESPONSE_PROMPT_NAME)
        system_tokens = count_tokens(system_prompt)
        min_output = 512
        max_input = n_ctx - system_tokens - min_output

        loop = asyncio.get_event_loop()
        chunk_summaries: list[str] = []

        for i, chunk in enumerate(chunks):
            user_prompt = (
                f"DATA TO SUMMARIZE (part {i + 1}/{len(chunks)}):\n"
                f"{chunk}\n\n---\n"
                "Summarize the above data. Preserve all key facts, "
                "numbers, names, IDs, and status values:"
            )
            user_tokens = count_tokens(user_prompt)

            # Truncate chunk if it exceeds available input budget
            if user_tokens > max_input:
                safe_tokens = max_input - count_tokens(
                    f"DATA TO SUMMARIZE (part {i + 1}/{len(chunks)}):\n"
                    "\n\n---\n"
                    "Summarize the above data. Preserve all key facts, "
                    "numbers, names, IDs, and status values:"
                )
                if safe_tokens > 0:
                    chunk = truncate_to_tokens(chunk, safe_tokens)
                    user_prompt = (
                        f"DATA TO SUMMARIZE (part {i + 1}/{len(chunks)}):\n"
                        f"{chunk}\n\n---\n"
                        "Summarize the above data. Preserve all key facts, "
                        "numbers, names, IDs, and status values:"
                    )
                    user_tokens = count_tokens(user_prompt)

            output_budget = max(min_output, n_ctx - system_tokens - user_tokens)

            try:
                result = await loop.run_in_executor(
                    None,
                    lambda p=user_prompt, mt=output_budget: local_ai_service.summarize(
                        text=p, system_prompt=system_prompt, max_tokens=mt,
                    ),
                )
                if result and result.text:
                    chunk_summaries.append(result.text)
            except Exception:
                pass

        if not chunk_summaries:
            return None
        if len(chunk_summaries) == 1:
            return chunk_summaries[0]

        # Merge all chunk summaries into one
        combined = "\n\n".join(
            f"Part {i + 1}:\n{s}" for i, s in enumerate(chunk_summaries)
        )
        merge_prompt = (
            f"PARTIAL SUMMARIES TO MERGE:\n{combined}\n\n"
            "Merge into a single coherent summary. Keep all key facts:"
        )
        merge_tokens = count_tokens(merge_prompt)

        # Truncate if merge input is too large
        if merge_tokens > max_input:
            combined = truncate_to_tokens(combined, max_input - 100)
            merge_prompt = (
                f"PARTIAL SUMMARIES TO MERGE:\n{combined}\n\n"
                "Merge into a single coherent summary. Keep all key facts:"
            )
            merge_tokens = count_tokens(merge_prompt)

        merge_output = max(min_output, n_ctx - system_tokens - merge_tokens)

        try:
            result = await loop.run_in_executor(
                None,
                lambda: local_ai_service.summarize(
                    text=merge_prompt,
                    system_prompt=system_prompt,
                    max_tokens=merge_output,
                ),
            )
            if result and result.text:
                return result.text
        except Exception:
            pass

        # Fallback: concatenate chunk summaries
        return "\n".join(chunk_summaries)

    # ── math ────────────────────────────────────────────────────

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
