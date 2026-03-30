"""Persistent memory service using sqlite-vec for vector similarity search."""

import json
import re
import sqlite3
import struct
import time
import uuid
from dataclasses import dataclass
from os import path

import sqlite_vec

from services.file import get_persistent_memory_dir

# Named constants
MEMORY_MAX_TOKENS = 1024
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
    """Serialize a float list into bytes for sqlite-vec."""
    return struct.pack(f"{len(embedding)}f", *embedding)


class PersistentMemoryService:
    """Per-Wingman persistent memory backed by sqlite-vec.

    Handles storage, retrieval, extraction, and deduplication of memory entries.
    All instances share the same memory.db file, scoped by collection name.
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
        self._db = sqlite3.connect(db_path)
        self._db.enable_load_extension(True)
        sqlite_vec.load(self._db)
        self._db.enable_load_extension(False)

        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS memory_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection TEXT NOT NULL,
                entry_type TEXT NOT NULL,
                content TEXT NOT NULL,
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

        # sqlite-vec virtual table (CREATE VIRTUAL TABLE IF NOT EXISTS is supported)
        self._db.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_vec USING vec0(
                entry_id INTEGER PRIMARY KEY,
                embedding FLOAT[{EMBEDDING_DIMENSIONS}]
            );
        """)
        self._db.commit()

    async def add_memory(
        self,
        entry_type: str,
        content: str,
        session_id: str | None = None,
    ) -> int:
        """Add a memory entry with embedding. Deduplicates facts automatically.

        Returns the entry ID (new or updated).
        """
        # Embed the content
        embeddings = await self.local_ai_service.embed([content])
        if not embeddings or not embeddings[0]:
            return -1
        embedding = embeddings[0]

        # Deduplicate facts
        if entry_type == "fact":
            existing = self._find_duplicate(embedding)
            if existing:
                # Update existing entry with newer phrasing
                self._update_entry(existing.id, content, embedding)
                return existing.id

        # Insert new entry
        now = time.time()
        cursor = self._db.execute(
            """INSERT INTO memory_entries
               (collection, entry_type, content, source_wingman, session_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (self.collection, entry_type, content, self.wingman_name,
             session_id or self.session_id, now, now),
        )
        entry_id = cursor.lastrowid

        self._db.execute(
            "INSERT INTO memory_vec (entry_id, embedding) VALUES (?, ?)",
            (entry_id, _serialize_embedding(embedding)),
        )
        self._db.commit()

        # Enforce session summary cap
        if entry_type == "session_summary":
            self._enforce_summary_cap()

        return entry_id

    async def update_memory(self, entry_id: int, new_content: str) -> None:
        """Update a memory entry's content and re-embed."""
        embeddings = await self.local_ai_service.embed([new_content])
        if not embeddings or not embeddings[0]:
            return
        embedding = embeddings[0]
        self._update_entry(entry_id, new_content, embedding)

    def delete_memory(self, entry_id: int) -> None:
        """Delete a single memory entry and its embedding."""
        self._db.execute("DELETE FROM memory_entries WHERE id = ?", (entry_id,))
        self._db.execute("DELETE FROM memory_vec WHERE entry_id = ?", (entry_id,))
        self._db.commit()

    def clear_collection(self) -> None:
        """Delete all memories for this Wingman's collection."""
        # Get all entry IDs for this collection
        rows = self._db.execute(
            "SELECT id FROM memory_entries WHERE collection = ?",
            (self.collection,),
        ).fetchall()
        if not rows:
            return
        ids = [r[0] for r in rows]
        placeholders = ",".join("?" * len(ids))
        self._db.execute(
            f"DELETE FROM memory_vec WHERE entry_id IN ({placeholders})", ids
        )
        self._db.execute(
            "DELETE FROM memory_entries WHERE collection = ?", (self.collection,)
        )
        self._db.commit()

    async def search(
        self,
        query_text: str,
        limit: int = 10,
        entry_type: str | None = None,
    ) -> list[MemoryEntry]:
        """Search memories by semantic similarity to query_text."""
        embeddings = await self.local_ai_service.embed([query_text])
        if not embeddings or not embeddings[0]:
            return []
        query_embedding = embeddings[0]

        # Build WHERE clause for collection filter (and optional type filter)
        type_filter = ""
        params: list = []
        if entry_type:
            type_filter = "AND e.entry_type = ?"
            params.append(entry_type)

        rows = self._db.execute(
            f"""
            SELECT e.id, e.collection, e.entry_type, e.content,
                   e.source_wingman, e.session_id, e.created_at, e.updated_at,
                   v.distance
            FROM memory_vec v
            JOIN memory_entries e ON e.id = v.entry_id
            WHERE e.collection = ?
            {type_filter}
            AND v.embedding MATCH ?
            ORDER BY v.distance
            LIMIT ?
            """,
            (self.collection, *params,
             _serialize_embedding(query_embedding), limit),
        ).fetchall()

        return [
            MemoryEntry(
                id=r[0], collection=r[1], entry_type=r[2], content=r[3],
                source_wingman=r[4], session_id=r[5], created_at=r[6], updated_at=r[7],
            )
            for r in rows
        ]

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
                source_wingman=r[4], session_id=r[5], created_at=r[6], updated_at=r[7],
            )
            for r in rows
        ]

    async def extract_memories(self, messages: list, generate_summary: bool = False) -> None:
        """Extract atomic facts (and optionally a session summary) from conversation messages.

        Args:
            messages: The conversation messages to extract from.
            generate_summary: If True, also generate and store a session summary.
        """
        if len(messages) < MIN_MESSAGES_FOR_EXTRACTION:
            return

        # Format messages into readable text
        text_parts = []
        for msg in messages:
            role = msg.get("role", "unknown") if isinstance(msg, dict) else getattr(msg, "role", "unknown")
            content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
            if content and role in ("user", "assistant"):
                text_parts.append(f"{role}: {content}")

        if not text_parts:
            return

        conversation_text = "\n".join(text_parts)

        # Call support model with extraction prompt
        from services.file import get_prompt

        system_prompt = get_prompt("extract-memories")
        result = await self.local_ai_service.support(
            text=conversation_text,
            system_prompt=system_prompt,
            max_tokens=512,
        )

        if not result or not result.text:
            return

        # Parse JSON response
        try:
            data = json.loads(result.text)
        except json.JSONDecodeError:
            # Try to extract JSON from the response if wrapped in markdown
            match = re.search(r"\{.*\}", result.text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    return
            else:
                return

        # Store extracted facts
        facts = data.get("facts", [])
        for fact in facts:
            if fact and isinstance(fact, str) and len(fact.strip()) > 5:
                await self.add_memory(
                    entry_type="fact",
                    content=fact.strip(),
                    session_id=self.session_id,
                )

        # Store session summary if requested
        if generate_summary:
            summary = data.get("summary", "")
            if summary and isinstance(summary, str) and len(summary.strip()) > 10:
                await self.add_memory(
                    entry_type="session_summary",
                    content=summary.strip(),
                    session_id=self.session_id,
                )

    async def build_memory_context(self, query_text: str, max_tokens: int = MEMORY_MAX_TOKENS) -> str:
        """Build a formatted memory context string for injection into the system prompt.

        Args:
            query_text: The user's current message to find relevant memories.
            max_tokens: Maximum tokens to use for memory context.

        Returns:
            Formatted memory string, or empty string if no relevant memories.
        """
        # Search for relevant facts
        facts = await self.search(query_text, limit=20, entry_type="fact")

        # Get most recent session summary
        summaries = await self.search(query_text, limit=2, entry_type="session_summary")

        if not facts and not summaries:
            return ""

        parts = []
        token_count = 0

        # Add facts first (compact, high-value)
        if facts:
            fact_lines = []
            for fact in facts:
                line = f"- {fact.content}"
                line_tokens = len(line) // 4
                if token_count + line_tokens > max_tokens:
                    break
                fact_lines.append(line)
                token_count += line_tokens

            if fact_lines:
                parts.append("[Memory - Relevant facts]\n" + "\n".join(fact_lines))

        # Add session summary if room
        if summaries:
            summary = summaries[0]
            summary_tokens = len(summary.content) // 4
            if token_count + summary_tokens <= max_tokens:
                parts.append(f"[Memory - Recent session]\n{summary.content}")

        return "\n\n".join(parts)

    async def forget_by_query(self, query_text: str) -> bool:
        """Find and delete the closest matching memory to the query.

        Returns True if a memory was deleted, False if no close match found.
        """
        embeddings = await self.local_ai_service.embed([query_text])
        if not embeddings or not embeddings[0]:
            return False

        rows = self._db.execute(
            """
            SELECT e.id, e.content, v.distance
            FROM memory_vec v
            JOIN memory_entries e ON e.id = v.entry_id
            WHERE e.collection = ?
            AND v.embedding MATCH ?
            ORDER BY v.distance
            LIMIT 1
            """,
            (self.collection, _serialize_embedding(embeddings[0])),
        ).fetchall()

        if not rows:
            return False

        entry_id, content, distance = rows[0]
        similarity = 1.0 - (distance / 2.0)

        if similarity >= FORGET_SIMILARITY_THRESHOLD:
            self.delete_memory(entry_id)
            return True
        return False

    def close(self) -> None:
        """Close the database connection."""
        if self._db:
            self._db.close()
            self._db = None

    # --- Private helpers ---

    def _find_duplicate(self, embedding: list[float]) -> MemoryEntry | None:
        """Find the most similar existing fact if above DEDUP_THRESHOLD."""
        rows = self._db.execute(
            """
            SELECT e.id, e.collection, e.entry_type, e.content,
                   e.source_wingman, e.session_id, e.created_at, e.updated_at,
                   v.distance
            FROM memory_vec v
            JOIN memory_entries e ON e.id = v.entry_id
            WHERE e.collection = ? AND e.entry_type = 'fact'
            AND v.embedding MATCH ?
            ORDER BY v.distance
            LIMIT 1
            """,
            (self.collection, _serialize_embedding(embedding)),
        ).fetchall()

        if not rows:
            return None

        r = rows[0]
        distance = r[8]
        # sqlite-vec returns cosine distance (0 = identical, 2 = opposite)
        # Convert to similarity: similarity = 1 - (distance / 2)
        similarity = 1.0 - (distance / 2.0)
        if similarity >= DEDUP_THRESHOLD:
            return MemoryEntry(
                id=r[0], collection=r[1], entry_type=r[2], content=r[3],
                source_wingman=r[4], session_id=r[5], created_at=r[6], updated_at=r[7],
            )
        return None

    def _update_entry(self, entry_id: int, content: str, embedding: list[float]) -> None:
        """Update an existing entry's content and embedding."""
        now = time.time()
        self._db.execute(
            "UPDATE memory_entries SET content = ?, updated_at = ? WHERE id = ?",
            (content, now, entry_id),
        )
        # sqlite-vec: delete old, insert new (no UPDATE on virtual tables)
        self._db.execute("DELETE FROM memory_vec WHERE entry_id = ?", (entry_id,))
        self._db.execute(
            "INSERT INTO memory_vec (entry_id, embedding) VALUES (?, ?)",
            (entry_id, _serialize_embedding(embedding)),
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
                f"DELETE FROM memory_vec WHERE entry_id IN ({placeholders})",
                to_delete,
            )
            self._db.execute(
                f"DELETE FROM memory_entries WHERE id IN ({placeholders})",
                to_delete,
            )
            self._db.commit()
