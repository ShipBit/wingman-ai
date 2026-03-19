# Accurate Token Usage Reporting

## Problem

The conversation token counter (`~72 tok` in ConfigBar) is inaccurate:

1. **Backstory truncation warning counted**: The "Backstory will be truncated" log message uses `source=LogSource.WINGMAN`, so the client counts it as a conversation message.
2. **System prompt not counted**: The compiled system prompt (backstory + skills + conversation_summary + ttsprompt + user_context) and tools schema are sent to the LLM but never reported to the client.
3. **Heuristic estimation**: Client uses `tokenx` (~96% accuracy) instead of actual provider-reported counts.

## Solution

Use the actual `usage` data from the `ChatCompletion` response object, which all providers already return. Send it to the client via a new WebSocket command.

## Backend Changes

### New WebSocket command (`api/commands.py`)

```python
class ConversationTokenUsageCommand(WebSocketCommandModel):
    command: Literal["conversation_token_usage"] = "conversation_token_usage"
    wingman_name: str
    prompt_tokens: int        # tokens sent to LLM (system prompt + history + tools)
    completion_tokens: int    # tokens in LLM response
    is_local: bool = False    # True for LOCAL_LLM provider (free, not billed)
```

### Emission point (`wingmen/open_ai_wingman.py`)

In `_process_completion()`, after extracting the response message:

- Read `completion.usage.prompt_tokens` and `completion.usage.completion_tokens`
- Guard against `completion.usage` being `None` (skip silently)
- Determine `is_local` from `self.config.features.conversation_provider == ConversationProvider.LOCAL_LLM`
- Send `ConversationTokenUsageCommand` via the websocket connection

**Token semantics for tool-call loops**: When a turn involves multiple LLM calls (tool-call follow-ups), each call's `prompt_tokens` already includes the full context (system prompt + history + tool results), so the **last call's `prompt_tokens`** is the most meaningful number — it represents the actual context size. For `completion_tokens`, we **sum across all calls** in the turn since each call generates different output. The accumulator state lives as local variables in `_get_response_for_transcript()`, passed to `_process_completion()` or accumulated after each call.

### Backstory warning fix (`wingmen/open_ai_wingman.py`)

- Change `source=LogSource.WINGMAN` to `source=LogSource.SYSTEM` on the backstory truncation warning
- Add the wingman name to the message text so the user knows which wingman's backstory is too long

## Client Changes

### New store (`services/stores.ts`)

`wingmanTokenUsage: Writable<Record<string, {prompt: number, completion: number}>>`

Stores per-wingman token usage from the most recent LLM turn.

### WebSocket handler (`routes/(app)/+layout.svelte`)

Register handler for `conversation_token_usage` command (matching the pattern used by `conversation_condensation` and `core_state_changed`). Update the `wingmanTokenUsage` store for the named wingman. Ignore messages where `is_local === true` for the main display.

### ConfigBar display (`ConfigBar.svelte`)

- Replace the `conversationTokens` derived store (client-side heuristic sum) with a read from `wingmanTokenUsage` for the focused wingman
- Display `prompt_tokens` as the main number
- Remove the `~` prefix (these are exact, not estimates)
- Update tooltip using i18n key `m.conversation_tokens_tooltip()` — update value in all 4 locales to reflect the new meaning

**Behavioral change**: No token count displays until the first LLM call completes (replacing the always-available heuristic). This is expected — the number now represents real API-reported usage, not an estimate.

### Per-message token display (`TerminalMessage.svelte`)

No change. Individual `X tok` labels on messages remain as client-side estimates for relative sizing. The `countTokens` helper and `tokenx` import stay for this use.

### Reset (`ConfigBar.svelte` — `clearMessageHistory`)

Clear the focused wingman's entry in `wingmanTokenUsage` alongside the existing clearing of `terminalMessages` and `wingmanSummaries`.

## Edge Cases

- **No usage data**: If `completion.usage` is `None`, don't send the command. Client shows nothing.
- **Multiple wingmen**: Each tracked independently by `wingman_name`.
- **Tool-call loops**: Last call's `prompt_tokens`, summed `completion_tokens`. See emission point section.
- **Condensation**: Next LLM call naturally reports fewer `prompt_tokens`. No special handling.
- **Local LLM**: Marked `is_local=True`. Client ignores for main display. Data available for future separate display.

## Provider Compatibility

All providers return OpenAI-compatible `ChatCompletion` with `usage`:
- OpenAI, Azure, Mistral, Groq, Cerebras, OpenRouter, Perplexity, XAI: OpenAI SDK
- Google: OpenAI compatibility layer
- WingmanPro: Deserializes to `ChatCompletion` explicitly
- Local LLM: llama.cpp OpenAI-compatible endpoint

## Files to Modify

| File | Change |
|------|--------|
| `api/commands.py` | Add `ConversationTokenUsageCommand` |
| `wingmen/open_ai_wingman.py` | Extract and send usage in `_process_completion()`, accumulate in `_get_response_for_transcript()`, fix backstory warning |
| `wingman-client/src/services/stores.ts` | Add `wingmanTokenUsage` store |
| `wingman-client/src/services/websocketService.ts` | Add new command to `CommandUnion` type |
| `wingman-client/src/routes/(app)/+layout.svelte` | Register WS handler for `conversation_token_usage` |
| `wingman-client/src/lib/ConfigBar.svelte` | Replace heuristic with real token data, update reset logic |
| `wingman-client/src/lib/i18n/*/index.ts` | Update `conversation_tokens_tooltip` in all 4 locales |
