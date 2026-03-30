"""SkillLocalAI — stable facade for skill developers to access local AI capabilities.

Skills access this via ``self.local_ai`` on SkillBase. The facade wraps
``LocalAiService`` and ``PersistentMemoryService`` behind a safe, documented API.
Skills never see exceptions — errors are logged to the client automatically and
methods return predictable failure values (None, [], "", False).
"""

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from api.enums import LogSource, LogType
from services.printr import Printr

if TYPE_CHECKING:
    from services.local_ai_service import TokenBudget
    from wingmen.open_ai_wingman import OpenAiWingman

printr = Printr()


# ── Facade types ──────────────────────────────────────────────────


@dataclass(frozen=True)
class SupportResponse:
    """Result from a local AI support model call."""

    text: str | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    truncated: bool = False


@dataclass(frozen=True)
class MemorySearchResult:
    """A memory entry returned from search."""

    id: int
    content: str
    entry_type: str
    source_wingman: str | None
    created_at: float


class MemoryType(str, Enum):
    """Type-safe enum for memory entry types."""

    FACT = "fact"
    SESSION_SUMMARY = "session_summary"


# ── Facade ────────────────────────────────────────────────────────


class SkillLocalAI:
    """Stable facade exposing local AI capabilities to skill developers.

    Wraps ``LocalAiService`` (support model, embeddings) and
    ``PersistentMemoryService`` (memory storage) behind a safe API.

    Every method follows the same pattern:
    1. Check service availability — return failure value if unavailable
    2. Try the operation
    3. On exception: log to client, return failure value
    4. On success: convert internal types to facade types and return
    """

    def __init__(self, wingman: "OpenAiWingman"):
        self._wingman = wingman

    # ── Availability ──────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """Whether the local support model is loaded and ready."""
        svc = self._wingman.local_ai_service
        return svc is not None and svc.is_ready()

    @property
    def embed_available(self) -> bool:
        """Whether the embedding model is loaded and ready."""
        # Embed readiness is tied to the same is_ready() check — if the
        # provider is ready, both support and embed models are loaded.
        svc = self._wingman.local_ai_service
        return svc is not None and svc.is_ready()

    @property
    def memory_available(self) -> bool:
        """Whether persistent memory is available (requires local AI + wingman config)."""
        return self._wingman.persistent_memory_service is not None

    # ── Error logging ─────────────────────────────────────────────

    async def _log_error(self, method: str, error: Exception):
        await printr.print_async(
            f"[SkillLocalAI] {method}() failed: {error}",
            color=LogType.ERROR,
            source_name=self._wingman.name,
            source=LogSource.WINGMAN,
        )

    def _log_error_sync(self, method: str, error: Exception):
        printr.print(
            f"[SkillLocalAI] {method}() failed: {error}",
            color=LogType.ERROR,
            source_name=self._wingman.name,
            source=LogSource.WINGMAN,
        )

    # ── Support model ─────────────────────────────────────────────

    async def support(
        self, text: str, system_prompt: str = ""
    ) -> SupportResponse | None:
        """Run text through the local support model.

        Returns SupportResponse with text and token usage, or None on failure.
        """
        if not self.available:
            return None
        try:
            result = await asyncio.to_thread(
                self._wingman.local_ai_service.support, text, system_prompt
            )
            if result is None:
                return None
            return SupportResponse(
                text=result.text,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                truncated=result.truncated,
            )
        except Exception as e:
            await self._log_error("support", e)
            return None

    def support_sync(
        self, text: str, system_prompt: str = ""
    ) -> SupportResponse | None:
        """Sync version of support()."""
        if not self.available:
            return None
        try:
            result = self._wingman.local_ai_service.support(text, system_prompt)
            if result is None:
                return None
            return SupportResponse(
                text=result.text,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                truncated=result.truncated,
            )
        except Exception as e:
            self._log_error_sync("support_sync", e)
            return None

    # ── Summarize ─────────────────────────────────────────────────

    async def summarize(
        self, text: str, instruction: str = ""
    ) -> SupportResponse | None:
        """Summarize text, automatically chunking if it exceeds the context window.

        For small text: single support() call with instruction as system prompt.
        For large text: chunks, summarizes each via ToolResponseCompressor, merges.
        """
        if not self.available:
            return None
        try:
            svc = self._wingman.local_ai_service
            budget = svc.get_token_budget(instruction)
            from services.token_utils import count_tokens

            text_tokens = count_tokens(text)

            if text_tokens <= budget.max_input_tokens:
                # Fits in one call
                return await self.support(text, system_prompt=instruction)

            # Too large — compress first, then apply instruction in a final pass
            from services.tool_response_cache import ToolResponseCompressor

            compressor = ToolResponseCompressor()
            compressed = await compressor.compress(
                response_text=text,
                local_ai_service=svc,
                wingman_name=self._wingman.name,
                tool_name="summarize",
            )
            # The compressed text should now fit; run a final pass with the
            # caller's instruction so it's not silently dropped.
            return await self.support(compressed, system_prompt=instruction)
        except Exception as e:
            await self._log_error("summarize", e)
            return None

    def summarize_sync(
        self, text: str, instruction: str = ""
    ) -> SupportResponse | None:
        """Sync version of summarize().

        Sync version handles large text via truncation rather than chunked
        summarization (ToolResponseCompressor is async-only). Use async
        summarize() for full chunked summarization of large text.
        """
        if not self.available:
            return None
        try:
            svc = self._wingman.local_ai_service
            budget = svc.get_token_budget(instruction)
            from services.token_utils import count_tokens, truncate_to_tokens

            text_tokens = count_tokens(text)

            if text_tokens <= budget.max_input_tokens:
                return self.support_sync(text, system_prompt=instruction)

            # Too large for sync — truncate and mark as truncated
            truncated_text = truncate_to_tokens(text, budget.max_input_tokens)
            result = self.support_sync(truncated_text, system_prompt=instruction)
            if result is None:
                return None
            return SupportResponse(
                text=result.text,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                truncated=True,
            )
        except Exception as e:
            self._log_error_sync("summarize_sync", e)
            return None

    # ── Embeddings ────────────────────────────────────────────────

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        """Generate embeddings for a list of texts. Returns None on failure."""
        if not self.embed_available:
            return None
        try:
            return await asyncio.to_thread(
                self._wingman.local_ai_service.embed, texts
            )
        except Exception as e:
            await self._log_error("embed", e)
            return None

    def embed_sync(self, texts: list[str]) -> list[list[float]] | None:
        """Sync version of embed()."""
        if not self.embed_available:
            return None
        try:
            return self._wingman.local_ai_service.embed(texts)
        except Exception as e:
            self._log_error_sync("embed_sync", e)
            return None

    # ── Memory: Remember ──────────────────────────────────────────

    async def remember_fact(
        self,
        content: str,
        entry_type: MemoryType = MemoryType.FACT,
    ) -> int | None:
        """Add a memory. Facts are auto-deduplicated (>90% similarity updates existing).

        Returns entry ID on success, None on failure.
        """
        mem = self._wingman.persistent_memory_service
        if mem is None:
            return None
        try:
            return await mem.add_memory(
                entry_type=entry_type.value,
                content=content,
            )
        except Exception as e:
            await self._log_error("remember_fact", e)
            return None

    def remember_fact_sync(
        self,
        content: str,
        entry_type: MemoryType = MemoryType.FACT,
    ) -> int | None:
        """Sync version of remember_fact()."""
        mem = self._wingman.persistent_memory_service
        if mem is None:
            return None
        try:
            return mem.add_memory_sync(
                entry_type=entry_type.value,
                content=content,
            )
        except Exception as e:
            self._log_error_sync("remember_fact_sync", e)
            return None

    # ── Memory: Recall ────────────────────────────────────────────

    async def recall_memory(
        self,
        query: str,
        limit: int = 5,
        entry_type: MemoryType | None = None,
    ) -> list[MemorySearchResult]:
        """Search memories by semantic similarity. Returns matches sorted by relevance.

        Returns empty list on failure — safe to iterate without None checks.
        """
        mem = self._wingman.persistent_memory_service
        if mem is None:
            return []
        try:
            entries = await mem.search(
                query_text=query,
                limit=limit,
                entry_type=entry_type.value if entry_type else None,
            )
            return [
                MemorySearchResult(
                    id=e.id,
                    content=e.content,
                    entry_type=e.entry_type,
                    source_wingman=e.source_wingman,
                    created_at=e.created_at,
                )
                for e in entries
            ]
        except Exception as e:
            await self._log_error("recall_memory", e)
            return []

    def recall_memory_sync(
        self,
        query: str,
        limit: int = 5,
        entry_type: MemoryType | None = None,
    ) -> list[MemorySearchResult]:
        """Sync version of recall_memory()."""
        mem = self._wingman.persistent_memory_service
        if mem is None:
            return []
        try:
            entries = mem.search_sync(
                query_text=query,
                limit=limit,
                entry_type=entry_type.value if entry_type else None,
            )
            return [
                MemorySearchResult(
                    id=e.id,
                    content=e.content,
                    entry_type=e.entry_type,
                    source_wingman=e.source_wingman,
                    created_at=e.created_at,
                )
                for e in entries
            ]
        except Exception as e:
            self._log_error_sync("recall_memory_sync", e)
            return []

    # ── Memory: Context ───────────────────────────────────────────

    async def memory_context(self, query: str, max_tokens: int = 500) -> str:
        """Get pre-formatted memory context for system prompt injection.

        Returns empty string on failure — safe to concatenate directly.
        """
        mem = self._wingman.persistent_memory_service
        if mem is None:
            return ""
        try:
            return await mem.build_memory_context(query, max_tokens)
        except Exception as e:
            await self._log_error("memory_context", e)
            return ""

    def memory_context_sync(self, query: str, max_tokens: int = 500) -> str:
        """Sync version of memory_context()."""
        mem = self._wingman.persistent_memory_service
        if mem is None:
            return ""
        try:
            return mem.build_memory_context_sync(query, max_tokens)
        except Exception as e:
            self._log_error_sync("memory_context_sync", e)
            return ""

    # ── Memory: Update ────────────────────────────────────────────

    async def update_memory(self, entry_id: int, new_content: str) -> bool:
        """Update a memory's content and re-embed it. Returns True on success."""
        mem = self._wingman.persistent_memory_service
        if mem is None:
            return False
        try:
            await mem.update_memory(entry_id, new_content)
            return True
        except Exception as e:
            await self._log_error("update_memory", e)
            return False

    def update_memory_sync(self, entry_id: int, new_content: str) -> bool:
        """Sync version of update_memory()."""
        mem = self._wingman.persistent_memory_service
        if mem is None:
            return False
        try:
            mem.update_memory_sync(entry_id, new_content)
            return True
        except Exception as e:
            self._log_error_sync("update_memory_sync", e)
            return False

    # ── Memory: Forget ────────────────────────────────────────────

    async def forget_memory_by_id(self, entry_id: int) -> bool:
        """Delete a specific memory by its ID. Returns True if deleted."""
        mem = self._wingman.persistent_memory_service
        if mem is None:
            return False
        try:
            await asyncio.to_thread(mem.delete_memory, entry_id)
            return True
        except Exception as e:
            await self._log_error("forget_memory_by_id", e)
            return False

    def forget_memory_by_id_sync(self, entry_id: int) -> bool:
        """Sync version of forget_memory_by_id()."""
        mem = self._wingman.persistent_memory_service
        if mem is None:
            return False
        try:
            mem.delete_memory(entry_id)
            return True
        except Exception as e:
            self._log_error_sync("forget_memory_by_id_sync", e)
            return False

    async def memory_forget(self, query: str) -> bool:
        """Find and delete the closest matching memory (fuzzy). Returns True if deleted."""
        mem = self._wingman.persistent_memory_service
        if mem is None:
            return False
        try:
            return await mem.forget_by_query(query)
        except Exception as e:
            await self._log_error("memory_forget", e)
            return False

    def memory_forget_sync(self, query: str) -> bool:
        """Sync version of memory_forget()."""
        mem = self._wingman.persistent_memory_service
        if mem is None:
            return False
        try:
            return mem.forget_by_query_sync(query)
        except Exception as e:
            self._log_error_sync("memory_forget_sync", e)
            return False

    # ── Token Budget (Advanced) ───────────────────────────────────

    def get_support_model_token_budget(
        self, system_prompt: str = ""
    ) -> "TokenBudget | None":
        """Get token budget for planning chunked support calls.

        Returns None if local AI is not available.
        """
        if not self.available:
            return None
        try:
            return self._wingman.local_ai_service.get_token_budget(system_prompt)
        except Exception as e:
            self._log_error_sync("get_support_model_token_budget", e)
            return None
