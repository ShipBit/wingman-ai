"""Persistent memory service using SQLite with Python-side vector similarity."""

import asyncio
import json
import math
import re
import sqlite3
import struct
import threading
import time
import uuid
from dataclasses import dataclass
from os import path

from api.enums import LogType
from services.file import get_persistent_memory_dir
from services.memory_debug_log import log_memory_event
from services.printr import Printr
from services.token_utils import count_tokens, truncate_to_tokens

printr = Printr()

# Named constants
MEMORY_MAX_TOKENS = 1024
# Recall threshold for injecting stored facts into the prompt. Lowered from 0.5
# to 0.4 after the internal eval suite showed the embed model (nomic) frequently
# scores a relevant fact 0.40-0.49 against a natural follow-up question ("who do
# I play with?" vs "Friend is named Mara"). build_memory_context returns a
# token-capped SET of facts, so a slightly looser gate lands the right fact in
# the batch without meaningful precision cost.
MEMORY_MIN_SIMILARITY = 0.4

# The absolute threshold is not enough on its own. Some facts sit close to
# everything said in a language: "Prefers to communicate in German" scores
# 0.51-0.54 against any German sentence, the weather, the landing gear, a
# story. So every fact also has a baseline, its similarity to a handful of
# everyday sentences nobody's memory is about, and a fact is recalled only
# when the message beats that baseline by this much. Measured with nomic:
# real hits lie 0.18-0.32 above their baseline, noise at most 0.04, a weak
# hit in another language around 0.07.
RECALL_MIN_LIFT = 0.06
GENERIC_QUERIES = [
    "How is the weather?", "Tell me a story.", "What time is it?", "Open the map.",
    "Thanks, that's all.",
    "Wie ist das Wetter?", "Erzähl mir etwas.", "Wie spät ist es?", "Öffne die Karte.",
    "Danke, das war's.",
    "¿Qué hora es?", "Cuéntame algo.", "Quelle heure est-il ?", "Raconte-moi quelque chose.",
]
DEDUP_THRESHOLD = 0.9
MIN_MESSAGES_FOR_EXTRACTION = 4
FORGET_SIMILARITY_THRESHOLD = 0.7
EMBEDDING_DIMENSIONS = 768  # Nomic Embed v1.5

# Session summaries are a "state of play", and only the latest one is ever
# recalled. Five is history enough to see what the last evenings were about in
# the memory tab; twenty were an activity log nobody read.
MAX_SESSION_SUMMARIES = 5

# Facts a wingman keeps at most. Enforced after each consolidation: the ones
# that have gone longest without being confirmed or updated go first.
MAX_FACTS = 150

# Facts attached to one user message. Eight clean facts say more than twenty
# with the noise in — and everything attached here gets repeated by the model,
# summarised into the history and extracted again.
RECALL_MAX_FACTS = 8

# Consolidation runs when this many facts were *inserted* (not merged into an
# existing one) since the last pass. Merges do not count; they are already tidy.
CONSOLIDATE_AFTER_NEW_FACTS = 10

# Assistant messages go into extraction cut to this many tokens. The model
# needs them for context ("yes, that one" answers a question), not for the
# status report or price table the wingman read out — which is exactly the
# text that used to come back as "facts".
ASSISTANT_EXCERPT_TOKENS = 150

# What a fact may be about. The extraction prompt asks for one of these per
# fact and anything else is dropped here, in code — the prompt alone did not
# stop "Destination is Area18" or "Set a timer for three minutes".
ALLOWED_FACT_KINDS = frozenset(
    {"identity", "possession", "relationship", "affiliation", "goal", "preference"}
)

# Belt and braces for the same problem: wording that marks a moment, not a
# durable fact. Kept narrow on purpose; a false positive here loses a fact,
# a false negative only costs one line until the next consolidation.
_TRANSIENT_FACT_RE = re.compile(
    r"\b(current (time|date|location)|right now|at the moment|a timer|"
    r"destination is|heading to|is parked|is docked|status of|"
    r"\w+ percent|\d+ ?%)\b",
    re.IGNORECASE,
)


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
        # A single sqlite3.Connection is opened with check_same_thread=False and
        # is hit from the default thread pool (every async method dispatches via
        # asyncio.to_thread). Concurrent execute()/commit() on one connection
        # corrupts SQLite's heap and crashes the process with a native SIGSEGV,
        # so ALL connection access must be serialized through this lock. It is
        # reentrant so composite operations (e.g. dedup-check then insert) can
        # hold it across several helper calls and stay atomic. Held only around
        # DB statements -- never around embedding/LLM calls -- to avoid
        # serializing turns on the slow paths.
        self._lock = threading.RLock()
        self._new_facts_since_consolidation = 0
        # Embeddings of GENERIC_QUERIES, computed on the first recall.
        self._generic_embeddings: list[list[float]] | None = None

    def initialize(self) -> None:
        """Create the database and tables if they don't exist."""
        db_dir = get_persistent_memory_dir()
        db_path = path.join(db_dir, "memory.db")
        with self._lock:
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
            CREATE TABLE IF NOT EXISTS memory_backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection TEXT NOT NULL,
                created_at REAL NOT NULL,
                payload TEXT NOT NULL
            );
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

        # Hold the lock across dedup-check + insert so the pair is atomic and
        # never races another thread on the shared connection.
        with self._lock:
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
            elif entry_type == "fact":
                self._new_facts_since_consolidation += 1

            return cursor.lastrowid

    def _update_memory_impl(self, entry_id: int, new_content: str) -> None:
        embeddings = self.local_ai_service.embed([new_content])
        if not embeddings or not embeddings[0]:
            return
        self._update_entry(entry_id, new_content, embeddings[0])

    def _baseline(self, embedding: list[float]) -> float:
        """How similar a fact is to everyday sentences that are about nothing
        in particular: the mean of its three closest. What a message has to
        beat for the fact to count as recalled."""
        if self._generic_embeddings is None:
            vectors = self.local_ai_service.embed(GENERIC_QUERIES)
            self._generic_embeddings = [v for v in (vectors or []) if v]
        if not self._generic_embeddings:
            return 0.0
        scores = sorted((_cosine_similarity(embedding, g) for g in self._generic_embeddings), reverse=True)
        return sum(scores[:3]) / len(scores[:3])

    def _search_impl(
        self,
        query_text: str,
        limit: int = 10,
        entry_type: str | None = None,
        min_similarity: float = 0.0,
        min_lift: float = 0.0,
    ) -> list[MemoryEntry]:
        """`min_lift` > 0 asks for more than closeness: the fact has to be
        closer to the query than to everyday talk by that much."""
        embeddings = self.local_ai_service.embed([query_text])
        if not embeddings or not embeddings[0]:
            return []
        query_embedding = embeddings[0]

        with self._lock:
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
            if similarity < min_similarity:
                continue
            if min_lift > 0 and similarity - self._baseline(stored_embedding) < min_lift:
                continue
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
            if not content or role not in ("user", "assistant"):
                continue
            if role == "assistant" and count_tokens(content) > ASSISTANT_EXCERPT_TOKENS:
                content = truncate_to_tokens(content, ASSISTANT_EXCERPT_TOKENS) + " […]"
            text_parts.append(f"{role}: {content}")

        if not text_parts:
            return

        conversation_text = "\n".join(text_parts)

        from services.file import get_prompt
        from services.skill_local_ai import SamplingPreset

        system_prompt = get_prompt("extract-memories")
        # Reasoning is intentionally OFF here: on the bundled 2B model it rambles
        # 3000+ <think> tokens and truncates before emitting the JSON (0 facts) —
        # proven in the internal eval suite. The rewritten prompt already yields
        # clean facts without it. Skill authors / capable remote models can still
        # opt into reasoning via the per-call param.
        budget = self.local_ai_service.get_token_budget(system_prompt)
        text_tokens = count_tokens(conversation_text)

        if text_tokens <= budget.max_input_tokens:
            # Fits in one pass.
            result = self.local_ai_service.support(
                text=conversation_text,
                system_prompt=system_prompt,
                preset=SamplingPreset.PRECISE,
            )
            log_memory_event(
                "extraction",
                self.wingman_name,
                mode="single",
                reasoning=False,
                generate_summary=generate_summary,
                input_tokens=text_tokens,
                conversation=conversation_text,
                raw_output=result.text if result else None,
                truncated=result.truncated if result else None,
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
                    preset=SamplingPreset.PRECISE,
                )
                log_memory_event(
                    "extraction",
                    self.wingman_name,
                    mode="chunk",
                    reasoning=False,
                    chunk_index=i,
                    chunk_count=len(chunks),
                    conversation=chunk,
                    raw_output=result.text if result else None,
                    truncated=result.truncated if result else None,
                )
                if result and result.text:
                    data = self._parse_json_response(result.text)
                    if data:
                        all_facts.extend(data.get("facts", []))
                        s = data.get("summary", "")
                        if s:
                            last_summary = s

            # Store collected facts
            for fact in self._clean_facts(all_facts):
                self._add_memory_impl(
                    entry_type="fact",
                    content=fact,
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

        for fact in self._clean_facts(data.get("facts", [])):
            self._add_memory_impl(
                entry_type="fact",
                content=fact,
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

    def _clean_facts(self, raw_facts) -> list[str]:
        """Turn the model's fact list into the strings worth storing.

        Accepts both shapes: ``{"kind": ..., "text": ...}`` as the prompt asks
        for, and plain strings from older prompts or a small model that ignored
        the format. A typed fact with a kind outside ``ALLOWED_FACT_KINDS`` is
        dropped; every fact is checked against ``_TRANSIENT_FACT_RE``.
        """
        kept: list[str] = []
        dropped: list[dict] = []
        if not isinstance(raw_facts, list):
            return kept
        for item in raw_facts:
            kind = None
            if isinstance(item, dict):
                kind = str(item.get("kind") or "").strip().lower()
                text = item.get("text") or item.get("fact") or ""
            else:
                text = item
            if not isinstance(text, str):
                continue
            text = text.strip()
            if len(text) <= 5:
                continue
            if kind is not None and kind not in ALLOWED_FACT_KINDS:
                dropped.append({"text": text, "reason": f"kind={kind or 'missing'}"})
                continue
            if _TRANSIENT_FACT_RE.search(text):
                dropped.append({"text": text, "reason": "transient"})
                continue
            kept.append(text)
        if dropped:
            log_memory_event("dropped_facts", self.wingman_name, dropped=dropped)
        return kept

    # --- Consolidation ---

    def _consolidate_impl(self) -> dict:
        """One pass of the support model over the whole fact list.

        Merges duplicates, drops what should never have been stored, and keeps
        the newer of two contradicting facts. Replaces the list atomically; the
        old one is saved to ``memory_backups`` first. Returns
        ``{"before": n, "after": m, "changed": bool}``.

        Refuses the result when the model hands back less than a third of the
        input on a list of five or more — that is a model that lost the plot,
        not a list that was two-thirds noise.
        """
        from services.file import get_prompt
        from services.skill_local_ai import SamplingPreset

        facts = self.get_all(entry_type="fact")
        before = len(facts)
        outcome = {"before": before, "after": before, "changed": False}
        if before < 2:
            self._new_facts_since_consolidation = 0
            return outcome

        # Oldest first, so "keep the newer one" reads top to bottom.
        facts.sort(key=lambda e: e.updated_at)
        listing = "\n".join(f"{i + 1}. {e.content}" for i, e in enumerate(facts))
        system_prompt = get_prompt("consolidate-memories")
        budget = self.local_ai_service.get_token_budget(system_prompt)
        if count_tokens(listing) > budget.max_input_tokens:
            # A local model with a small window: consolidate what fits, keep
            # the rest as it is. Facts are sorted oldest first, so the ones
            # left untouched are the newest and the least likely to be stale.
            listing = truncate_to_tokens(listing, budget.max_input_tokens)
            fitted = listing.count("\n") + 1
            facts, untouched = facts[:fitted], facts[fitted:]
            listing = "\n".join(f"{i + 1}. {e.content}" for i, e in enumerate(facts))
        else:
            untouched = []

        result = self.local_ai_service.support(
            text=f"FACTS:\n{listing}",
            system_prompt=system_prompt,
            preset=SamplingPreset.PRECISE,
        )
        data = self._parse_json_response(result.text) if result and result.text else None
        cleaned = self._clean_facts(data.get("facts", [])) if data else []
        log_memory_event(
            "consolidation",
            self.wingman_name,
            input_facts=[e.content for e in facts],
            raw_output=result.text if result else None,
            kept=cleaned,
        )
        if not cleaned or (len(facts) >= 5 and len(cleaned) < len(facts) / 3):
            printr.print(
                f"Memory consolidation for {self.wingman_name} rejected: model returned "
                f"{len(cleaned)} of {len(facts)} facts.",
                color=LogType.WARNING,
                server_only=True,
            )
            return outcome

        # Same set, nothing to write. Rewriting would only reset timestamps.
        if [e.content for e in facts] == cleaned:
            self._new_facts_since_consolidation = 0
            return outcome

        embeddings = self.local_ai_service.embed(cleaned)
        if not embeddings or len(embeddings) != len(cleaned):
            return outcome

        now = time.time()
        with self._lock:
            self._db.execute(
                "INSERT INTO memory_backups (collection, created_at, payload) VALUES (?, ?, ?)",
                (self.collection, now, json.dumps([e.content for e in facts])),
            )
            self._db.execute(
                """DELETE FROM memory_backups WHERE collection = ? AND id NOT IN (
                       SELECT id FROM memory_backups WHERE collection = ?
                       ORDER BY created_at DESC LIMIT 3)""",
                (self.collection, self.collection),
            )
            ids = [e.id for e in facts]
            placeholders = ",".join("?" * len(ids))
            self._db.execute(
                f"DELETE FROM memory_entries WHERE id IN ({placeholders})", ids
            )
            for content, embedding in zip(cleaned, embeddings):
                self._db.execute(
                    """INSERT INTO memory_entries
                       (collection, entry_type, content, embedding,
                        source_wingman, session_id, created_at, updated_at)
                       VALUES (?, 'fact', ?, ?, ?, ?, ?, ?)""",
                    (
                        self.collection, content, _serialize_embedding(embedding),
                        self.wingman_name, self.session_id, now, now,
                    ),
                )
            self._db.commit()
            self._enforce_fact_cap()
            after = len(self.get_all(entry_type="fact"))

        self._new_facts_since_consolidation = 0
        outcome.update(after=after, changed=True)
        printr.print(
            f"Memory consolidated for {self.wingman_name}: {before} facts → {after}"
            + (f" ({len(untouched)} newest left as they were)" if untouched else "")
            + ".",
            color=LogType.MEMORY,
        )
        return outcome

    def _enforce_fact_cap(self) -> None:
        """Drop the facts that went longest without an update beyond MAX_FACTS."""
        with self._lock:
            rows = self._db.execute(
                """SELECT id FROM memory_entries
                   WHERE collection = ? AND entry_type = 'fact'
                   ORDER BY updated_at DESC""",
                (self.collection,),
            ).fetchall()
            if len(rows) > MAX_FACTS:
                to_delete = [r[0] for r in rows[MAX_FACTS:]]
                placeholders = ",".join("?" * len(to_delete))
                self._db.execute(
                    f"DELETE FROM memory_entries WHERE id IN ({placeholders})",
                    to_delete,
                )
                self._db.commit()

    def _build_memory_context_impl(
        self, query_text: str, max_tokens: int = MEMORY_MAX_TOKENS
    ) -> str:
        facts = self._search_impl(
            query_text, limit=RECALL_MAX_FACTS, entry_type="fact",
            min_similarity=MEMORY_MIN_SIMILARITY, min_lift=RECALL_MIN_LIFT,
        )
        # The latest session, by time — not the most similar one. "Where were we"
        # is a question about last night, not about whichever evening happened
        # to use the same words.
        summaries = self.get_all(entry_type="session_summary")[:1]

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

        with self._lock:
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

    async def consolidate(self) -> dict:
        """Tidy the fact list with one support-model pass. See ``_consolidate_impl``."""
        return await asyncio.to_thread(self._consolidate_impl)

    async def maybe_consolidate(self) -> dict | None:
        """Consolidate when enough new facts arrived since the last pass."""
        if self._new_facts_since_consolidation < CONSOLIDATE_AFTER_NEW_FACTS:
            return None
        return await self.consolidate()

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
        with self._lock:
            self._db.execute("DELETE FROM memory_entries WHERE id = ?", (entry_id,))
            self._db.commit()

    def clear_collection(self) -> None:
        """Delete all memories for this Wingman's collection."""
        with self._lock:
            self._db.execute(
                "DELETE FROM memory_entries WHERE collection = ?", (self.collection,)
            )
            self._db.commit()

    def get_all(self, entry_type: str | None = None) -> list[MemoryEntry]:
        """Get all memories for this Wingman's collection."""
        with self._lock:
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
        with self._lock:
            if self._db:
                self._db.close()
                self._db = None

    def get_tool_definitions(self) -> list[dict]:
        """Return the OpenAI-style tool definitions for persistent memory operations.
        These are exposed to the LLM whenever a PersistentMemoryService is active."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "memory_remember",
                    "description": "Store something about the user that is meant to last: how they want to be addressed, a standing instruction, a preference, a fact about them or their life. Use it right away when the user tells you such a thing or asks you to remember something; do not wait to be asked twice.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "The fact or detail to remember.",
                            },
                        },
                        "required": ["text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "memory_recall",
                    "description": "Search your memory for relevant information. Use when the user asks what you remember or know about a topic.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "What to search for in memory.",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "memory_forget",
                    "description": "Remove a specific memory. Use when the user explicitly asks you to forget something.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Description of the memory to forget.",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
        ]

    # --- Private helpers ---

    def _find_duplicate(self, embedding: list[float]) -> MemoryEntry | None:
        """Find the most similar existing fact if above DEDUP_THRESHOLD."""
        with self._lock:
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
        with self._lock:
            self._db.execute(
                """UPDATE memory_entries
                   SET content = ?, embedding = ?, updated_at = ?
                   WHERE id = ?""",
                (content, _serialize_embedding(embedding), now, entry_id),
            )
            self._db.commit()

    def _enforce_summary_cap(self) -> None:
        """Delete oldest session summaries beyond MAX_SESSION_SUMMARIES."""
        with self._lock:
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
