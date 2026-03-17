"""Lore Library Service — STUB

Pending rebuild with sqlite-vec + llama.cpp stack (Milestone 2).
All CRUD methods and LLM tool schemas have been removed.
Routes in wingman_core.py return 501 Not Implemented.

The class shell and key interfaces are preserved so that open_ai_wingman.py
imports don't break. All methods return empty/no-op results.
"""

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

LORE_TOOL_NAMES: set[str] = set()
LORE_TOOL_SCHEMAS: list[dict] = []

NOT_IMPLEMENTED_MSG = (
    "Lore Library is being rebuilt. This feature is temporarily unavailable."
)


class LoreLibraryService:
    """Stub — pending rebuild with sqlite-vec + llama.cpp stack."""

    def __init__(self):
        pass

    # ── Universes (stub) ──────────────────────────────────────────────

    def get_universes(self) -> list[LoreUniverse]:
        return []

    def get_universe(self, universe_id: str) -> Optional[LoreUniverse]:
        return None

    def create_universe(self, data: LoreUniverseCreate) -> LoreUniverse:
        raise NotImplementedError(NOT_IMPLEMENTED_MSG)

    def update_universe(
        self, universe_id: str, data: LoreUniverseUpdate
    ) -> Optional[LoreUniverse]:
        raise NotImplementedError(NOT_IMPLEMENTED_MSG)

    def delete_universe(self, universe_id: str) -> bool:
        raise NotImplementedError(NOT_IMPLEMENTED_MSG)

    # ── Characters (stub) ─────────────────────────────────────────────

    def get_characters(self, universe_id: str) -> list[LoreCharacter]:
        return []

    def get_character(self, character_id: str) -> Optional[LoreCharacter]:
        return None

    def get_character_by_name(
        self, universe_id: str, name: str
    ) -> Optional[LoreCharacter]:
        return None

    def create_character(
        self, universe_id: str, data: LoreCharacterCreate
    ) -> LoreCharacter:
        raise NotImplementedError(NOT_IMPLEMENTED_MSG)

    def update_character(
        self, character_id: str, data: LoreCharacterUpdate
    ) -> Optional[LoreCharacter]:
        raise NotImplementedError(NOT_IMPLEMENTED_MSG)

    def delete_character(self, character_id: str) -> bool:
        raise NotImplementedError(NOT_IMPLEMENTED_MSG)

    def set_character_axes(
        self, character_id: str, axes: list[LorePersonalityAxisCreate]
    ) -> list[LorePersonalityAxis]:
        raise NotImplementedError(NOT_IMPLEMENTED_MSG)

    # ── Codex Entries (stub) ──────────────────────────────────────────

    def get_codex_entries(
        self, universe_id: str, category: Optional[str] = None
    ) -> list[LoreCodexEntry]:
        return []

    def get_codex_entry(self, entry_id: str) -> Optional[LoreCodexEntry]:
        return None

    def get_codex_entry_by_title(
        self, universe_id: str, topic: str
    ) -> Optional[LoreCodexEntry]:
        return None

    def create_codex_entry(
        self, universe_id: str, data: LoreCodexEntryCreate
    ) -> LoreCodexEntry:
        raise NotImplementedError(NOT_IMPLEMENTED_MSG)

    def update_codex_entry(
        self, entry_id: str, data: LoreCodexEntryUpdate
    ) -> Optional[LoreCodexEntry]:
        raise NotImplementedError(NOT_IMPLEMENTED_MSG)

    def delete_codex_entry(self, entry_id: str) -> bool:
        raise NotImplementedError(NOT_IMPLEMENTED_MSG)

    # ── Relationships (stub) ──────────────────────────────────────────

    def get_relationships(self, universe_id: str) -> list[LoreRelationship]:
        return []

    def get_entity_relationships(
        self, entity_type: str, entity_id: str
    ) -> list[LoreRelationship]:
        return []

    def create_relationship(
        self, universe_id: str, data: LoreRelationshipCreate
    ) -> LoreRelationship:
        raise NotImplementedError(NOT_IMPLEMENTED_MSG)

    def update_relationship(
        self, relationship_id: str, data: LoreRelationshipUpdate
    ) -> Optional[LoreRelationship]:
        raise NotImplementedError(NOT_IMPLEMENTED_MSG)

    def delete_relationship(self, relationship_id: str) -> bool:
        raise NotImplementedError(NOT_IMPLEMENTED_MSG)

    # ── Backstory Generation (stub) ──────────────────────────────────

    def generate_backstory(
        self, character_id: str, universe_id: str
    ) -> GenerateBackstoryResponse:
        return GenerateBackstoryResponse(backstory="", token_estimate=0)

    # ── LLM Tool Interface (stub — no tools registered) ─────────────

    def execute_tool(
        self,
        function_name: str,
        parameters: dict,
        universe_id: str,
        character_id: Optional[str] = None,
    ) -> str:
        return NOT_IMPLEMENTED_MSG

    def get_tool_schemas(self) -> list[dict]:
        return LORE_TOOL_SCHEMAS

    def get_tool_names(self) -> set[str]:
        return LORE_TOOL_NAMES
