# Embedding Inspector Drawer

## Problem

Embeddings are used for tool response compression (RAG) and will be used for future features (user tags, persistent memory). There is no way to inspect what embeddings exist, how much memory they use, or what content they contain. Users need visibility into this system, especially as it grows.

## Solution

A right-side drawer (like Audio Library) accessible from ConfigBar. Uses Skeleton UI tabs to separate embedding source types. Shows stats, allows browsing chunk content, and supports managing (deleting) entries.

## Drawer UI

### Trigger

Button in ConfigBar (right side, near condense/copy/clear buttons). Uses `drawerStore.open({ id: 'embedding-inspector' })`. Visible when a wingman is focused OR in "View all" mode.

### Layout

```
+--------------------------------------------------+
| [icon] Embedding Inspector  [ATC]   [Refresh] [X] |
+--------------------------------------------------+
| Indices: 3 | Chunks: 47 | Embeddings: 47 | ~2.4MB |
| Model: nomic-embed-text                            |
+--------------------------------------------------+
| [Tool Responses (3)] | [Tags: soon] | [Memory: soon] |
+--------------------------------------------------+
| Entry card 1 (expandable)                         |
| Entry card 2 (collapsed)                          |
| Entry card 3 (collapsed)                          |
|                                                   |
| [Clear all tool response embeddings]              |
+--------------------------------------------------+
```

### Components

- **Header**: Title, wingman badge (or "All" in view-all mode), refresh button, close button
- **Summary stats bar**: Total indices, chunks, embeddings, estimated memory, embedding model name
- **Skeleton UI TabGroup**: One `Tab` per source type. Currently only "Tool Responses" is active; "Tags" and "Memory" show disabled/coming-soon state
- **Entry cards**: One per cached tool response. Shows:
  - Tool name (with globe icon for MCP tools)
  - `cache_id` (truncated)
  - Original token count, compressed token count, chunk count, embedding count
  - Relative timestamp
  - Delete button (variant-ghost-error)
  - Expandable detail section: summary text + numbered chunk previews (first 2 shown, rest behind "show more")
- **Clear all button**: At bottom, clears all entries for the current source tab + wingman
- **"View all" mode**: Same layout but each card has a colored wingman badge. Stats bar aggregates across all wingmen.

### Empty state

When no embeddings exist: centered message "No embeddings yet. Large tool responses will be automatically compressed and cached here."

## Backend API

### Models (`api/interface.py`)

```python
class EmbeddingEntryStats(BaseModel):
    cache_id: str
    tool_name: str
    original_token_count: int
    summary_token_count: int
    chunk_count: int
    embedding_count: int
    embedding_dimensions: int
    summary: str
    chunks: list[str]
    timestamp: float

class EmbeddingSourceStats(BaseModel):
    source_type: str  # "tool_response_cache"
    entries: list[EmbeddingEntryStats]

class WingmanEmbeddingStats(BaseModel):
    wingman_name: str
    sources: list[EmbeddingSourceStats]

class EmbeddingStatsResponse(BaseModel):
    wingmen: list[WingmanEmbeddingStats]
    total_chunks: int
    total_embeddings: int
    estimated_memory_bytes: int
    embedding_model: str | None
```

### Endpoints (`wingman_core.py`)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/embedding-stats` | Get stats for all wingmen (or `?wingman_name=X` for one) |
| `DELETE` | `/embedding-cache/{wingman_name}/{cache_id}` | Delete a single cached entry |
| `DELETE` | `/embedding-cache/{wingman_name}` | Clear all entries for a wingman |

### `ToolResponseCache.get_stats()` → `EmbeddingSourceStats`

New method on `ToolResponseCache` that returns stats for all cached entries. Iterates `self._cache`, builds `EmbeddingEntryStats` for each entry including chunk content and embedding dimensions.

### Memory estimation

`estimated_memory_bytes` = sum over all entries of:
- `len(chunks) * embedding_dimensions * 4` (float32 embeddings)
- `sum(len(chunk.encode()) for chunk in chunks)` (chunk text)

### Embedding model name

Retrieved from `local_ai_service.get_embed_model_name()` or similar. If local AI is not ready, return `None`.

## Backend Integration Points

### `ToolResponseCache` additions

- `get_stats() -> dict`: Returns source stats with all entry metadata
- `delete_entry(cache_id: str) -> bool`: Delete single entry, return success

### `WingmanCore` additions

- `get_embedding_stats(wingman_name: str | None) -> EmbeddingStatsResponse`: Iterates `tower.wingmen`, collects stats from each `OpenAiWingman._tool_response_cache`, aggregates totals
- `delete_embedding_cache_entry(wingman_name: str, cache_id: str)`: Finds wingman, calls `evict(cache_id)`
- `clear_embedding_cache(wingman_name: str)`: Finds wingman, calls `clear()`
- Three new routes registered via `self.router.add_api_route()`

### Accessing the cache from WingmanCore

`WingmanCore` gets wingmen via `self.tower.wingmen`. Each wingman is cast/checked for `OpenAiWingman` (which has `_tool_response_cache`). Base `Wingman` class does not have embeddings.

## Frontend Implementation

### New file: `src/lib/EmbeddingInspector.svelte`

Self-contained drawer component. Fetches data on mount via `CoreService.getEmbeddingStats()`. Uses:
- `getDrawerStore()` for close
- `focusedWingman` store to filter by wingman or show all
- `TabGroup` / `Tab` from Skeleton UI for source type tabs
- `ProgressRadial` for loading state

### Root layout addition (`src/routes/+layout.svelte`)

Add to the `<Drawer>` conditional block:
```svelte
{:else if $drawerStore.id === 'embedding-inspector'}
  <EmbeddingInspector />
```

### ConfigBar button (`src/lib/ConfigBar.svelte`)

New button in the right-side controls area (near condense/copy/clear). Uses `Database` icon from lucide-svelte.

### i18n keys (all 4 locales)

Keys prefixed with `embedding_inspector_*`:
- `embedding_inspector` — "Embedding Inspector"
- `embedding_inspector_indices` — "Indices"
- `embedding_inspector_chunks` — "Chunks"
- `embedding_inspector_embeddings` — "Embeddings"
- `embedding_inspector_memory` — "Est. Memory"
- `embedding_inspector_model` — "Model"
- `embedding_inspector_tool_responses` — "Tool Responses"
- `embedding_inspector_tags` — "Tags"
- `embedding_inspector_memory_tab` — "Memory"
- `embedding_inspector_coming_soon` — "coming soon"
- `embedding_inspector_original` — "Original"
- `embedding_inspector_compressed` — "Compressed"
- `embedding_inspector_summary` — "Summary"
- `embedding_inspector_delete` — "Delete"
- `embedding_inspector_clear_all` — "Clear all"
- `embedding_inspector_empty` — "No embeddings yet"
- `embedding_inspector_empty_hint` — "Large tool responses will be automatically compressed and cached here."
- `embedding_inspector_confirm_delete` — "Delete this cached embedding?"
- `embedding_inspector_confirm_clear` — "Clear all embeddings for this source?"
- `embedding_inspector_show_details` — "Show details"
- `embedding_inspector_hide_details` — "Hide details"

### API client

After backend endpoints are added, run `npm run generate:api` to auto-generate `CoreService.getEmbeddingStats()`, `CoreService.deleteEmbeddingCacheEntry()`, `CoreService.clearEmbeddingCache()` and the TypeScript models.

## Files to Create/Modify

| File | Action |
|------|--------|
| `services/tool_response_cache.py` | Add `get_stats()`, `delete_entry()` |
| `api/interface.py` | Add Pydantic models |
| `wingman_core.py` | Add 3 endpoints + handler methods |
| **Client** | |
| `src/lib/EmbeddingInspector.svelte` | Create drawer component |
| `src/routes/+layout.svelte` | Add drawer ID case + import |
| `src/lib/ConfigBar.svelte` | Add trigger button |
| `messages/en.json` | Add i18n keys |
| `messages/de.json` | Add i18n keys (German) |
| `messages/it.json` | Add i18n keys (Italian) |
| `messages/pt.json` | Add i18n keys (Portuguese) |

## Future Extensibility

When tags or persistent memory are added:
1. Each new source implements its own `get_stats()` returning `EmbeddingSourceStats`
2. Backend aggregates all sources into the `WingmanEmbeddingStats.sources` list
3. Frontend adds a new `Tab` with source-specific card rendering
4. The "coming soon" placeholder for that tab is replaced with real content
