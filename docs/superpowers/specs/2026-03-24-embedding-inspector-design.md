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
  - `cache_id` (truncated) — this is the `tool_call_id` internally, exposed as `cache_id` in the API
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

Note: `cache_id` in these models maps to `tool_call_id` internally in `CachedResponse`. The API uses `cache_id` for consistency with the LLM-facing retrieval tool schema.

```python
class EmbeddingEntryStats(BaseModel):
    cache_id: str              # maps to CachedResponse.tool_call_id
    tool_name: str
    original_token_count: int
    summary_token_count: int   # stored at creation time in CachedResponse
    chunk_count: int
    embedding_count: int
    embedding_dimensions: int
    summary: str
    chunks: list[str]          # truncated to first 200 chars each in response
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
| `GET` | `/embedding-inspector/stats` | Get stats for all wingmen (or `?wingman_name=X` for one). `response_model=EmbeddingStatsResponse` |
| `DELETE` | `/embedding-inspector/cache/{wingman_name}/{cache_id}` | Delete a single cached entry |
| `DELETE` | `/embedding-inspector/cache/{wingman_name}` | Clear all entries for a wingman |

### `ToolResponseCache.get_stats()` → `dict`

New method on `ToolResponseCache` that returns stats for all cached entries. Iterates `self._cache`, builds entry dicts for each entry. Chunk content is truncated to first 200 chars each. `summary_token_count` is stored in `CachedResponse` at creation time (already computed during `compress_and_cache`).

### Memory estimation

`estimated_memory_bytes` = sum over all entries of:
- `len(chunks) * embedding_dimensions * 4` (float32 embeddings)
- `sum(len(chunk.encode()) for chunk in chunks)` (chunk text)

### Embedding model name

Derived from the embed model path via `local_ai_service.provider.model_manager.get_embed_model_path()` — extract the filename/stem. If local AI is not ready or the path is not set, return `None`. A convenience method `get_embed_model_name()` should be added to `LocalAiService` to encapsulate this.

## Backend Integration Points

### `CachedResponse` additions

- Add `summary_token_count: int` field — computed and stored during `compress_and_cache()`

### `ToolResponseCache` additions

- `get_stats() -> dict`: Returns source stats with all entry metadata, chunk text truncated to 200 chars
- `delete_entry(cache_id: str) -> bool`: Returns `True` if the entry existed and was deleted, `False` if not found (wraps `dict.pop` with existence check)

### `OpenAiWingman` public API additions

To avoid breaking encapsulation by accessing `_tool_response_cache` from outside, add public methods:

- `get_embedding_stats() -> dict`: Delegates to `self._tool_response_cache.get_stats()`
- `delete_embedding_cache_entry(cache_id: str) -> bool`: Delegates to `self._tool_response_cache.delete_entry(cache_id)`
- `clear_embedding_cache()`: Delegates to `self._tool_response_cache.clear()`

### `WingmanCore` additions

- `get_embedding_stats(wingman_name: str | None) -> EmbeddingStatsResponse`: If `self.tower is None`, returns empty response. Otherwise iterates `tower.wingmen`, calls `wingman.get_embedding_stats()` on each `OpenAiWingman`, aggregates totals.
- `delete_embedding_cache_entry(wingman_name: str, cache_id: str)`: Finds wingman, calls public method
- `clear_embedding_cache(wingman_name: str)`: Finds wingman, calls public method
- Three new routes registered via `self.router.add_api_route()`

### Accessing wingmen from WingmanCore

`WingmanCore` gets wingmen via `self.tower.wingmen`. Uses `isinstance(wingman, OpenAiWingman)` to check for embedding support — base `Wingman` class does not have embeddings. Returns empty stats for non-OpenAiWingman instances.

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
- `embedding_inspector` — "Embedding Inspector" (also used as ConfigBar button tooltip)
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
| `services/tool_response_cache.py` | Add `get_stats()`, `delete_entry()`, `summary_token_count` to `CachedResponse` |
| `api/interface.py` | Add Pydantic models |
| `wingmen/open_ai_wingman.py` | Add public embedding stat/delete/clear methods |
| `wingman_core.py` | Add 3 endpoints + handler methods |
| `services/local_ai_service.py` | Add `get_embed_model_name()` convenience method |
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
