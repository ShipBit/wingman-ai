import json
import sqlite3
import uuid
from datetime import datetime, timezone
from os import path
from typing import Optional

from api.interface import (
    GenerateBackstoryResponse,
    LoreCharacter,
    LoreCharacterCreate,
    LoreCharacterUpdate,
    LoreCodexEntry,
    LoreCodexEntryCreate,
    LoreCodexEntryUpdate,
    LorePersonalityAxis,
    LorePersonalityAxisCreate,
    LoreRelationship,
    LoreRelationshipCreate,
    LoreRelationshipUpdate,
    LoreUniverse,
    LoreUniverseCreate,
    LoreUniverseUpdate,
    MigrateBackstoryRequest,
    MigrateBackstoryResponse,
)
from services.file import get_lore_library_dir
from services.printr import Printr

printr = Printr()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS universes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS characters (
    id TEXT PRIMARY KEY,
    universe_id TEXT NOT NULL REFERENCES universes(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    nickname TEXT,
    gender TEXT,
    age TEXT,
    species TEXT,
    role TEXT,
    faction TEXT,
    title TEXT,
    appearance TEXT,
    personality_summary TEXT,
    speaking_style TEXT,
    backstory_text TEXT,
    secrets TEXT,
    directives TEXT,
    free_notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(universe_id, name)
);

CREATE TABLE IF NOT EXISTS personality_axes (
    id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    axis_name TEXT NOT NULL,
    value INTEGER NOT NULL CHECK(value BETWEEN 1 AND 10),
    note TEXT,
    UNIQUE(character_id, axis_name)
);

CREATE TABLE IF NOT EXISTS codex_entries (
    id TEXT PRIMARY KEY,
    universe_id TEXT NOT NULL REFERENCES universes(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    category TEXT,
    content TEXT NOT NULL,
    tags TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(universe_id, title)
);

CREATE TABLE IF NOT EXISTS relationships (
    id TEXT PRIMARY KEY,
    universe_id TEXT NOT NULL REFERENCES universes(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL CHECK(source_type IN ('character', 'codex')),
    source_id TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK(target_type IN ('character', 'codex')),
    target_id TEXT NOT NULL,
    relationship_type TEXT,
    description TEXT,
    bidirectional INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('character', 'codex', 'universe')),
    entity_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    mime_type TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_characters_name ON characters(name);
CREATE INDEX IF NOT EXISTS idx_characters_universe ON characters(universe_id);
CREATE INDEX IF NOT EXISTS idx_codex_title ON codex_entries(title);
CREATE INDEX IF NOT EXISTS idx_codex_universe ON codex_entries(universe_id);
CREATE INDEX IF NOT EXISTS idx_codex_category ON codex_entries(universe_id, category);
CREATE INDEX IF NOT EXISTS idx_relationships_source ON relationships(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_relationships_target ON relationships(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_relationships_universe ON relationships(universe_id);
CREATE INDEX IF NOT EXISTS idx_personality_axes_character ON personality_axes(character_id);

CREATE TRIGGER IF NOT EXISTS trg_delete_character_relationships
AFTER DELETE ON characters
BEGIN
    DELETE FROM relationships
    WHERE (source_type = 'character' AND source_id = OLD.id)
       OR (target_type = 'character' AND target_id = OLD.id);
    DELETE FROM attachments
    WHERE entity_type = 'character' AND entity_id = OLD.id;
END;

CREATE TRIGGER IF NOT EXISTS trg_delete_codex_relationships
AFTER DELETE ON codex_entries
BEGIN
    DELETE FROM relationships
    WHERE (source_type = 'codex' AND source_id = OLD.id)
       OR (target_type = 'codex' AND target_id = OLD.id);
    DELETE FROM attachments
    WHERE entity_type = 'codex' AND entity_id = OLD.id;
END;
"""

# LLM tool schemas in OpenAI function calling format
LORE_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_character",
            "description": (
                "Retrieve detailed information about a character in your universe. "
                "Returns their full profile including your relationship with them. "
                "Use this when you need to reference another character's background, "
                "appearance, abilities, or your shared history during roleplay."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The name of the character to look up.",
                    }
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_codex",
            "description": (
                "Look up a lore entry from your universe's codex — events, locations, "
                "factions, technology, or other world knowledge. Use this when a "
                "conversation touches on universe lore you need details about."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The title or topic to look up in the codex.",
                    }
                },
                "required": ["topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_lore",
            "description": (
                "Search your universe's lore library for characters and codex entries "
                "matching a query. Returns brief summaries. Use this when you're not "
                "sure of the exact name or want to find related lore."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to find matching lore.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_lore",
            "description": (
                "List all characters and codex entries available in your universe. "
                "Use this to see what lore is available."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]

LORE_TOOL_NAMES = {"get_character", "get_codex", "search_lore", "list_lore"}

MIGRATION_EXTRACTION_PROMPT = """You are a data extraction assistant. Given the following character backstory,
extract structured information into the JSON format below. Be thorough — capture
all characters mentioned, their traits, relationships, and any world lore
(events, locations, factions).

For personality axes, rate each character on these scales (1-10):
Courage, Humor, Intelligence, Loyalty, Empathy, Aggression, Charisma, Discipline

BACKSTORY:
{backstory_text}

{language_hint}

OUTPUT FORMAT (respond with ONLY valid JSON, no markdown):
{{
  "characters": [
    {{
      "name": "string",
      "gender": "string or null",
      "age": "string or null",
      "species": "string or null",
      "role": "string or null",
      "faction": "string or null",
      "title": "string or null",
      "appearance": "string or null",
      "personality_summary": "string or null",
      "speaking_style": "string or null",
      "backstory_text": "string or null",
      "secrets": "string or null",
      "directives": "string or null",
      "free_notes": "string or null",
      "personality_axes": [
        {{"axis_name": "string", "value": 1-10, "note": "string or null"}}
      ]
    }}
  ],
  "codex_entries": [
    {{
      "title": "string",
      "category": "Event|Location|Faction|Technology|Custom",
      "content": "string",
      "tags": "comma-separated string or null"
    }}
  ],
  "relationships": [
    {{
      "source_name": "string (character or codex entry name)",
      "source_type": "character|codex",
      "target_name": "string (character or codex entry name)",
      "target_type": "character|codex",
      "relationship_type": "ally|enemy|mentor|rival|family|custom",
      "description": "string",
      "bidirectional": true
    }}
  ],
  "warnings": ["string"]
}}"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class LoreLibraryService:
    def __init__(self):
        self.db_path = path.join(get_lore_library_dir(), "lore.db")
        self._init_db()

    # ── Database Setup ────────────────────────────────────────────────────

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    # ── Universes ─────────────────────────────────────────────────────────

    def get_universes(self) -> list[LoreUniverse]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM universes ORDER BY name"
            ).fetchall()
            return [LoreUniverse(**dict(r)) for r in rows]

    def get_universe(self, universe_id: str) -> Optional[LoreUniverse]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM universes WHERE id = ?", (universe_id,)
            ).fetchone()
            return LoreUniverse(**dict(row)) if row else None

    def create_universe(self, data: LoreUniverseCreate) -> LoreUniverse:
        now = _now_iso()
        uid = _new_id()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO universes (id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (uid, data.name, data.description, now, now),
            )
        return LoreUniverse(
            id=uid,
            name=data.name,
            description=data.description,
            created_at=now,
            updated_at=now,
        )

    def update_universe(
        self, universe_id: str, data: LoreUniverseUpdate
    ) -> Optional[LoreUniverse]:
        now = _now_iso()
        updates = []
        params = []
        if data.name is not None:
            updates.append("name = ?")
            params.append(data.name)
        if data.description is not None:
            updates.append("description = ?")
            params.append(data.description)
        if not updates:
            return self.get_universe(universe_id)
        updates.append("updated_at = ?")
        params.append(now)
        params.append(universe_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE universes SET {', '.join(updates)} WHERE id = ?",
                params,
            )
        return self.get_universe(universe_id)

    def delete_universe(self, universe_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM universes WHERE id = ?", (universe_id,)
            )
            return cursor.rowcount > 0

    # ── Characters ────────────────────────────────────────────────────────

    def get_characters(self, universe_id: str) -> list[LoreCharacter]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM characters WHERE universe_id = ? ORDER BY name",
                (universe_id,),
            ).fetchall()
            characters = []
            for r in rows:
                char = LoreCharacter(**dict(r))
                char.personality_axes = self._get_axes(conn, char.id)
                characters.append(char)
            return characters

    def get_character(self, character_id: str) -> Optional[LoreCharacter]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM characters WHERE id = ?", (character_id,)
            ).fetchone()
            if not row:
                return None
            char = LoreCharacter(**dict(row))
            char.personality_axes = self._get_axes(conn, char.id)
            return char

    def get_character_by_name(
        self, universe_id: str, name: str
    ) -> Optional[LoreCharacter]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM characters WHERE universe_id = ? AND name = ? COLLATE NOCASE",
                (universe_id, name),
            ).fetchone()
            if not row:
                # Fuzzy fallback: LIKE match
                row = conn.execute(
                    "SELECT * FROM characters WHERE universe_id = ? AND name LIKE ? COLLATE NOCASE",
                    (universe_id, f"%{name}%"),
                ).fetchone()
            if not row:
                return None
            char = LoreCharacter(**dict(row))
            char.personality_axes = self._get_axes(conn, char.id)
            return char

    def create_character(
        self, universe_id: str, data: LoreCharacterCreate
    ) -> LoreCharacter:
        now = _now_iso()
        cid = _new_id()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO characters
                (id, universe_id, name, nickname, gender, age, species, role, faction, title,
                 appearance, personality_summary, speaking_style, backstory_text,
                 secrets, directives, free_notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cid, universe_id, data.name, data.nickname, data.gender, data.age,
                    data.species, data.role, data.faction, data.title,
                    data.appearance, data.personality_summary, data.speaking_style,
                    data.backstory_text, data.secrets, data.directives,
                    data.free_notes, now, now,
                ),
            )
            # Insert personality axes
            for axis in data.personality_axes:
                conn.execute(
                    "INSERT INTO personality_axes (id, character_id, axis_name, value, note) VALUES (?, ?, ?, ?, ?)",
                    (_new_id(), cid, axis.axis_name, axis.value, axis.note),
                )
        return self.get_character(cid)

    def update_character(
        self, character_id: str, data: LoreCharacterUpdate
    ) -> Optional[LoreCharacter]:
        now = _now_iso()
        fields = [
            "name", "nickname", "gender", "age", "species", "role", "faction", "title",
            "appearance", "personality_summary", "speaking_style",
            "backstory_text", "secrets", "directives", "free_notes",
        ]
        updates = []
        params = []
        for field in fields:
            value = getattr(data, field, None)
            if value is not None:
                updates.append(f"{field} = ?")
                params.append(value)
        if not updates:
            return self.get_character(character_id)
        updates.append("updated_at = ?")
        params.append(now)
        params.append(character_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE characters SET {', '.join(updates)} WHERE id = ?",
                params,
            )
        return self.get_character(character_id)

    def delete_character(self, character_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM characters WHERE id = ?", (character_id,)
            )
            return cursor.rowcount > 0

    def set_character_axes(
        self, character_id: str, axes: list[LorePersonalityAxisCreate]
    ) -> list[LorePersonalityAxis]:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM personality_axes WHERE character_id = ?",
                (character_id,),
            )
            for axis in axes:
                conn.execute(
                    "INSERT INTO personality_axes (id, character_id, axis_name, value, note) VALUES (?, ?, ?, ?, ?)",
                    (_new_id(), character_id, axis.axis_name, axis.value, axis.note),
                )
            return self._get_axes(conn, character_id)

    def _get_axes(
        self, conn: sqlite3.Connection, character_id: str
    ) -> list[LorePersonalityAxis]:
        rows = conn.execute(
            "SELECT * FROM personality_axes WHERE character_id = ? ORDER BY axis_name",
            (character_id,),
        ).fetchall()
        return [LorePersonalityAxis(**dict(r)) for r in rows]

    # ── Codex Entries ─────────────────────────────────────────────────────

    def get_codex_entries(
        self, universe_id: str, category: Optional[str] = None
    ) -> list[LoreCodexEntry]:
        with self._connect() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM codex_entries WHERE universe_id = ? AND category = ? ORDER BY title",
                    (universe_id, category),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM codex_entries WHERE universe_id = ? ORDER BY title",
                    (universe_id,),
                ).fetchall()
            return [LoreCodexEntry(**dict(r)) for r in rows]

    def get_codex_entry(self, entry_id: str) -> Optional[LoreCodexEntry]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM codex_entries WHERE id = ?", (entry_id,)
            ).fetchone()
            return LoreCodexEntry(**dict(row)) if row else None

    def get_codex_entry_by_title(
        self, universe_id: str, topic: str
    ) -> Optional[LoreCodexEntry]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM codex_entries WHERE universe_id = ? AND title = ? COLLATE NOCASE",
                (universe_id, topic),
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT * FROM codex_entries WHERE universe_id = ? AND title LIKE ? COLLATE NOCASE",
                    (universe_id, f"%{topic}%"),
                ).fetchone()
            return LoreCodexEntry(**dict(row)) if row else None

    def create_codex_entry(
        self, universe_id: str, data: LoreCodexEntryCreate
    ) -> LoreCodexEntry:
        now = _now_iso()
        eid = _new_id()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO codex_entries
                (id, universe_id, title, category, content, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (eid, universe_id, data.title, data.category, data.content, data.tags, now, now),
            )
        return LoreCodexEntry(
            id=eid,
            universe_id=universe_id,
            title=data.title,
            category=data.category,
            content=data.content,
            tags=data.tags,
            created_at=now,
            updated_at=now,
        )

    def update_codex_entry(
        self, entry_id: str, data: LoreCodexEntryUpdate
    ) -> Optional[LoreCodexEntry]:
        now = _now_iso()
        updates = []
        params = []
        for field in ["title", "category", "content", "tags"]:
            value = getattr(data, field, None)
            if value is not None:
                updates.append(f"{field} = ?")
                params.append(value)
        if not updates:
            return self.get_codex_entry(entry_id)
        updates.append("updated_at = ?")
        params.append(now)
        params.append(entry_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE codex_entries SET {', '.join(updates)} WHERE id = ?",
                params,
            )
        return self.get_codex_entry(entry_id)

    def delete_codex_entry(self, entry_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM codex_entries WHERE id = ?", (entry_id,)
            )
            return cursor.rowcount > 0

    # ── Relationships ─────────────────────────────────────────────────────

    def get_relationships(self, universe_id: str) -> list[LoreRelationship]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM relationships WHERE universe_id = ? ORDER BY created_at",
                (universe_id,),
            ).fetchall()
            return [self._enrich_relationship(conn, r) for r in rows]

    def get_entity_relationships(
        self, entity_type: str, entity_id: str
    ) -> list[LoreRelationship]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM relationships
                WHERE (source_type = ? AND source_id = ?)
                   OR (target_type = ? AND target_id = ?)
                ORDER BY created_at""",
                (entity_type, entity_id, entity_type, entity_id),
            ).fetchall()
            return [self._enrich_relationship(conn, r) for r in rows]

    def create_relationship(
        self, universe_id: str, data: LoreRelationshipCreate
    ) -> LoreRelationship:
        now = _now_iso()
        rid = _new_id()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO relationships
                (id, universe_id, source_type, source_id, target_type, target_id,
                 relationship_type, description, bidirectional, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    rid, universe_id, data.source_type, data.source_id,
                    data.target_type, data.target_id, data.relationship_type,
                    data.description, 1 if data.bidirectional else 0, now, now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM relationships WHERE id = ?", (rid,)
            ).fetchone()
            return self._enrich_relationship(conn, row)

    def update_relationship(
        self, relationship_id: str, data: LoreRelationshipUpdate
    ) -> Optional[LoreRelationship]:
        now = _now_iso()
        updates = []
        params = []
        if data.relationship_type is not None:
            updates.append("relationship_type = ?")
            params.append(data.relationship_type)
        if data.description is not None:
            updates.append("description = ?")
            params.append(data.description)
        if data.bidirectional is not None:
            updates.append("bidirectional = ?")
            params.append(1 if data.bidirectional else 0)
        if not updates:
            return self._get_relationship(relationship_id)
        updates.append("updated_at = ?")
        params.append(now)
        params.append(relationship_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE relationships SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            row = conn.execute(
                "SELECT * FROM relationships WHERE id = ?", (relationship_id,)
            ).fetchone()
            return self._enrich_relationship(conn, row) if row else None

    def delete_relationship(self, relationship_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM relationships WHERE id = ?", (relationship_id,)
            )
            return cursor.rowcount > 0

    def _get_relationship(
        self, relationship_id: str
    ) -> Optional[LoreRelationship]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM relationships WHERE id = ?", (relationship_id,)
            ).fetchone()
            return self._enrich_relationship(conn, row) if row else None

    def _enrich_relationship(
        self, conn: sqlite3.Connection, row: sqlite3.Row
    ) -> LoreRelationship:
        d = dict(row)
        d["bidirectional"] = bool(d["bidirectional"])
        # Resolve names for display
        d["source_name"] = self._resolve_entity_name(
            conn, d["source_type"], d["source_id"]
        )
        d["target_name"] = self._resolve_entity_name(
            conn, d["target_type"], d["target_id"]
        )
        return LoreRelationship(**d)

    def _resolve_entity_name(
        self, conn: sqlite3.Connection, entity_type: str, entity_id: str
    ) -> Optional[str]:
        if entity_type == "character":
            row = conn.execute(
                "SELECT name FROM characters WHERE id = ?", (entity_id,)
            ).fetchone()
        elif entity_type == "codex":
            row = conn.execute(
                "SELECT title AS name FROM codex_entries WHERE id = ?",
                (entity_id,),
            ).fetchone()
        else:
            return None
        return row["name"] if row else None

    # ── Backstory Generation ──────────────────────────────────────────────

    def generate_backstory(
        self, character_id: str, universe_id: str
    ) -> GenerateBackstoryResponse:
        char = self.get_character(character_id)
        if not char:
            return GenerateBackstoryResponse(
                backstory="Character not found.", token_estimate=0
            )

        parts = []

        # Identity section
        identity_parts = [f"You are {char.name}"]
        if char.nickname:
            identity_parts[0] += f', also known as "{char.nickname}"'
        if char.title:
            identity_parts[0] += f' — "{char.title}"'
        details = []
        if char.species:
            details.append(char.species)
        if char.role:
            details.append(char.role)
        if char.faction:
            details.append(f"of {char.faction}")
        if char.age:
            details.append(f"age: {char.age}")
        if char.gender:
            details.append(char.gender)
        if details:
            identity_parts[0] += f" ({', '.join(details)})"
        identity_parts[0] += "."
        if char.backstory_text:
            # Take first ~100 chars as a brief summary
            brief = char.backstory_text[:200]
            if len(char.backstory_text) > 200:
                brief += "..."
            identity_parts.append(brief)
        parts.append("## Identity\n" + "\n".join(identity_parts))

        # Personality section
        if char.personality_summary or char.personality_axes:
            personality_parts = []
            if char.personality_axes:
                axes_str = " | ".join(
                    f"{a.axis_name}: {a.value}/10" for a in char.personality_axes
                )
                personality_parts.append(axes_str)
            if char.personality_summary:
                personality_parts.append(char.personality_summary)
            parts.append("## Personality\n" + "\n".join(personality_parts))

        # Speaking Style
        if char.speaking_style:
            parts.append(f"## Speaking Style\n{char.speaking_style}")

        # Directives
        if char.directives:
            parts.append(f"## Directives\n{char.directives}")

        # Key Relationships (brief)
        rels = self.get_entity_relationships("character", character_id)
        if rels:
            rel_lines = []
            for rel in rels[:6]:  # Cap at 6 to keep it slim
                # Determine the "other" entity name
                if rel.source_id == character_id:
                    other_name = rel.target_name or "Unknown"
                else:
                    other_name = rel.source_name or "Unknown"
                rel_desc = rel.description or rel.relationship_type or "related"
                rel_lines.append(f"- {other_name}: {rel_desc}")
            parts.append(
                "## Key Relationships (brief)\n" + "\n".join(rel_lines)
            )

        # Lore tools instruction
        parts.append(
            "Use the lore tools (get_character, get_codex, search_lore) to retrieve detailed "
            "information about characters, events, and the universe when needed for roleplay."
        )

        backstory = "\n\n".join(parts)
        # Rough token estimate: ~4 chars per token
        token_estimate = len(backstory) // 4

        return GenerateBackstoryResponse(
            backstory=backstory, token_estimate=token_estimate
        )

    # ── LLM Tool Execution ────────────────────────────────────────────────

    def execute_tool(
        self,
        function_name: str,
        parameters: dict,
        universe_id: str,
        character_id: Optional[str] = None,
    ) -> str:
        if function_name == "get_character":
            return self._tool_get_character(
                universe_id, parameters.get("name", ""), character_id
            )
        elif function_name == "get_codex":
            return self._tool_get_codex(
                universe_id, parameters.get("topic", "")
            )
        elif function_name == "search_lore":
            return self._tool_search_lore(
                universe_id, parameters.get("query", "")
            )
        elif function_name == "list_lore":
            return self._tool_list_lore(universe_id)
        return "Unknown lore tool."

    def _tool_get_character(
        self, universe_id: str, name: str, requesting_character_id: Optional[str]
    ) -> str:
        char = self.get_character_by_name(universe_id, name)
        if not char:
            return f"No character named '{name}' found in this universe."

        parts = [f"# {char.name}"]
        if char.title:
            parts.append(f"**Title:** {char.title}")
        for field, label in [
            ("gender", "Gender"),
            ("age", "Age"),
            ("species", "Species"),
            ("role", "Role"),
            ("faction", "Faction"),
        ]:
            val = getattr(char, field)
            if val:
                parts.append(f"**{label}:** {val}")

        if char.appearance:
            parts.append(f"\n## Appearance\n{char.appearance}")
        if char.personality_summary:
            parts.append(f"\n## Personality\n{char.personality_summary}")
        if char.personality_axes:
            axes = ", ".join(
                f"{a.axis_name}: {a.value}/10" for a in char.personality_axes
            )
            parts.append(f"**Personality Axes:** {axes}")
        if char.speaking_style:
            parts.append(f"\n## Speaking Style\n{char.speaking_style}")
        if char.backstory_text:
            parts.append(f"\n## Backstory\n{char.backstory_text}")
        if char.directives:
            parts.append(f"\n## Directives\n{char.directives}")
        if char.free_notes:
            parts.append(f"\n## Notes\n{char.free_notes}")

        # Relationships from requesting character's perspective
        rels = self.get_entity_relationships("character", char.id)
        if rels:
            rel_lines = []
            for rel in rels:
                if rel.source_id == char.id:
                    other = rel.target_name or "Unknown"
                else:
                    other = rel.source_name or "Unknown"
                desc = rel.description or rel.relationship_type or ""
                rel_lines.append(f"- {other}: {desc}")
            parts.append("\n## Relationships\n" + "\n".join(rel_lines))

        return "\n".join(parts)

    def _tool_get_codex(self, universe_id: str, topic: str) -> str:
        entry = self.get_codex_entry_by_title(universe_id, topic)
        if not entry:
            return f"No codex entry matching '{topic}' found."

        parts = [f"# {entry.title}"]
        if entry.category:
            parts.append(f"**Category:** {entry.category}")
        if entry.tags:
            parts.append(f"**Tags:** {entry.tags}")
        parts.append(f"\n{entry.content}")
        return "\n".join(parts)

    def _tool_search_lore(self, universe_id: str, query: str) -> str:
        results = []
        with self._connect() as conn:
            # Search characters
            chars = conn.execute(
                """SELECT id, name, role, species FROM characters
                WHERE universe_id = ? AND (
                    name LIKE ? COLLATE NOCASE OR
                    role LIKE ? COLLATE NOCASE OR
                    faction LIKE ? COLLATE NOCASE OR
                    backstory_text LIKE ? COLLATE NOCASE OR
                    free_notes LIKE ? COLLATE NOCASE
                ) LIMIT 10""",
                (universe_id, f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%"),
            ).fetchall()
            for c in chars:
                snippet = f"{c['name']}"
                if c["role"]:
                    snippet += f" ({c['role']})"
                if c["species"]:
                    snippet += f" — {c['species']}"
                results.append(f"[Character] {snippet}")

            # Search codex entries
            entries = conn.execute(
                """SELECT id, title, category, content FROM codex_entries
                WHERE universe_id = ? AND (
                    title LIKE ? COLLATE NOCASE OR
                    content LIKE ? COLLATE NOCASE OR
                    tags LIKE ? COLLATE NOCASE
                ) LIMIT 10""",
                (universe_id, f"%{query}%", f"%{query}%", f"%{query}%"),
            ).fetchall()
            for e in entries:
                snippet = f"{e['title']}"
                if e["category"]:
                    snippet += f" [{e['category']}]"
                # Add content preview
                content = e["content"][:100]
                if len(e["content"]) > 100:
                    content += "..."
                snippet += f" — {content}"
                results.append(f"[Codex] {snippet}")

        if not results:
            return f"No lore matching '{query}' found."
        return f"Search results for '{query}':\n" + "\n".join(results)

    def _tool_list_lore(self, universe_id: str) -> str:
        parts = []
        with self._connect() as conn:
            chars = conn.execute(
                "SELECT name, role FROM characters WHERE universe_id = ? ORDER BY name",
                (universe_id,),
            ).fetchall()
            if chars:
                char_list = []
                for c in chars:
                    entry = c["name"]
                    if c["role"]:
                        entry += f" ({c['role']})"
                    char_list.append(f"- {entry}")
                parts.append("## Characters\n" + "\n".join(char_list))

            entries = conn.execute(
                "SELECT title, category FROM codex_entries WHERE universe_id = ? ORDER BY category, title",
                (universe_id,),
            ).fetchall()
            if entries:
                codex_list = []
                for e in entries:
                    entry = e["title"]
                    if e["category"]:
                        entry += f" [{e['category']}]"
                    codex_list.append(f"- {entry}")
                parts.append("## Codex Entries\n" + "\n".join(codex_list))

        if not parts:
            return "No lore entries found in this universe."
        return "\n\n".join(parts)

    # ── Migration ─────────────────────────────────────────────────────────

    async def migrate_backstory(
        self, request: MigrateBackstoryRequest, llm_call
    ) -> MigrateBackstoryResponse:
        """Extract structured data from a backstory using an LLM.

        Args:
            request: The migration request containing backstory text.
            llm_call: An async callable that takes a system prompt and user message
                     and returns the LLM's response text.
        """
        language_hint = ""
        if request.language:
            language_hint = f"The backstory is written in {request.language}. Extract data in the same language."

        prompt = MIGRATION_EXTRACTION_PROMPT.format(
            backstory_text=request.backstory_text,
            language_hint=language_hint,
        )

        try:
            response_text = await llm_call(
                system_prompt="You are a data extraction assistant. Respond with valid JSON only.",
                user_message=prompt,
            )

            # Strip markdown code fences if present
            text = response_text.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                # Remove first and last lines (code fences)
                lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                text = "\n".join(lines)

            data = json.loads(text)

            characters = [
                LoreCharacterCreate(**c) for c in data.get("characters", [])
            ]
            codex_entries = [
                LoreCodexEntryCreate(**e) for e in data.get("codex_entries", [])
            ]

            # Relationships need name→ID resolution which happens on the frontend
            # after the user confirms. For now, pass them through as-is.
            relationships = []
            for r in data.get("relationships", []):
                # Store source/target names temporarily — frontend resolves to IDs
                relationships.append(
                    LoreRelationshipCreate(
                        source_type=r.get("source_type", "character"),
                        source_id=r.get("source_name", ""),  # Name as placeholder
                        target_type=r.get("target_type", "character"),
                        target_id=r.get("target_name", ""),  # Name as placeholder
                        relationship_type=r.get("relationship_type"),
                        description=r.get("description"),
                        bidirectional=r.get("bidirectional", True),
                    )
                )

            warnings = data.get("warnings", [])

            return MigrateBackstoryResponse(
                characters=characters,
                codex_entries=codex_entries,
                relationships=relationships,
                warnings=warnings,
            )
        except json.JSONDecodeError as e:
            return MigrateBackstoryResponse(
                characters=[],
                codex_entries=[],
                relationships=[],
                warnings=[f"Failed to parse LLM response as JSON: {str(e)}"],
            )
        except Exception as e:
            return MigrateBackstoryResponse(
                characters=[],
                codex_entries=[],
                relationships=[],
                warnings=[f"Migration failed: {str(e)}"],
            )

    # ── Tool Schemas ──────────────────────────────────────────────────────

    def get_tool_schemas(self) -> list[dict]:
        return LORE_TOOL_SCHEMAS

    def get_tool_names(self) -> set[str]:
        return LORE_TOOL_NAMES
