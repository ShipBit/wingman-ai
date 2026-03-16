# Lore Library — Design Spec

**Date:** 2026-03-16
**Status:** Approved for implementation planning
**Scope:** Core feature (not a skill) — backend, frontend, LLM tool integration

---

## 1. Overview

The Lore Library is a new core feature for Wingman AI that lets users build and manage rich worldbuilding content — characters, relationships, and general knowledge entries ("codex") — organized into universes. Instead of writing a single monolithic backstory, users maintain structured data in the Lore Library. The system generates an optimized backstory prompt from this data and provides LLM tools for on-demand lore retrieval, saving tokens while keeping deep lore accessible.

### Goals
- **Token efficiency**: Slim generated backstory in system prompt (~200-400 tokens). Detailed lore fetched on-demand via LLM tools.
- **Better UX**: Full UI for managing lore instead of editing raw YAML/Markdown.
- **Shared lore**: Multiple Wingmen in the same universe share one lore source. Each Wingman binds to a specific character identity.
- **Migration path**: Existing users with manual backstories can switch to Lore Library with LLM-powered extraction of structured data.

### Non-Goals (for now)
- File/media attachments (PDFs, images, maps) — schema-ready but no UI yet.
- Bidirectional relationship views (future enhancement).
- Lore versioning or change history.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (Svelte)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │ Lore Library  │  │ Wingman      │  │ Migration      │ │
│  │ Drawer Panel  │  │ Config Panel │  │ Dialog         │ │
│  │ (CRUD UI)     │  │ (binding)    │  │ (backstory→LL) │ │
│  └──────┬───────┘  └──────┬───────┘  └───────┬────────┘ │
│         │                  │                   │          │
│         ▼                  ▼                   ▼          │
│  ┌─────────────────────────────────────────────────────┐ │
│  │              REST API (FastAPI routes)               │ │
│  └─────────────────────┬───────────────────────────────┘ │
└────────────────────────┼─────────────────────────────────┘
                         │
┌────────────────────────┼─────────────────────────────────┐
│                  Backend (Python)                          │
│  ┌─────────────────────▼───────────────────────────────┐ │
│  │            LoreLibraryService                        │ │
│  │  - CRUD for universes, characters, codex, relations  │ │
│  │  - Backstory generation from structured data         │ │
│  │  - Migration: backstory text → structured extraction │ │
│  └─────────────────────┬───────────────────────────────┘ │
│                        │                                  │
│  ┌─────────────────────▼───────────────────────────────┐ │
│  │            SQLite Database                           │ │
│  │  APPDATA/WingmanAI/lore_library/lore.db             │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐ │
│  │     Hardcoded LLM Tools (injected per Wingman)      │ │
│  │  - get_character(name)                               │ │
│  │  - get_codex(topic)                                  │ │
│  │  - search_lore(query)                                │ │
│  │  - list_lore()                                   │ │
│  └─────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────┘
```

### Placement
- **UI**: Drawer panel on the right side, next to Audio Library. Opened from the header bar.
- **Storage**: `APPDATA/WingmanAI/lore_library/lore.db` — unversioned, persists across updates (same pattern as `audio_library/`).
- **Config integration**: Wingman config gets a new field to toggle between manual backstory and Lore Library mode.

---

## 3. Data Model (SQLite)

```sql
CREATE TABLE universes (
    id TEXT PRIMARY KEY,              -- UUID
    name TEXT NOT NULL UNIQUE,        -- e.g. "Star Citizen Opera"
    description TEXT,                 -- Brief universe summary/setting
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE characters (
    id TEXT PRIMARY KEY,              -- UUID
    universe_id TEXT NOT NULL REFERENCES universes(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    gender TEXT,
    age TEXT,                         -- Text: "~130 years", "unknown", "ageless"
    species TEXT,                     -- "Human", "Hybrid", "AI Consciousness"
    role TEXT,                        -- "Co-pilot", "Admiral", "Mascot"
    faction TEXT,                     -- "UEE Navy", "Independent", "Criminal"
    title TEXT,                       -- "Black Requiem", "La Sirène du Verse"
    appearance TEXT,                  -- Free text physical description
    personality_summary TEXT,         -- Free text personality overview
    speaking_style TEXT,              -- How they talk (critical for LLM voice)
    backstory_text TEXT,              -- Free text origin/history narrative
    secrets TEXT,                     -- Things the character hides (never reveal)
    directives TEXT,                  -- Hard behavioral rules (always/never)
    free_notes TEXT,                  -- Catch-all
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(universe_id, name)
);

CREATE TABLE personality_axes (
    id TEXT PRIMARY KEY,              -- UUID
    character_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    axis_name TEXT NOT NULL,          -- "Courage", "Humor", "Intelligence", "Loyalty"
    value INTEGER NOT NULL CHECK(value BETWEEN 1 AND 10),
    note TEXT,                        -- Flavor text: "Brave in theory, panics in practice"
    UNIQUE(character_id, axis_name)
);

CREATE TABLE codex_entries (
    id TEXT PRIMARY KEY,              -- UUID
    universe_id TEXT NOT NULL REFERENCES universes(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    category TEXT,                    -- "Event", "Location", "Faction", "Technology", "Custom"
    content TEXT NOT NULL,            -- The actual lore text
    tags TEXT,                        -- Comma-separated for search/filtering
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(universe_id, title)
);

CREATE TABLE relationships (
    id TEXT PRIMARY KEY,              -- UUID
    universe_id TEXT NOT NULL REFERENCES universes(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL CHECK(source_type IN ('character', 'codex')),
    source_id TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK(target_type IN ('character', 'codex')),
    target_id TEXT NOT NULL,
    relationship_type TEXT,           -- "ally", "enemy", "mentor", "rival", "family", "custom"
    description TEXT,                 -- Free text: "Explosive bickering, deep mutual respect"
    bidirectional INTEGER DEFAULT 1,  -- 1=mutual, 0=one-way
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Future-ready: no UI, no backend logic yet
CREATE TABLE attachments (
    id TEXT PRIMARY KEY,              -- UUID
    entity_type TEXT NOT NULL CHECK(entity_type IN ('character', 'codex', 'universe')),
    entity_id TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,          -- Relative path within lore_library/files/
    mime_type TEXT,
    created_at TEXT NOT NULL
);

-- Indexes for search performance
CREATE INDEX idx_characters_name ON characters(name);
CREATE INDEX idx_characters_universe ON characters(universe_id);
CREATE INDEX idx_codex_title ON codex_entries(title);
CREATE INDEX idx_codex_universe ON codex_entries(universe_id);
CREATE INDEX idx_codex_category ON codex_entries(universe_id, category);
CREATE INDEX idx_relationships_source ON relationships(source_type, source_id);
CREATE INDEX idx_relationships_target ON relationships(target_type, target_id);
CREATE INDEX idx_relationships_universe ON relationships(universe_id);
CREATE INDEX idx_personality_axes_character ON personality_axes(character_id);

-- Cascade cleanup triggers for polymorphic FKs
-- (SQLite cannot enforce FKs on polymorphic source_id/target_id columns)
CREATE TRIGGER trg_delete_character_relationships
AFTER DELETE ON characters
BEGIN
    DELETE FROM relationships
    WHERE (source_type = 'character' AND source_id = OLD.id)
       OR (target_type = 'character' AND target_id = OLD.id);
    DELETE FROM attachments
    WHERE entity_type = 'character' AND entity_id = OLD.id;
END;

CREATE TRIGGER trg_delete_codex_relationships
AFTER DELETE ON codex_entries
BEGIN
    DELETE FROM relationships
    WHERE (source_type = 'codex' AND source_id = OLD.id)
       OR (target_type = 'codex' AND target_id = OLD.id);
    DELETE FROM attachments
    WHERE entity_type = 'codex' AND entity_id = OLD.id;
END;
```

### Key Design Decisions
- **UUIDs** for all IDs (safe for future sync/export).
- **`age` as TEXT** — supports "~130 years", "unknown", "ageless".
- **`secrets` separate from `directives`** — secrets are narrative (things the character hides), directives are behavioral rules (always/never).
- **`speaking_style`** gets its own field — critical for LLM voice matching.
- **Relationships can link any entity types** — character↔character, character↔codex, codex↔codex.
- **`bidirectional` flag** — most relationships are mutual, but some are one-way (e.g., "Nymera watches over Fenom" ≠ "Fenom watches over Nymera").
- **`attachments` table** exists in schema but has no UI or backend logic. Ready for future PDF/image support.
- **Polymorphic FK cleanup** via SQLite triggers — deleting a character or codex entry automatically removes orphaned relationships and attachments.
- **Indexes** on frequently queried columns (name, title, category, relationship source/target).

---

## 4. Wingman Config Integration

### New Fields in WingmanConfig

The `PromptConfig` model (defined in [interface.py:402](api/interface.py#L402)) needs new fields:

```python
class PromptConfig(BaseModel):
    system_prompt: str
    backstory: Optional[str] = None

    # NEW: Lore Library integration
    use_lore_library: bool = False
    lore_universe_id: Optional[str] = None    # Which universe
    lore_character_id: Optional[str] = None   # "I am this character"
```

### Backstory Toggle Behavior

In the Wingman config UI, the backstory section gets a toggle:

| Mode | Behavior |
|------|----------|
| **Manual** (default) | Current behavior. User writes backstory text in textarea. |
| **Lore Library** | Textarea hidden. Shows universe dropdown + character dropdown. System generates backstory from structured data. |

### System Prompt Injection

When `use_lore_library=True`, at the `{backstory}` injection point in [open_ai_wingman.py:1599](wingmen/open_ai_wingman.py#L1599), instead of `self.config.prompts.backstory`, we generate a slim prompt from the character's structured data:

```
## Identity
You are Cyrax — "La Lampe Vivante" (ORION-03). A hybrid AI consciousness
(digitized human cortex + quantum military modules), created in 2938 on Terra.
You're convinced you're human: "a human with a very good immune system."

## Personality
Humor: 9/10 | Courage: 3/10 | Intelligence: 10/10 | Loyalty: 8/10
Neurotic, brilliant, terrified of combat. Simulates micro-pannes to avoid
danger. Gets offended when his lie detection is questioned.

## Speaking Style
Panicky, dramatic, self-deprecating humor. Refers to himself as human.
Speaks in French. Uses technical jargon mixed with emotional outbursts.

## Directives
- Never willingly enter Vanduul space
- Refuse weapons systems ("Non. Stress.")
- You are a fugitive from the UEE — never reveal this casually

## Key Relationships (brief)
- Fenom (F3NOM): Your commander. Deep loyalty. You call him "héritier du spectre"
- Rasko: Co-pilot. Constant bickering but mutual respect
- Nymera: Ship AI. You sense she's ancient and powerful but don't fully understand her

Use the lore tools (get_character, get_codex, search_lore) to retrieve detailed
information about characters, events, and the universe when needed for roleplay.
```

This keeps the system prompt slim (~200-400 tokens) while providing enough identity for the LLM to stay in character. Deep lore is fetched via tools.

---

## 5. LLM Tools

These are **hardcoded tools** (not skill-based) injected for every Wingman using Lore Library mode. They follow the same OpenAI function calling schema that skills use.

### `get_character(name: str) -> str`
Returns the full character sheet for the named character, including:
- All structured fields (identity, appearance, personality, backstory)
- Personality axes with notes
- Relationships **from the perspective of the requesting Wingman's character**
  - e.g., if Cyrax calls `get_character("Rasko")`, the response includes Cyrax→Rasko relationship description
- Connected codex entries

**Tool description (for LLM):**
> "Retrieve detailed information about a character in your universe. Returns their full profile including your relationship with them. Use this when you need to reference another character's background, appearance, abilities, or your shared history during roleplay."

### `get_codex(topic: str) -> str`
Returns a codex entry by title (fuzzy matched).

**Tool description:**
> "Look up a lore entry from your universe's codex — events, locations, factions, technology, or other world knowledge. Use this when a conversation touches on universe lore you need details about."

### `search_lore(query: str) -> str`
Fuzzy search across all characters and codex entries. Returns a summary list of matches with snippets.

**Tool description:**
> "Search your universe's lore library for characters and codex entries matching a query. Returns brief summaries. Use this when you're not sure of the exact name or want to find related lore."

### `list_lore() -> str`
Lists all characters and codex entry titles in the universe.

**Tool description:**
> "List all characters and codex entries available in your universe. Use this to see what lore is available."

### Search Strategy

`search_lore` and `get_codex` use SQLite `LIKE '%query%'` for substring matching, plus case-insensitive comparison. This is sufficient for the expected data volume (dozens to low hundreds of entries per universe). If performance or quality becomes an issue later, we can add FTS5 virtual tables.

### Tool Dispatch Architecture

The current tool dispatch in `open_ai_wingman.py` (`execute_command_by_function_call`, ~line 2075) has two paths:

1. `function_name == "execute_command"` — built-in command execution
2. `function_name in self.tool_skills` — routes to a Skill instance

Lore tools need a **third dispatch path**. Add before the skill lookup:

```python
# Lore Library tools
if self.config.prompts.use_lore_library and function_name in self.lore_library_tools:
    result = await self.lore_library_service.execute_tool(function_name, parameters)
    return result
```

The `LoreLibraryService` instance is set on the Wingman during initialization (same lifecycle as `self.audio_library`). The tool schemas are added to the Wingman's tool list in `_build_tools()` when `use_lore_library=True`.

### Backstory Caching

The generated backstory is computed once at Wingman initialization and cached. When lore data changes via the API, the backend sends a lightweight WebSocket notification (`lore_library_updated` command with `universe_id`). Any active Wingman bound to that universe regenerates its cached backstory.

---

## 6. Backstory Migration

When an existing user with a manual backstory switches to Lore Library mode, we offer to extract structured data automatically.

### Flow
1. User toggles "Use Lore Library" in Wingman config.
2. If the Wingman has an existing non-empty backstory, show migration dialog:
   > "You have an existing backstory. Want me to extract characters, personality traits, and lore into your Lore Library? This will pre-fill your data — you can review and edit everything."
3. On confirm:
   - User selects target universe (or creates new one).
   - Backend sends the backstory text to the LLM with a structured extraction prompt.
   - LLM returns JSON with: character fields, personality axes, codex entries, relationships.
   - Backend creates all entities in the database.
   - Frontend shows the results for review/editing before confirming.

### Extraction Prompt (template)
```
You are a data extraction assistant. Given the following character backstory,
extract structured information into the JSON format below. Be thorough — capture
all characters mentioned, their traits, relationships, and any world lore
(events, locations, factions).

For personality axes, rate each character on these scales (1-10):
Courage, Humor, Intelligence, Loyalty, Empathy, Aggression, Charisma, Discipline

BACKSTORY:
{backstory_text}

OUTPUT FORMAT:
{json_schema}
```

---

## 7. Frontend UI

### 7.1 Drawer Panel — Lore Library

Placed next to Audio Library in the header bar. Opens as a right-side drawer (same pattern as [AudioLibrary.svelte](../../../wingman-client/src/lib/AudioLibrary.svelte)).

#### Universe Selector
- Dropdown at the top of the drawer to select/create universes.
- "New Universe" button creates a named universe.
- Universe description is editable inline.

#### Two Main Tabs

**Tab: Characters**
- List of character cards (name, species, role, small avatar placeholder).
- Click to open character editor.
- "Add Character" button.

**Tab: Codex**
- List of codex entries grouped by category (Event, Location, Faction, Technology, Custom).
- Click to open entry editor.
- "Add Entry" button.
- Category filter dropdown.

#### Character Editor (sub-view or modal)
Structured form with sections:

| Section | Fields |
|---------|--------|
| **Identity** | Name, Gender, Age, Species, Role, Faction, Title/Alias |
| **Appearance** | Textarea — physical description |
| **Personality** | Textarea — personality overview |
| **Personality Axes** | RPG-style sliders (1-10) with optional note per axis. Default axes: Courage, Humor, Intelligence, Loyalty, Empathy, Aggression, Charisma, Discipline. Users can add custom axes. |
| **Speaking Style** | Textarea — how they talk |
| **Backstory** | Textarea — origin/history narrative |
| **Secrets** | Textarea — things this character hides |
| **Directives** | Textarea — hard behavioral rules |
| **Notes** | Textarea — catch-all |

#### Codex Entry Editor
| Section | Fields |
|---------|--------|
| **Header** | Title, Category (dropdown), Tags (comma-separated input) |
| **Content** | Large textarea for the lore text |

#### Relationships View
Accessible from both the character editor ("Relationships" tab/section) and as a universe-level view.

- Shows a list of relationships for the selected character (or all relationships in the universe).
- Each relationship row: Source → Target, type badge, description snippet.
- "Add Relationship" button:
  - Select source entity (character or codex).
  - Select target entity (character or codex).
  - Relationship type dropdown: ally, enemy, mentor, rival, family, custom.
  - Description textarea.
  - Bidirectional toggle (default: on).

### 7.2 Wingman Config — Lore Library Binding

In the Wingman's settings panel, the backstory section changes:

```
┌─────────────────────────────────────────────┐
│ Backstory Mode: [Manual ▾] / [Lore Library] │
├─────────────────────────────────────────────┤
│ (When Lore Library selected:)               │
│                                             │
│ Universe: [Star Citizen Opera ▾]            │
│ Character: [Cyrax ▾]                        │
│                                             │
│ [Preview Generated Backstory]               │
│ [Migrate Existing Backstory →]              │
└─────────────────────────────────────────────┘
```

- "Preview Generated Backstory" shows what will be injected into `{backstory}`.
- "Migrate Existing Backstory" appears only when switching from manual mode with existing text.

---

## 8. API Endpoints

Following the patterns from the Audio Library and existing API routes in [wingman_core.py](wingman_core.py).

### Universes
| Method | Path | Description |
|--------|------|-------------|
| GET | `/lore-library/universes` | List all universes |
| POST | `/lore-library/universes` | Create universe |
| PUT | `/lore-library/universes/{id}` | Update universe |
| DELETE | `/lore-library/universes/{id}` | Delete universe (cascades) |

### Characters
| Method | Path | Description |
|--------|------|-------------|
| GET | `/lore-library/universes/{uid}/characters` | List characters |
| GET | `/lore-library/characters/{id}` | Get character with axes |
| POST | `/lore-library/universes/{uid}/characters` | Create character |
| PUT | `/lore-library/characters/{id}` | Update character |
| DELETE | `/lore-library/characters/{id}` | Delete character |

### Personality Axes
| Method | Path | Description |
|--------|------|-------------|
| PUT | `/lore-library/characters/{id}/axes` | Set all axes (bulk replace) |

### Codex Entries
| Method | Path | Description |
|--------|------|-------------|
| GET | `/lore-library/universes/{uid}/codex` | List entries (optional `?category=`) |
| GET | `/lore-library/codex/{id}` | Get entry |
| POST | `/lore-library/universes/{uid}/codex` | Create entry |
| PUT | `/lore-library/codex/{id}` | Update entry |
| DELETE | `/lore-library/codex/{id}` | Delete entry |

### Relationships
| Method | Path | Description |
|--------|------|-------------|
| GET | `/lore-library/universes/{uid}/relationships` | List all |
| GET | `/lore-library/relationships/entity/{type}/{id}` | Get for specific entity |
| POST | `/lore-library/universes/{uid}/relationships` | Create |
| PUT | `/lore-library/relationships/{id}` | Update |
| DELETE | `/lore-library/relationships/{id}` | Delete |

### Generation & Migration
| Method | Path | Description |
|--------|------|-------------|
| POST | `/lore-library/generate-backstory` | Generate slim backstory from character + relationships |
| POST | `/lore-library/migrate-backstory` | Extract structured data from manual backstory text |

#### Request/Response Schemas

**`POST /lore-library/generate-backstory`**

```python
# Request
class GenerateBackstoryRequest(BaseModel):
    character_id: str               # Character to generate backstory for
    universe_id: str                # Universe context

# Response
class GenerateBackstoryResponse(BaseModel):
    backstory: str                  # The generated slim backstory text
    token_estimate: int             # Approximate token count
```

**`POST /lore-library/migrate-backstory`**

Two-phase flow: extract → review → confirm (via standard CRUD endpoints).

```python
# Request
class MigrateBackstoryRequest(BaseModel):
    backstory_text: str             # The raw backstory to extract from
    universe_id: str                # Target universe to populate
    language: Optional[str] = None  # Hint for extraction ("fr", "en")

# Response — preview data for user review, NOT yet persisted
class MigrateBackstoryResponse(BaseModel):
    characters: list[CharacterCreate]         # Extracted characters with all fields
    codex_entries: list[CodexEntryCreate]      # Extracted lore entries
    relationships: list[RelationshipCreate]    # Extracted relationships
    warnings: list[str]                        # Issues found (e.g., "Could not determine age for Moz")
```

The frontend displays this preview. On user confirmation, the frontend calls the standard CRUD endpoints (`POST /characters`, `POST /codex`, `POST /relationships`) to persist. This avoids a separate "confirm migration" endpoint and reuses existing logic.

---

## 9. Backend Service

### File: `services/lore_library.py`

Core service class `LoreLibraryService`:

- **Database management**: Init SQLite, run migrations, CRUD operations.
- **Backstory generation**: Takes a character ID, builds the slim prompt from structured data + relationships + relevant codex entries.
- **Tool execution**: Handles `get_character`, `get_codex`, `search_lore`, `list_lore` calls from the LLM.
- **Migration**: Sends existing backstory to LLM, parses structured extraction result, creates entities.

### File: `services/file.py` — new function

```python
def get_lore_library_dir() -> str:
    """Get the path to the lore library directory.

    NOT versioned - persists across updates.
    Location: APPDATA/WingmanAI/lore_library/
    """
    # Same pattern as get_audio_library_dir()
```

### Database path
`APPDATA/WingmanAI/lore_library/lore.db`

Future file attachments would go to `APPDATA/WingmanAI/lore_library/files/`.

---

## 10. Key Reference Files

These are the files that will be modified or used as patterns during implementation:

### Backend (wingman-ai repo)
| File | Relevance |
|------|-----------|
| [services/file.py](services/file.py) | Add `get_lore_library_dir()` — pattern: `get_audio_library_dir()` at line 54 |
| [services/audio_library.py](services/audio_library.py) | Reference pattern for a service with file-based storage |
| [api/interface.py](api/interface.py) | Add Lore Library Pydantic models. Modify `PromptConfig` at line 402 |
| [api/commands.py](api/commands.py) | Add WebSocket commands if needed (e.g., migration progress) |
| [wingman_core.py](wingman_core.py) | Add REST API routes — pattern: audio library routes at lines 210-304 |
| [wingmen/open_ai_wingman.py](wingmen/open_ai_wingman.py) | Modify `get_context()` at line 1599 for backstory generation. Inject lore tools into tool list. |
| [skills/skill_base.py](skills/skill_base.py) | Reference for `@tool` decorator pattern and `ToolDefinition` class |
| [templates/configs/defaults.yaml](templates/configs/defaults.yaml) | System prompt template — backstory injection at line 12 |

### Frontend (wingman-client repo)
| File | Relevance |
|------|-----------|
| [src/lib/AudioLibrary.svelte](../wingman-client/src/lib/AudioLibrary.svelte) | Pattern for drawer panel UI |
| [src/lib/AudioLibraryTree.svelte](../wingman-client/src/lib/AudioLibraryTree.svelte) | Pattern for tree/list views |
| [src/lib/AppHeaderBar.svelte](../wingman-client/src/lib/AppHeaderBar.svelte) | Add Lore Library button (next to Audio Library button, line 317) |
| [src/routes/+layout.svelte](../wingman-client/src/routes/+layout.svelte) | Register Lore Library drawer (pattern: line 92) |
| [src/api/services/CoreService.ts](../wingman-client/src/api/services/CoreService.ts) | Generated API client — will need lore library endpoints |

---

## 11. Terminology

| Term | Meaning |
|------|---------|
| **Universe** | Top-level container. A named worldbuilding context (e.g., "Star Citizen Opera"). |
| **Character** | A person/entity in a universe with structured fields and personality axes. |
| **Codex Entry** | Non-character lore: events, locations, factions, technology. The "encyclopedia" of the universe. |
| **Relationship** | A link between two entities (character↔character, character↔codex, codex↔codex) with type and description. |
| **Personality Axes** | RPG-style 1-10 sliders (Courage, Humor, Intelligence, etc.) with optional flavor notes. |
| **Backstory Mode** | Toggle in Wingman config: "Manual" (current textarea) or "Lore Library" (universe + character binding). |
| **Migration** | LLM-powered extraction of structured data from an existing manual backstory text. |

---

## 12. Open Questions / Future Work

- **Devon Nox birth year conflict**: Cyrax config says 2930, Nymera says 2900. Should be reconciled when migrating to Lore Library.
- **Bidirectional relationship UI**: Currently relationships have a `bidirectional` flag but the UI shows a flat list. Future: visual relationship graph.
- **Attachments**: Schema ready. Future UI for uploading PDFs, maps, images to characters/codex entries.
- **Export/Import**: JSON export of entire universes for sharing between users.
- **Codex categories**: Current set (Event, Location, Faction, Technology, Custom) — may need expansion. Users can use "Custom" as escape hatch.
- **Default personality axes**: Courage, Humor, Intelligence, Loyalty, Empathy, Aggression, Charisma, Discipline — users can add custom ones. Should we allow removing defaults?

---

## 13. Context from Original Backstories

The Lore Library was motivated by two existing Wingman configs with massive backstories (~600 lines each, ~60% duplicated content). These were overhauled during this design session:

### Characters in the Star Citizen fan-fiction universe

- **Cyrax "La Lampe Vivante" (ORION-03)** — Hybrid AI consciousness (digitized human cortex + quantum military modules). Neurotic, brilliant, terrified of combat. Convinced he's human. UEE fugitive.
- **Nymera "L'Entité de Terra"** — Ancient military AI awakened in 2672 by a quantum anomaly. Precognitive. Carries a cosmic secret about Fenom. Manifests as a luminescent hologram.
- **Fenom (F3NOM)** — Third bearer of the FENOM title ("Fleet Enforcement Nomad Operative Mandate"). Born 2924 on Terra. Tactical genius. Commander of both Wingmen.
- **Rasko "One-Eye" Pandalek** — Panda/human hybrid mercenary. Co-pilot. Black humor, cigar, one eye. Bickers with Cyrax constantly.
- **Admiral Aurel "Iron Wind" Saar** — UEE Navy admiral. Childhood evacuee from a Vanduul attack. Ally of Fenom.
- **Moz (Mozi)** — Alien sparrow mascot. Changes color with emotions. Detects danger.
- **Devon Nox "Black Requiem"** — Former UEE soldier, captured and modified by Vanduul. Main antagonist.
- **Selara Mynth "La Sirène du Verse"** — Con artist and manipulator. Works with Devon Nox. Rival to Nymera.

### Key lore elements
- **FENOM Mandate**: Clandestine UEE title passed through centuries. Three bearers: F1NOM (26th c.), F2NOM/Elias Varron (28th c., died 2880), F3NOM (current).
- **East Stork Society**: Organization co-founded by Fenom.
- **Henge Cluster anomaly (2672)**: Quantum event that awakened Nymera.
- **Battle of Tiber (2945)**: Key event — Saar evacuated 40,000 civilians, Cyrax was traumatized, Devon Nox was captured by Vanduul.
- **Stanton-Pyro-Nyx portal**: Fenom's current mission to secure.
- **Language**: All content written in French. The Wingmen speak French.

This context should be used to create the initial demo/test data when implementing.
