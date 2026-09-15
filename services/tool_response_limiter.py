"""One cap for every tool response, however it was produced.

A skill, an MCP server or a command handler can hand back any amount of text.
The main model is what that text costs — on Wingman Pro it costs us, on an own
key it costs the user — so the cap is about the main model, not about the
support model. Under the cap a response passes through untouched. Over it the
user gets a warning in the client and the response is brought under the cap in
one of two ways:

1. **Cut structurally** when the response is JSON. Whole list entries or whole
   keys are kept, so what is left is still valid JSON, and the order is the
   skill's own — a skill that sorts by price or relevance has already put the
   best entries first. Measured 2026-09-15 on gemini-2.5-flash-lite: asked to
   condense a 170-row price table, the model copied the first rows until the
   budget ran out, ten seconds and 0.3 cent for what a cut does for free.
2. **Summarised** by the support model when the response is text (a page, a
   log, a document) and a support model is configured, allowed, and fits it in
   one call. The summary is capped at ``SUMMARY_MAX_TOKENS``; a paid call that
   hands back something not much smaller than a plain cut would be money for
   nothing, so anything at or above ``SUMMARY_REJECT_RATIO`` of the cap is
   thrown away and the text is cut at a line boundary instead.

A note at the end says how much is missing and tells the model to ask the tool
for less. The local 2B model with its 4096-token window never fits a text that
is over an 8000-token cap, so local users get the cut there too. That is
intended: chunking 50k tokens through a 2B model takes minutes and drops facts
along the way.
"""

import asyncio
import json
from typing import Optional

from api.enums import LogSource, LogType
from services.printr import Printr
from services.token_utils import count_tokens, truncate_to_tokens

printr = Printr()

SUMMARY_MAX_TOKENS = 4000
"""Output ceiling for the summary: half the Pro cap. A page or a search result
keeps its useful middle at this size; at 2,000 too much of it went missing.
The extra 2,000 tokens cost about 0.1 cent per call on the support model and
the same again on a mini-class chat model, once — the trimming after the turn
brings every response down to 500 and then 25 tokens regardless."""

SUMMARY_REJECT_RATIO = 0.75
"""A summary at or above this share of the cap is thrown away: it would not
have saved enough over a plain cut to justify the call."""

SUMMARY_PROMPT_NAME = "support-tool-response"

_ADVICE = (
    "If this comes from a custom skill or an MCP server, ask its author to "
    "return less data or to paginate."
)


class ToolResponseLimiter:
    """Brings an oversized tool response under ``cap`` tokens.

    Stateless apart from the printr; one instance per wingman is fine.
    """

    async def limit(
        self,
        response_text: str,
        cap: int,
        tool_name: str = "",
        wingman_name: str = "",
        local_ai_service=None,
    ) -> str:
        """Return ``response_text`` unchanged when it fits, otherwise a version
        under ``cap`` tokens.

        ``local_ai_service`` is the support model to summarise with. Pass
        ``None`` when summarisation is switched off or no support model is
        ready; the response is then cut instead.
        """
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

        if local_ai_service is not None and not is_structured(response_text):
            summary = await self._summarize(
                response_text, original_tokens, cap, local_ai_service, wingman_name
            )
            if summary is not None:
                return summary

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

    # ── summarisation ────────────────────────────────────────────

    async def _summarize(
        self,
        response_text: str,
        original_tokens: int,
        cap: int,
        local_ai_service,
        wingman_name: str,
    ) -> Optional[str]:
        """One support call, or ``None`` when that is not possible or the
        result is not worth keeping."""
        from services.file import get_prompt
        from services.skill_local_ai import SamplingPreset

        system_prompt = get_prompt(SUMMARY_PROMPT_NAME)
        budget = local_ai_service.get_token_budget(system_prompt)
        reject_at = int(cap * SUMMARY_REJECT_RATIO)
        max_summary = min(SUMMARY_MAX_TOKENS, max(1, reject_at - 1))

        if original_tokens > budget.max_input_tokens:
            # Local model with a small window: a chunked pass through a 2B model
            # is slow and lossy, the cut is the better deal. Cloud: 128k in one
            # call is the ceiling we are willing to pay for, cut down to it.
            if budget.max_input_tokens < cap:
                await printr.print_async(
                    f"Support model window (~{budget.max_input_tokens:,} tokens) is "
                    f"too small to summarize this response in one call. Cutting instead.",
                    color=LogType.LOCALMODEL,
                    source=LogSource.WINGMAN,
                    source_name=wingman_name,
                )
                return None
            response_text, _, _, _ = structural_cut(response_text, budget.max_input_tokens)

        await printr.print_async(
            f"Summarizing the response with the support model "
            f"(at most ~{max_summary:,} tokens)...",
            color=LogType.LOCALMODEL,
            source=LogSource.WINGMAN,
            source_name=wingman_name,
        )

        user_prompt = (
            f"TOKEN BUDGET FOR YOUR ANSWER: {max_summary}\n\n"
            f"DATA:\n{response_text}\n\n---\n"
            f"Condense the data above into at most {max_summary} tokens."
        )
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: local_ai_service.support(
                    text=user_prompt,
                    system_prompt=system_prompt,
                    preset=SamplingPreset.PRECISE,
                    max_output_tokens=max_summary,
                ),
            )
        except Exception as error:
            printr.print(
                f"[ToolResponseLimiter] support call failed: {error}",
                color=LogType.WARNING,
                server_only=True,
            )
            return None

        summary = (result.text or "").strip() if result else ""
        if not summary:
            await printr.print_async(
                "Support model returned nothing. Cutting instead.",
                color=LogType.LOCALMODEL,
                source=LogSource.WINGMAN,
                source_name=wingman_name,
            )
            return None

        summary_tokens = count_tokens(summary)
        if summary_tokens >= reject_at:
            await printr.print_async(
                f"Summary is not small enough (~{summary_tokens:,} tokens). Cutting instead.",
                color=LogType.LOCALMODEL,
                source=LogSource.WINGMAN,
                source_name=wingman_name,
            )
            return None

        await printr.print_async(
            f"Tool response summarized (~{original_tokens:,} → ~{summary_tokens:,} tokens).",
            color=LogType.LOCALMODEL,
            source=LogSource.WINGMAN,
            source_name=wingman_name,
        )
        return (
            f"[SUMMARY OF A TOOL RESPONSE — the original had ~{original_tokens:,} "
            f"tokens and was condensed by a support model. Ask for a narrower "
            f"query if a detail is missing.]\n{summary}"
        )


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
