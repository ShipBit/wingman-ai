"""Persistent memory: what a wingman knows about the user across sessions.

Two kinds of memory, kept apart because they age differently:

``fact``     timeless statements about the user ("Owns a Cutlass Black"). A
             newer statement replaces an older one that contradicts it; the
             list is rewritten as a whole at every checkpoint.
``episode``  one entry per session: what happened, what was memorable, what
             is still open. Never rewritten after the session ends, only
             aged out. The three most recent go into the system prompt with
             their age, so the model knows which one is current.

Writes happen at checkpoints: every CHECKPOINT_TURNS user turns or
CHECKPOINT_SECONDS, at the end of a session (unload, reset, IDLE_SECONDS
without a user turn), and through the ``memory_remember`` tool. One support
call per checkpoint gets the stored facts, the episode so far and the new
messages, and returns the list as it should be from now on.

Reads do not search. Every fact (capped) and the recent episodes go into the
system prompt as one block that only changes at checkpoints, so the
provider's prompt cache covers it. Embeddings remain for deduplication, the
``memory_recall`` and ``memory_forget`` tools, and the memory tab's search.

Older databases hold ``session_summary`` rows; they are read as episodes.
"""

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

DEDUP_THRESHOLD = 0.9
FORGET_SIMILARITY_THRESHOLD = 0.7
EMBEDDING_DIMENSIONS = 768  # Nomic Embed v1.5

# A checkpoint runs after this many user turns or this many seconds since the
# last one, whichever comes first. Both are counted by the wingman.
CHECKPOINT_TURNS = 25
CHECKPOINT_SECONDS = 20 * 60

# No user turn for this long ends the session: the episode is closed and the
# next message starts a new one.
IDLE_SECONDS = 30 * 60

# A session with fewer user turns than this at its end is not worth a
# support call: a mic test, a greeting, two commands. Nothing durable is said
# in it, and the moods that were once stored as facts came from exactly
# these sessions.
MIN_USER_TURNS = 4

# Facts a wingman keeps at most. The ones that have gone longest without
# being confirmed or updated go first.
MAX_FACTS = 150
# Facts in the system prompt, most recently updated first. About 400 tokens.
FACTS_IN_PROMPT = 40

MAX_EPISODES = 5
EPISODES_IN_PROMPT = 3
EPISODE_MAX_AGE_DAYS = 30

# Assistant messages go into a checkpoint cut to this many tokens. The model
# needs them for context ("yes, that one" answers a question), not for the
# status report or price table the wingman read out.
ASSISTANT_EXCERPT_TOKENS = 150

# What a fact may be about. The prompt asks for one of these per fact and
# anything else is dropped here, in code.
ALLOWED_FACT_KINDS = frozenset(
    {"identity", "possession", "relationship", "affiliation", "goal", "preference"}
)

# Wording that marks a moment, not a durable fact. Kept narrow on purpose; a
# false positive here loses a fact, a false negative costs one line until the
# next checkpoint rewrites the list.
_TRANSIENT_FACT_RE = re.compile(
    r"\b(current (time|date|location)|right now|at the moment|a timer|"
    r"destination is|heading to|is parked|is docked|status of|"
    r"\w+ percent|\d+ ?%)\b",
    re.IGNORECASE,
)

EPISODE_TYPES = ("episode", "session_summary")


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
    return struct.pack(f"{len(embedding)}f", *embedding)


def _deserialize_embedding(blob: bytes) -> list[float]:
    count = len(blob) // 4  # 4 bytes per float32
    return list(struct.unpack(f"{count}f", blob))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot_product = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)


def age_label(created_at: float, now: float | None = None) -> str:
    """How long ago, in words the model can weigh: "earlier today",
    "yesterday", "5 days ago", "3 weeks ago"."""
    now = now or time.time()
    days = int((now - created_at) // 86400)
    if days <= 0:
        return "earlier today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    return f"{days // 7} weeks ago"


class PersistentMemoryService:
    """Per-Wingman persistent memory backed by SQLite.

    All instances share the same memory.db file, scoped by collection name.
    Public methods come in async/sync pairs. The async versions run the
    support and embedding calls in a thread pool.
    """

    def __init__(self, wingman_name: str, local_ai_service):
        self.wingman_name = wingman_name
        self.collection = f"wingman:{wingman_name}"
        self.local_ai_service = local_ai_service
        self.session_id = str(uuid.uuid4())
        self._db: sqlite3.Connection | None = None
        # A single sqlite3.Connection is opened with check_same_thread=False and
        # is hit from the default thread pool. Concurrent execute()/commit() on
        # one connection corrupts SQLite's heap and crashes the process, so ALL
        # connection access is serialized through this lock. Reentrant so
        # composite operations (dedup-check then insert) stay atomic. Held only
        # around DB statements, never around embedding or support calls.
        self._lock = threading.RLock()
        # The system prompt block, rebuilt after every write.
        self._block: str | None = None

    def initialize(self) -> None:
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

    # ── sessions ───────────────────────────────────────────────────

    def new_session(self) -> None:
        """The next checkpoint writes a new episode."""
        self.session_id = str(uuid.uuid4())
        self._block = None

    # ── writes ─────────────────────────────────────────────────────

    def _add_memory_impl(
        self, entry_type: str, content: str, session_id: str | None = None
    ) -> int | None:
        embeddings = self.local_ai_service.embed([content])
        if not embeddings or not embeddings[0]:
            return None
        embedding = embeddings[0]

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
            if entry_type in EPISODE_TYPES:
                self._enforce_episode_cap()
            self._block = None
            return cursor.lastrowid

    def _update_memory_impl(self, entry_id: int, new_content: str) -> None:
        embeddings = self.local_ai_service.embed([new_content])
        if not embeddings or not embeddings[0]:
            return
        self._update_entry(entry_id, new_content, embeddings[0])

    # ── search (tools, forget, memory tab) ─────────────────────────

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
            similarity = _cosine_similarity(query_embedding, _deserialize_embedding(r[4]))
            if similarity < min_similarity:
                continue
            scored.append((similarity, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            MemoryEntry(
                id=r[0], collection=r[1], entry_type=r[2], content=r[3],
                source_wingman=r[5], session_id=r[6], created_at=r[7], updated_at=r[8],
            )
            for _, r in scored[:limit]
        ]

    # ── parsing helpers ────────────────────────────────────────────

    def _parse_json_response(self, text: str) -> dict | None:
        """Parse JSON from model output, repairing common small-model issues."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        raw = match.group()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        repaired = re.sub(r'"\s*\n\s*"', '", "', raw)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _extract_text_content(content) -> str:
        """Plain text from message content (string or multimodal list)."""
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

    @classmethod
    def conversation_text(cls, messages: list) -> tuple[str, int]:
        """The transcript a checkpoint sees, and how many user turns it holds.

        Assistant lines are cut short: the model needs them for context, not
        for the status report or price table the wingman read out, which is
        exactly the text that used to come back as facts.
        """
        parts = []
        user_turns = 0
        for msg in messages:
            role = msg.get("role", "") if isinstance(msg, dict) else getattr(msg, "role", "")
            raw = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
            content = cls._extract_text_content(raw)
            if not content or role not in ("user", "assistant"):
                continue
            if role == "assistant" and count_tokens(content) > ASSISTANT_EXCERPT_TOKENS:
                content = truncate_to_tokens(content, ASSISTANT_EXCERPT_TOKENS) + " […]"
            if role == "user":
                user_turns += 1
            parts.append(f"{role}: {content}")
        return "\n".join(parts), user_turns

    def _clean_facts(self, raw_facts) -> list[str]:
        """The model's fact list, reduced to the strings worth storing.

        Accepts ``{"kind": ..., "text": ...}`` as the prompt asks for, and
        plain strings from a model that ignored the format. A typed fact
        outside ``ALLOWED_FACT_KINDS`` is dropped; every fact is checked
        against ``_TRANSIENT_FACT_RE``. Duplicates within the list are folded.
        """
        kept: list[str] = []
        seen: set[str] = set()
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
            key = text.lower().rstrip(".")
            if key in seen:
                continue
            seen.add(key)
            kept.append(text)
        if dropped:
            log_memory_event("dropped_facts", self.wingman_name, dropped=dropped)
        return kept

    @staticmethod
    def _worth_keeping(episode) -> bool:
        """An episode earns its place with something to bring up again or
        something still open. A plain string (older prompt) is kept."""
        if isinstance(episode, str):
            return bool(episode.strip())
        if not isinstance(episode, dict):
            return False
        return bool(str(episode.get("memorable") or "").strip() or str(episode.get("open") or "").strip())

    @staticmethod
    def episode_text(episode) -> str:
        """The stored form of an episode: one paragraph, open threads last."""
        if isinstance(episode, str):
            return episode.strip()
        if not isinstance(episode, dict):
            return ""
        happened = str(episode.get("happened") or "").strip()
        memorable = str(episode.get("memorable") or "").strip()
        open_thread = str(episode.get("open") or "").strip()
        parts = [p for p in (happened, memorable) if p]
        text = " ".join(parts)
        if open_thread:
            text = f"{text} Open: {open_thread}".strip()
        return text

    # ── checkpoint ─────────────────────────────────────────────────

    def _current_episode(self) -> MemoryEntry | None:
        with self._lock:
            row = self._db.execute(
                """SELECT id, collection, entry_type, content, source_wingman,
                          session_id, created_at, updated_at
                   FROM memory_entries
                   WHERE collection = ? AND entry_type = 'episode' AND session_id = ?""",
                (self.collection, self.session_id),
            ).fetchone()
        if not row:
            return None
        return MemoryEntry(
            id=row[0], collection=row[1], entry_type=row[2], content=row[3],
            source_wingman=row[4], session_id=row[5], created_at=row[6], updated_at=row[7],
        )

    def _checkpoint_input(self, facts: list[MemoryEntry], episode: str,
                          earlier: str, transcript: str) -> str:
        listing = "\n".join(f"{i + 1}. {e.content}" for i, e in enumerate(facts)) or "(none)"
        parts = [f"STORED FACTS:\n{listing}", f"EPISODE SO FAR:\n{episode or '(none)'}"]
        if earlier:
            parts.append(f"EARLIER IN THIS SESSION, CONDENSED:\n{earlier}")
        parts.append(f"NEW MESSAGES:\n{transcript or '(none)'}")
        return "\n\n".join(parts)

    def _checkpoint_impl(
        self,
        messages: list,
        conversation_summary: str = "",
        final: bool = False,
        tidy_only: bool = False,
    ) -> dict:
        """One support call: stored facts + episode so far + new messages in,
        the whole fact list and the episode out.

        ``final`` closes the session afterwards. ``tidy_only`` is the memory
        tab's button: rewrite the facts with no new messages, leave the
        episode alone. Returns ``{"before", "after", "changed", "episode",
        "skipped"}``.
        """
        from services.file import get_prompt
        from services.skill_local_ai import SamplingPreset

        transcript, user_turns = self.conversation_text(messages)
        outcome = {"before": 0, "after": 0, "changed": False, "episode": "", "skipped": ""}

        if not tidy_only and user_turns == 0 and not conversation_summary:
            outcome["skipped"] = "nothing new"
            return outcome
        if not tidy_only and final and user_turns < MIN_USER_TURNS and not self._current_episode():
            outcome["skipped"] = f"{user_turns} user turns"
            return outcome

        facts = self.get_all(entry_type="fact")
        facts.sort(key=lambda e: e.updated_at)  # oldest first: "newer wins" reads top down
        current = self._current_episode()
        episode_so_far = current.content if current else ""
        before = len(facts)
        outcome.update(before=before, after=before)

        system_prompt = get_prompt("extract-memories")
        budget = self.local_ai_service.get_token_budget(system_prompt)
        fixed = self._checkpoint_input(facts, episode_so_far, conversation_summary, "")
        room = budget.max_input_tokens - count_tokens(fixed)
        if room < 200:
            # A local model with a window too small for its own fact list:
            # the newest facts stay as they are, the rest is what fits.
            listing_budget = max(0, budget.max_input_tokens - 600)
            while facts and count_tokens(self._checkpoint_input(facts, episode_so_far, "", "")) > listing_budget:
                facts = facts[:-1]
            fixed = self._checkpoint_input(facts, episode_so_far, conversation_summary, "")
            room = max(200, budget.max_input_tokens - count_tokens(fixed))
        chunks = self._split(transcript, room) if transcript else [""]

        data = None
        last_episode = None
        for i, chunk in enumerate(chunks):
            text = self._checkpoint_input(facts, episode_so_far, conversation_summary if i == 0 else "", chunk)
            result = self.local_ai_service.support(
                text=text, system_prompt=system_prompt, preset=SamplingPreset.PRECISE,
            )
            data = self._parse_json_response(result.text) if result and result.text else None
            log_memory_event(
                "checkpoint", self.wingman_name, final=final, tidy_only=tidy_only,
                chunk_index=i, chunk_count=len(chunks), input_text=text,
                raw_output=result.text if result else None,
                truncated=result.truncated if result else None,
            )
            if not data:
                outcome["skipped"] = "no usable answer"
                return outcome
            cleaned = self._clean_facts(data.get("facts", []))
            if not cleaned and facts or (len(facts) >= 5 and len(cleaned) < len(facts) / 3):
                # A model that lost the plot, not a list that was two-thirds noise.
                printr.print(
                    f"Memory checkpoint for {self.wingman_name} rejected: model returned "
                    f"{len(cleaned)} of {len(facts)} facts.",
                    color=LogType.WARNING, server_only=True,
                )
                outcome["skipped"] = "too many facts lost"
                return outcome
            if not tidy_only:
                last_episode = data.get("episode") or data.get("summary") or ""
                episode_so_far = self.episode_text(last_episode) or episode_so_far
            if [e.content for e in facts] != cleaned:
                self._replace_facts(facts, cleaned)
                outcome["changed"] = True
            facts = self.get_all(entry_type="fact")
            facts.sort(key=lambda e: e.updated_at)

        if not tidy_only and episode_so_far and len(episode_so_far) > 10:
            if final and not self._worth_keeping(last_episode):
                # A session with nothing memorable and nothing open is a
                # log of what was done, and the models write one for every
                # flight. Mid-session it stays so the next checkpoint can
                # continue it; at the end it goes.
                current = self._current_episode()
                if current:
                    self.delete_memory(current.id)
            else:
                self._upsert_episode(episode_so_far)
                outcome["episode"] = episode_so_far
        outcome["after"] = len(self.get_all(entry_type="fact"))
        self._block = None
        if final:
            self.new_session()
        return outcome

    @staticmethod
    def _split(text: str, max_tokens: int) -> list[str]:
        chunks = []
        remaining = text
        approx_chars = max_tokens * 4
        while remaining:
            if count_tokens(remaining) <= max_tokens:
                chunks.append(remaining)
                break
            split_at = remaining.rfind("\n", 0, approx_chars)
            if split_at <= 0:
                split_at = approx_chars
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip()
        return chunks or [""]

    def _replace_facts(self, old: list[MemoryEntry], new: list[str]) -> None:
        """Swap the fact list atomically, the old one saved to memory_backups.

        A fact whose text is unchanged keeps its row and timestamps, so the
        "longest unconfirmed" order behind MAX_FACTS still means something.
        """
        old_by_text = {e.content: e for e in old}
        added = [f for f in new if f not in old_by_text]
        removed = [e for e in old if e.content not in set(new)]
        embeddings = self.local_ai_service.embed(added) if added else []
        if added and (not embeddings or len(embeddings) != len(added)):
            return
        now = time.time()
        with self._lock:
            self._db.execute(
                "INSERT INTO memory_backups (collection, created_at, payload) VALUES (?, ?, ?)",
                (self.collection, now, json.dumps([e.content for e in old])),
            )
            self._db.execute(
                """DELETE FROM memory_backups WHERE collection = ? AND id NOT IN (
                       SELECT id FROM memory_backups WHERE collection = ?
                       ORDER BY created_at DESC LIMIT 3)""",
                (self.collection, self.collection),
            )
            if removed:
                ids = [e.id for e in removed]
                self._db.execute(
                    f"DELETE FROM memory_entries WHERE id IN ({','.join('?' * len(ids))})", ids
                )
            for content, embedding in zip(added, embeddings):
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
        self._block = None

    def _upsert_episode(self, text: str) -> None:
        current = self._current_episode()
        if current:
            self._update_memory_impl(current.id, text)
        else:
            self._add_memory_impl("episode", text, session_id=self.session_id)
        self._block = None

    def _enforce_fact_cap(self) -> None:
        with self._lock:
            rows = self._db.execute(
                """SELECT id FROM memory_entries
                   WHERE collection = ? AND entry_type = 'fact'
                   ORDER BY updated_at DESC""",
                (self.collection,),
            ).fetchall()
            if len(rows) > MAX_FACTS:
                to_delete = [r[0] for r in rows[MAX_FACTS:]]
                self._db.execute(
                    f"DELETE FROM memory_entries WHERE id IN ({','.join('?' * len(to_delete))})",
                    to_delete,
                )
                self._db.commit()

    def _enforce_episode_cap(self) -> None:
        with self._lock:
            rows = self._db.execute(
                """SELECT id FROM memory_entries
                   WHERE collection = ? AND entry_type IN ('episode', 'session_summary')
                   ORDER BY created_at DESC""",
                (self.collection,),
            ).fetchall()
            if len(rows) > MAX_EPISODES:
                to_delete = [r[0] for r in rows[MAX_EPISODES:]]
                self._db.execute(
                    f"DELETE FROM memory_entries WHERE id IN ({','.join('?' * len(to_delete))})",
                    to_delete,
                )
                self._db.commit()

    # ── the system prompt block ────────────────────────────────────

    def episodes(self, now: float | None = None) -> list[MemoryEntry]:
        """Closed episodes young enough for the prompt, oldest first."""
        now = now or time.time()
        cutoff = now - EPISODE_MAX_AGE_DAYS * 86400
        rows = [
            e for e in self.get_all()
            if e.entry_type in EPISODE_TYPES and e.session_id != self.session_id
            and e.created_at >= cutoff
        ]
        rows.sort(key=lambda e: e.created_at)
        return rows[-EPISODES_IN_PROMPT:]

    def prompt_facts(self) -> list[MemoryEntry]:
        facts = self.get_all(entry_type="fact")
        facts.sort(key=lambda e: e.updated_at, reverse=True)
        return facts[:FACTS_IN_PROMPT]

    def memory_block(self) -> str:
        """The MEMORY section of the system prompt; empty when there is nothing.
        Cached until the next write."""
        if self._block is not None:
            return self._block
        facts = self.prompt_facts()
        episodes = self.episodes()
        if not facts and not episodes:
            self._block = ""
            return ""
        parts = ["# MEMORY", "What you know about the user from earlier sessions."]
        if facts:
            parts.append("\nFacts:\n" + "\n".join(f"- {e.content}" for e in facts))
        if episodes:
            now = time.time()
            parts.append(
                "\nRecent sessions, oldest first. Only the last one is current; the "
                "earlier ones are past events the user may want to talk about.\n"
                + "\n".join(f"- {age_label(e.created_at, now)}: {e.content}" for e in episodes)
            )
        self._block = "\n".join(parts)
        return self._block

    def block_stats(self) -> tuple[int, int]:
        """(facts, episodes) the block holds; for the one line in the log."""
        return len(self.prompt_facts()), len(self.episodes())

    # ── forget ─────────────────────────────────────────────────────

    def _forget_by_query_impl(self, query_text: str) -> bool:
        hits = self._search_impl(query_text, limit=1)
        if not hits:
            return False
        embeddings = self.local_ai_service.embed([query_text])
        # _search_impl already ranked; re-check the threshold on the best hit.
        best = hits[0]
        with self._lock:
            row = self._db.execute(
                "SELECT embedding FROM memory_entries WHERE id = ?", (best.id,)
            ).fetchone()
        if not row or not embeddings or not embeddings[0]:
            return False
        if _cosine_similarity(embeddings[0], _deserialize_embedding(row[0])) < FORGET_SIMILARITY_THRESHOLD:
            return False
        self.delete_memory(best.id)
        return True

    # ── async public API ───────────────────────────────────────────

    async def add_memory(self, entry_type: str, content: str, session_id: str | None = None) -> int | None:
        return await asyncio.to_thread(self._add_memory_impl, entry_type, content, session_id)

    async def update_memory(self, entry_id: int, new_content: str) -> None:
        await asyncio.to_thread(self._update_memory_impl, entry_id, new_content)

    async def search(self, query_text: str, limit: int = 10, entry_type: str | None = None) -> list[MemoryEntry]:
        return await asyncio.to_thread(self._search_impl, query_text, limit, entry_type)

    async def checkpoint(self, messages: list, conversation_summary: str = "", final: bool = False) -> dict:
        """Write what the new messages add to memory. See ``_checkpoint_impl``."""
        return await asyncio.to_thread(self._checkpoint_impl, messages, conversation_summary, final)

    async def consolidate(self) -> dict:
        """Rewrite the fact list with no new messages: the memory tab's button."""
        return await asyncio.to_thread(self._checkpoint_impl, [], "", False, True)

    async def forget_by_query(self, query_text: str) -> bool:
        return await asyncio.to_thread(self._forget_by_query_impl, query_text)

    # ── sync public API ────────────────────────────────────────────

    def add_memory_sync(self, entry_type: str, content: str, session_id: str | None = None) -> int | None:
        return self._add_memory_impl(entry_type, content, session_id)

    def update_memory_sync(self, entry_id: int, new_content: str) -> None:
        self._update_memory_impl(entry_id, new_content)

    def search_sync(self, query_text: str, limit: int = 10, entry_type: str | None = None) -> list[MemoryEntry]:
        return self._search_impl(query_text, limit, entry_type)

    def checkpoint_sync(self, messages: list, conversation_summary: str = "", final: bool = False) -> dict:
        return self._checkpoint_impl(messages, conversation_summary, final)

    def forget_by_query_sync(self, query_text: str) -> bool:
        return self._forget_by_query_impl(query_text)

    # ── plain DB access ────────────────────────────────────────────

    def delete_memory(self, entry_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM memory_entries WHERE id = ?", (entry_id,))
            self._db.commit()
        self._block = None

    def clear_collection(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM memory_entries WHERE collection = ?", (self.collection,))
            self._db.commit()
        self._block = None

    def get_all(self, entry_type: str | None = None) -> list[MemoryEntry]:
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
                source_wingman=r[4], session_id=r[5], created_at=r[6], updated_at=r[7],
            )
            for r in rows
        ]

    def close(self) -> None:
        with self._lock:
            if self._db:
                self._db.close()
                self._db = None

    def get_tool_definitions(self) -> list[dict]:
        """OpenAI-style tool definitions, exposed to the LLM whenever a
        PersistentMemoryService is active."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "memory_remember",
                    "description": "Store something about the user that should still hold next month: how they want to be addressed, which language to answer in, a standing instruction, what they own, who they play with, what they like or dislike, a goal. Use it right away when the user says such a thing; do not wait to be asked twice. Not for where they are, what they are doing right now, a status, or a mood.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "The fact, one short sentence in third person."},
                        },
                        "required": ["text"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "memory_recall",
                    "description": "Search your memory. Use only when the user asks what you remember or know about them; never for a question about the world or the game.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "What to search for in memory."},
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
                            "query": {"type": "string", "description": "Description of the memory to forget."},
                        },
                        "required": ["query"],
                    },
                },
            },
        ]

    # ── private helpers ────────────────────────────────────────────

    def _find_duplicate(self, embedding: list[float]) -> MemoryEntry | None:
        """The most similar existing fact if above DEDUP_THRESHOLD."""
        with self._lock:
            rows = self._db.execute(
                """SELECT id, collection, entry_type, content, embedding,
                          source_wingman, session_id, created_at, updated_at
                   FROM memory_entries
                   WHERE collection = ? AND entry_type = 'fact'
                   AND embedding IS NOT NULL""",
                (self.collection,),
            ).fetchall()
        best_row, best = None, -1.0
        for r in rows:
            similarity = _cosine_similarity(embedding, _deserialize_embedding(r[4]))
            if similarity > best:
                best, best_row = similarity, r
        if best_row is not None and best >= DEDUP_THRESHOLD:
            return MemoryEntry(
                id=best_row[0], collection=best_row[1], entry_type=best_row[2],
                content=best_row[3], source_wingman=best_row[5], session_id=best_row[6],
                created_at=best_row[7], updated_at=best_row[8],
            )
        return None

    def _update_entry(self, entry_id: int, content: str, embedding: list[float]) -> None:
        now = time.time()
        with self._lock:
            self._db.execute(
                "UPDATE memory_entries SET content = ?, embedding = ?, updated_at = ? WHERE id = ?",
                (content, _serialize_embedding(embedding), now, entry_id),
            )
            self._db.commit()
        self._block = None
