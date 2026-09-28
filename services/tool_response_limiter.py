"""One cap for every tool response, however it was produced.

A skill, an MCP server or a command handler can hand back any amount of text.
The main model is what that text costs, and it has a window it cannot exceed,
so the cap comes from the main model (``ContextBudget.tool_cap``: 32,000 tokens,
or a quarter of a smaller model's window). Under the cap a response passes
through untouched. Over it the user gets a warning and the response is cut:

- **JSON** by whole list entries or whole keys, so what is left is still valid
  JSON in the skill's own order — a skill that sorts by price or relevance has
  already put the best entries first.
- **Text** at a line boundary.

A note at the end says how much is missing and tells the model to ask the tool
for less.

There is no summary. Measured 2026-09-28 on 62,000 tokens of real prose with
three facts in it: the support model's summary kept none of them and made the
pilot wait 25 seconds; a cut at 32,000 kept two
(evals/FINDINGS-context-budget-2026-09-28.md). On JSON a summary had already
lost to the cut on 2026-09-15.
"""

import json
from typing import Optional

from api.enums import LogSource, LogType
from services.printr import Printr
from services.token_utils import count_tokens, truncate_to_tokens

printr = Printr()

_ADVICE = (
    "If this comes from a custom skill or an MCP server, ask its author to "
    "return less data or to paginate."
)


class ToolResponseLimiter:
    """Brings an oversized tool response under ``cap`` tokens."""

    async def limit(
        self,
        response_text: str,
        cap: int,
        tool_name: str = "",
        wingman_name: str = "",
    ) -> str:
        """Return ``response_text`` unchanged when it fits, otherwise cut to
        ``cap`` tokens with a note on what is missing."""
        original_tokens = count_tokens(response_text)
        if original_tokens <= cap:
            return response_text

        tool_info = f" from '{tool_name}'" if tool_name else ""
        await printr.print_async(
            f"Tool response{tool_info} has ~{original_tokens:,} tokens, above the "
            f"limit of ~{cap:,}. {_ADVICE}",
            color=LogType.WARNING,
            source=LogSource.WINGMAN,
            source_name=wingman_name,
        )

        cut_text, kept, total, kind = structural_cut(response_text, cap)
        cut_tokens = count_tokens(cut_text)
        if kind == "text":
            what = f"the first ~{cut_tokens:,} tokens"
        else:
            what = f"{kept} of {total} {kind}"
        await printr.print_async(
            f"Tool response cut to {what} (~{original_tokens:,} → ~{cut_tokens:,} tokens).",
            color=LogType.WARNING,
            source=LogSource.WINGMAN,
            source_name=wingman_name,
        )
        return cut_text + _cut_note(original_tokens, cap, kept, total, kind)


# ── structural cut ───────────────────────────────────────────────


def _cut_note(original: int, cap: int, kept: int, total: int, kind: str) -> str:
    if kind == "text":
        shown = f"Only the beginning is shown"
    else:
        shown = f"Only {kept} of {total} {kind} are shown"
    return (
        f"\n\n[TOOL RESPONSE TRUNCATED: it had ~{original:,} tokens, the limit is "
        f"~{cap:,}. {shown}. Ask the tool for a narrower query or fewer results "
        f"to see the rest.]"
    )


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def is_structured(text: str) -> bool:
    """Whether ``text`` is a JSON list or object that ``structural_cut`` can
    trim entry by entry. A JSON string or number is text for our purposes."""
    stripped = text.lstrip()
    if not stripped or stripped[0] not in "[{":
        return False
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return False
    return isinstance(data, (list, dict)) and bool(data)


def structural_cut(text: str, max_tokens: int) -> tuple[str, int, int, str]:
    """Cut ``text`` to about ``max_tokens`` without breaking its structure.

    Returns ``(cut_text, kept, total, kind)`` where ``kind`` is ``"entries"``
    for a JSON list, ``"keys"`` for a JSON object and ``"text"`` for anything
    else. ``kept`` / ``total`` count the entries or keys; for text they are 0.

    The note the caller appends costs about 60 tokens, so the budget for the
    content is reduced by that much.
    """
    budget = max(1, max_tokens - 60)
    data = None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        pass

    if isinstance(data, list) and data:
        kept_items, total = _fit_list(data, budget)
        return _dumps(kept_items), len(kept_items), total, "entries"

    if isinstance(data, dict) and data:
        kept_dict, kept, total, inner = _fit_dict(data, budget)
        if inner is not None:
            return _dumps(kept_dict), inner[0], inner[1], "entries"
        return _dumps(kept_dict), kept, total, "keys"

    return _cut_text(text, budget), 0, 0, "text"


def _fit_list(items: list, budget: int) -> tuple[list, int]:
    """Keep leading entries while they fit. Always keeps at least one, cut
    down to size if it alone is too big."""
    kept = []
    used = 2  # the brackets
    for item in items:
        item_text = _dumps(item)
        item_tokens = count_tokens(item_text) + 1
        if kept and used + item_tokens > budget:
            break
        if not kept and item_tokens > budget:
            kept.append(_shrink(item, budget - 2))
            break
        kept.append(item)
        used += item_tokens
    return kept, len(items)


def _fit_dict(data: dict, budget: int) -> tuple[dict, int, int, Optional[tuple[int, int]]]:
    """Keep leading keys while they fit.

    A key whose value is a list that does not fit is kept with the list cut —
    the common shape ``{"keys": {...legend...}, "data": [...]}`` from skills
    that minify their output stays self-describing that way. ``inner`` reports
    the list's kept/total in that case so the note can say "entries" instead of
    "keys".
    """
    kept: dict = {}
    used = 2
    inner: Optional[tuple[int, int]] = None
    for key, value in data.items():
        entry_tokens = count_tokens(_dumps({key: value}))
        if used + entry_tokens <= budget:
            kept[key] = value
            used += entry_tokens
            continue
        if isinstance(value, list) and value:
            remaining = max(1, budget - used - count_tokens(_dumps(key)) - 2)
            kept_items, total = _fit_list(value, remaining)
            kept[key] = kept_items
            inner = (len(kept_items), total)
        elif not kept:
            kept[key] = _shrink(value, budget - count_tokens(_dumps(key)) - 3)
        break
    return kept, len(kept), len(data), inner


def _shrink(value, budget: int):
    """Last resort for a single oversized value: cut its text form."""
    if isinstance(value, str):
        return _cut_text(value, budget)
    return _cut_text(_dumps(value), budget)


def _cut_text(text: str, budget: int) -> str:
    cut = truncate_to_tokens(text, budget)
    if cut == text:
        return text
    newline = cut.rfind("\n")
    if newline > len(cut) * 0.8:
        cut = cut[:newline]
    return cut.rstrip()
