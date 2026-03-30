"""Persistent memory service using SQLite with Python-side vector similarity."""

import asyncio
import json
import math
import re
import sqlite3
import struct
import time
import uuid
from dataclasses import dataclass
from os import path

from api.enums import LogType
from services.file import get_persistent_memory_dir
from services.printr import Printr
from services.token_utils import count_tokens

printr = Printr()

# Named constants
MEMORY_MAX_TOKENS = 1024
MEMORY_MIN_SIMILARITY = 0.5
DEDUP_THRESHOLD = 0.9
MAX_SESSION_SUMMARIES = 20
MIN_MESSAGES_FOR_EXTRACTION = 4
FORGET_SIMILARITY_THRESHOLD = 0.7
EMBEDDING_DIMENSIONS = 768  # Nomic Embed v1.5


@dataclass
class MemoryEntry:
    """A single memory entry returned from the database."""

    id: int
    collection: str
    entry_type: str
    content: str
    source_wingman: str | None
    session_id: str | None
    created_at: float
    updated_at: float


def _serialize_embedding(embedding: list[float]) -> bytes:
    """Serialize a float list into bytes for storage."""
    return struct.pack(f"{len(embedding)}f", *embedding)


def _deserialize_embedding(blob: bytes) -> list[float]:
    """Deserialize bytes back into a float list."""
    count = len(blob) // 4  # 4 bytes per float32
    return list(struct.unpack(f"{count}f", blob))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot_product = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)


class PersistentMemoryService:
    """Per-Wingman persistent memory backed by SQLite.

    Handles storage, retrieval, extraction, and deduplication of memory entries.
    Embeddings are stored as BLOBs and similarity is computed in Python.
    All instances share the same memory.db file, scoped by collection name.

    Public methods come in async/sync pairs. The async versions (add_memory,
    search, etc.) run embedding in a thread pool. The sync versions (*_sync)
    call the embedding model directly on the current thread.
    """

    def __init__(self, wingman_name: str, local_ai_service):
        self.wingman_name = wingman_name
        self.collection = f"wingman:{wingman_name}"
        self.local_ai_service = local_ai_service
        self.session_id = str(uuid.uuid4())
        self._db: sqlite3.Connection | None = None

    def initialize(self) -> None:
        """Create the database and tables if they don't exist."""
        db_dir = get_persistent_memory_dir()
        db_path = path.join(db_dir, "memory.db")
        self._db = sqlite3.connect(db_path, check_same_thread=False)

        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS memory_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection TEXT NOT NULL,
                entry_type TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding BLOB,
                source_wingman TEXT,
                session_id TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_memory_collection
                ON memory_entries(collection);
            CREATE INDEX IF NOT EXISTS idx_memory_entry_type
                ON memory_entries(entry_type);
            CREATE INDEX IF NOT EXISTS idx_memory_collection_type
                ON memory_entries(collection, entry_type);
        """)
        self._db.commit()

    # --- Core sync implementations ---

    def _add_memory_impl(
        self,
        entry_type: str,
        content: str,
        session_id: str | None = None,
    ) -> int | None:
        embeddings = self.local_ai_service.embed([content])
        if not embeddings or not embeddings[0]:
            return None
        embedding = embeddings[0]

        if entry_type == "fact":
            existing = self._find_duplicate(embedding)
            if existing:
                self._update_entry(existing.id, content, embedding)
                return existing.id

        now = time.time()
        cursor = self._db.execute(
            """INSERT INTO memory_entries
               (collection, entry_type, content, embedding,
                source_wingman, session_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                self.collection, entry_type, content,
                _serialize_embedding(embedding),
                self.wingman_name, session_id or self.session_id, now, now,
            ),
        )
        self._db.commit()

        if entry_type == "session_summary":
            self._enforce_summary_cap()

        return cursor.lastrowid

    def _update_memory_impl(self, entry_id: int, new_content: str) -> None:
        embeddings = self.local_ai_service.embed([new_content])
        if not embeddings or not embeddings[0]:
            return
        self._update_entry(entry_id, new_content, embeddings[0])

    def _search_impl(
        self,
        query_text: str,
        limit: int = 10,
        entry_type: str | None = None,
        min_similarity: float = 0.0,
    ) -> list[MemoryEntry]:
        embeddings = self.local_ai_service.embed([query_text])
        if not embeddings or not embeddings[0]:
            return []
        query_embedding = embeddings[0]

        if entry_type:
            rows = self._db.execute(
                """SELECT id, collection, entry_type, content, embedding,
                          source_wingman, session_id, created_at, updated_at
                   FROM memory_entries
                   WHERE collection = ? AND entry_type = ?
                   AND embedding IS NOT NULL""",
                (self.collection, entry_type),
            ).fetchall()
        else:
            rows = self._db.execute(
                """SELECT id, collection, entry_type, content, embedding,
                          source_wingman, session_id, created_at, updated_at
                   FROM memory_entries
                   WHERE collection = ? AND embedding IS NOT NULL""",
                (self.collection,),
            ).fetchall()

        scored = []
        for r in rows:
            stored_embedding = _deserialize_embedding(r[4])
            similarity = _cosine_similarity(query_embedding, stored_embedding)
            if similarity >= min_similarity:
                scored.append((similarity, r))

        scored.sort(key=lambda x: x[0], reverse=True)

        return [
            MemoryEntry(
                id=r[0], collection=r[1], entry_type=r[2], content=r[3],
                source_wingman=r[5], session_id=r[6],
                created_at=r[7], updated_at=r[8],
            )
            for _, r in scored[:limit]
        ]

    def _parse_json_response(self, text: str) -> dict | None:
        """Parse JSON from model output, repairing common small-model issues."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try extracting JSON object from surrounding text
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        raw = match.group()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        # Repair missing commas between quoted strings: "foo"\n"bar" → "foo", "bar"
        repaired = re.sub(r'"\s*\n\s*"', '", "', raw)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _extract_text_content(content) -> str:
        """Extract plain text from message content (string or multimodal list)."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(part.get("text", ""))
                elif isinstance(part, str):
                    parts.append(part)
            return " ".join(parts)
        return ""

    def _extract_memories_impl(
        self, messages: list, generate_summary: bool = False
    ) -> None:
        if len(messages) < MIN_MESSAGES_FOR_EXTRACTION:
            return

        text_parts = []
        for msg in messages:
            role = (
                msg.get("role", "unknown")
                if isinstance(msg, dict)
                else getattr(msg, "role", "unknown")
            )
            raw_content = (
                msg.get("content", "")
                if isinstance(msg, dict)
                else getattr(msg, "content", "")
            )
            content = self._extract_text_content(raw_content)
            if content and role in ("user", "assistant"):
                text_parts.append(f"{role}: {content}")

        if not text_parts:
            return

        conversation_text = "\n".join(text_parts)

        from services.file import get_prompt
        from services.token_utils import count_tokens, truncate_to_tokens

        system_prompt = get_prompt("extract-memories")
        budget = self.local_ai_service.get_token_budget(system_prompt)
        text_tokens = count_tokens(conversation_text)

        if text_tokens <= budget.max_input_tokens:
            # Fits in one pass
            result = self.local_ai_service.support(
                text=conversation_text,
                system_prompt=system_prompt,
            )
            self._process_extraction_result(result, generate_summary)
        else:
            # Chunk: split into segments that fit the context window
            chunk_max_tokens = budget.max_input_tokens
            approx_chunk_chars = chunk_max_tokens * 4
            chunks = []
            remaining = conversation_text
            while remaining:
                if count_tokens(remaining) <= chunk_max_tokens:
                    chunks.append(remaining)
                    break
                split_at = remaining.rfind("\n", 0, approx_chunk_chars)
                if split_at <= 0:
                    split_at = approx_chunk_chars
                chunks.append(remaining[:split_at])
                remaining = remaining[split_at:].lstrip()

            printr.print(
                f"Memory extraction: chunking {text_tokens} tokens into {len(chunks)} parts.",
                color=LogType.MEMORY,
                server_only=True,
            )

            all_facts = []
            last_summary = ""
            for i, chunk in enumerate(chunks):
                # Safety: truncate if chunk still exceeds budget
                if count_tokens(chunk) > chunk_max_tokens:
                    chunk = truncate_to_tokens(chunk, chunk_max_tokens)
                result = self.local_ai_service.support(
                    text=chunk,
                    system_prompt=system_prompt,
                )
                if result and result.text:
                    data = self._parse_json_response(result.text)
                    if data:
                        all_facts.extend(data.get("facts", []))
                        s = data.get("summary", "")
                        if s:
                            last_summary = s

            # Store collected facts
            for fact in all_facts:
                if fact and isinstance(fact, str) and len(fact.strip()) > 5:
                    self._add_memory_impl(
                        entry_type="fact",
                        content=fact.strip(),
                        session_id=self.session_id,
                    )

            if generate_summary and last_summary and len(last_summary.strip()) > 10:
                self._add_memory_impl(
                    entry_type="session_summary",
                    content=last_summary.strip(),
                    session_id=self.session_id,
                )

    def _process_extraction_result(
        self, result, generate_summary: bool
    ) -> None:
        """Process a support model result from memory extraction."""
        if not result or not result.text:
            return

        data = self._parse_json_response(result.text)
        if data is None:
            return

        facts = data.get("facts", [])
        for fact in facts:
            if fact and isinstance(fact, str) and len(fact.strip()) > 5:
                self._add_memory_impl(
                    entry_type="fact",
                    content=fact.strip(),
                    session_id=self.session_id,
                )

        if generate_summary:
            summary = data.get("summary", "")
            if summary and isinstance(summary, str) and len(summary.strip()) > 10:
                self._add_memory_impl(
                    entry_type="session_summary",
                    content=summary.strip(),
                    session_id=self.session_id,
                )

    def _build_memory_context_impl(
        self, query_text: str, max_tokens: int = MEMORY_MAX_TOKENS
    ) -> str:
        facts = self._search_impl(
            query_text, limit=20, entry_type="fact",
            min_similarity=MEMORY_MIN_SIMILARITY,
        )
        summaries = self._search_impl(
            query_text, limit=2, entry_type="session_summary",
            min_similarity=MEMORY_MIN_SIMILARITY,
        )

        if not facts and not summaries:
            return ""

        parts = []
        token_count = 0

        if facts:
            fact_lines = []
            for fact in facts:
                line = f"- {fact.content}"
                line_tokens = count_tokens(line)
                if token_count + line_tokens > max_tokens:
                    break
                fact_lines.append(line)
                token_count += line_tokens

            if fact_lines:
                parts.append(
                    "[Memory - Relevant facts]\n" + "\n".join(fact_lines)
                )

        if summaries:
            summary = summaries[0]
            summary_tokens = count_tokens(summary.content)
            if token_count + summary_tokens <= max_tokens:
                parts.append(
                    f"[Memory - Recent session]\n{summary.content}"
                )

        return "\n\n".join(parts)

    def _forget_by_query_impl(self, query_text: str) -> bool:
        embeddings = self.local_ai_service.embed([query_text])
        if not embeddings or not embeddings[0]:
            return False
        query_embedding = embeddings[0]

        rows = self._db.execute(
            """SELECT id, content, embedding
               FROM memory_entries
               WHERE collection = ? AND embedding IS NOT NULL""",
            (self.collection,),
        ).fetchall()

        if not rows:
            return False

        best_id = None
        best_similarity = -1.0
        for entry_id, _content, emb_blob in rows:
            stored_embedding = _deserialize_embedding(emb_blob)
            similarity = _cosine_similarity(query_embedding, stored_embedding)
            if similarity > best_similarity:
                best_similarity = similarity
                best_id = entry_id

        if best_id is not None and best_similarity >= FORGET_SIMILARITY_THRESHOLD:
            self.delete_memory(best_id)
            return True
        return False

    # --- Async public API (preferred) ---

    async def add_memory(
        self,
        entry_type: str,
        content: str,
        session_id: str | None = None,
    ) -> int | None:
        """Add a memory entry with embedding. Deduplicates facts automatically.

        Returns the entry ID (new or updated), or None on failure.
        """
        return await asyncio.to_thread(
            self._add_memory_impl, entry_type, content, session_id
        )

    async def update_memory(self, entry_id: int, new_content: str) -> None:
        """Update a memory entry's content and re-embed."""
        await asyncio.to_thread(self._update_memory_impl, entry_id, new_content)

    async def search(
        self,
        query_text: str,
        limit: int = 10,
        entry_type: str | None = None,
    ) -> list[MemoryEntry]:
        """Search memories by semantic similarity to query_text."""
        return await asyncio.to_thread(
            self._search_impl, query_text, limit, entry_type
        )

    async def extract_memories(
        self, messages: list, generate_summary: bool = False
    ) -> None:
        """Extract facts (and optionally a session summary) from messages."""
        await asyncio.to_thread(
            self._extract_memories_impl, messages, generate_summary
        )

    async def build_memory_context(
        self, query_text: str, max_tokens: int = MEMORY_MAX_TOKENS
    ) -> str:
        """Build formatted memory context for system prompt injection."""
        return await asyncio.to_thread(
            self._build_memory_context_impl, query_text, max_tokens
        )

    async def forget_by_query(self, query_text: str) -> bool:
        """Find and delete the closest matching memory to the query.

        Returns True if a memory was deleted, False if no close match found.
        """
        return await asyncio.to_thread(
            self._forget_by_query_impl, query_text
        )

    # --- Sync public API ---

    def add_memory_sync(
        self,
        entry_type: str,
        content: str,
        session_id: str | None = None,
    ) -> int | None:
        """Sync version of add_memory."""
        return self._add_memory_impl(entry_type, content, session_id)

    def update_memory_sync(self, entry_id: int, new_content: str) -> None:
        """Sync version of update_memory."""
        self._update_memory_impl(entry_id, new_content)

    def search_sync(
        self,
        query_text: str,
        limit: int = 10,
        entry_type: str | None = None,
    ) -> list[MemoryEntry]:
        """Sync version of search."""
        return self._search_impl(query_text, limit, entry_type)

    def extract_memories_sync(
        self, messages: list, generate_summary: bool = False
    ) -> None:
        """Sync version of extract_memories."""
        self._extract_memories_impl(messages, generate_summary)

    def build_memory_context_sync(
        self, query_text: str, max_tokens: int = MEMORY_MAX_TOKENS
    ) -> str:
        """Sync version of build_memory_context."""
        return self._build_memory_context_impl(query_text, max_tokens)

    def forget_by_query_sync(self, query_text: str) -> bool:
        """Sync version of forget_by_query."""
        return self._forget_by_query_impl(query_text)

    # --- Pure sync methods (no embedding needed) ---

    def delete_memory(self, entry_id: int) -> None:
        """Delete a single memory entry."""
        self._db.execute("DELETE FROM memory_entries WHERE id = ?", (entry_id,))
        self._db.commit()

    def clear_collection(self) -> None:
        """Delete all memories for this Wingman's collection."""
        self._db.execute(
            "DELETE FROM memory_entries WHERE collection = ?", (self.collection,)
        )
        self._db.commit()

    def get_all(self, entry_type: str | None = None) -> list[MemoryEntry]:
        """Get all memories for this Wingman's collection."""
        if entry_type:
            rows = self._db.execute(
                """SELECT id, collection, entry_type, content, source_wingman,
                          session_id, created_at, updated_at
                   FROM memory_entries
                   WHERE collection = ? AND entry_type = ?
                   ORDER BY created_at DESC""",
                (self.collection, entry_type),
            ).fetchall()
        else:
            rows = self._db.execute(
                """SELECT id, collection, entry_type, content, source_wingman,
                          session_id, created_at, updated_at
                   FROM memory_entries
                   WHERE collection = ?
                   ORDER BY created_at DESC""",
                (self.collection,),
            ).fetchall()

        return [
            MemoryEntry(
                id=r[0], collection=r[1], entry_type=r[2], content=r[3],
                source_wingman=r[4], session_id=r[5],
                created_at=r[6], updated_at=r[7],
            )
            for r in rows
        ]

    def close(self) -> None:
        """Close the database connection."""
        if self._db:
            self._db.close()
            self._db = None

    # --- Private helpers ---

    def _find_duplicate(self, embedding: list[float]) -> MemoryEntry | None:
        """Find the most similar existing fact if above DEDUP_THRESHOLD."""
        rows = self._db.execute(
            """SELECT id, collection, entry_type, content, embedding,
                      source_wingman, session_id, created_at, updated_at
               FROM memory_entries
               WHERE collection = ? AND entry_type = 'fact'
               AND embedding IS NOT NULL""",
            (self.collection,),
        ).fetchall()

        if not rows:
            return None

        best_row = None
        best_similarity = -1.0
        for r in rows:
            stored_embedding = _deserialize_embedding(r[4])
            similarity = _cosine_similarity(embedding, stored_embedding)
            if similarity > best_similarity:
                best_similarity = similarity
                best_row = r

        if best_row is not None and best_similarity >= DEDUP_THRESHOLD:
            return MemoryEntry(
                id=best_row[0], collection=best_row[1],
                entry_type=best_row[2], content=best_row[3],
                source_wingman=best_row[5], session_id=best_row[6],
                created_at=best_row[7], updated_at=best_row[8],
            )
        return None

    def _update_entry(
        self, entry_id: int, content: str, embedding: list[float]
    ) -> None:
        """Update an existing entry's content and embedding."""
        now = time.time()
        self._db.execute(
            """UPDATE memory_entries
               SET content = ?, embedding = ?, updated_at = ?
               WHERE id = ?""",
            (content, _serialize_embedding(embedding), now, entry_id),
        )
        self._db.commit()

    def _enforce_summary_cap(self) -> None:
        """Delete oldest session summaries beyond MAX_SESSION_SUMMARIES."""
        rows = self._db.execute(
            """SELECT id FROM memory_entries
               WHERE collection = ? AND entry_type = 'session_summary'
               ORDER BY created_at DESC""",
            (self.collection,),
        ).fetchall()

        if len(rows) > MAX_SESSION_SUMMARIES:
            to_delete = [r[0] for r in rows[MAX_SESSION_SUMMARIES:]]
            placeholders = ",".join("?" * len(to_delete))
            self._db.execute(
                f"DELETE FROM memory_entries WHERE id IN ({placeholders})",
                to_delete,
            )
            self._db.commit()
