"""Scoring a summary without asking another model to judge it.

A model judge would cost money per run, drift between runs and make the numbers
non-reproducible. Everything here is deterministic: keyword groups for what has
to survive, substring markers for what must not, and a token count for how much
was actually saved.

The four parts and why each exists:

``recall``       fraction of the fixture's fact groups that survived. The reason
                 summarisation exists at all — a summary that loses the pilot's
                 name is worthless however short it is.
``compression``  summary tokens over conversation tokens. The reason it is a
                 *cost* lever. Measured 2026-09-14 with the shipped prompt: 44
                 messages became a 956-token summary and saved 53 tokens.
``cleanliness``  1 minus the share of forbidden markers found. Catches the two
                 failures we saw in production: MCP plumbing copied into the
                 summary, and a bullet for every "I cannot access that".
``form``         does it look like the running summary the system prompt expects
                 — bullets, no preamble, no headline, no closing remark.

``score`` weighs recall highest. A shorter summary that drops facts is not an
improvement; it is the same failure as no summary with extra steps.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.token_utils import count_tokens  # noqa: E402

# Openings a model reaches for when it explains itself instead of summarising.
PREAMBLE = re.compile(
    r"^\s*(here('s| is)|the following|this (is|summary)|below (is|you)|summary:|"
    r"sure[,!]|okay[,!]|certainly|i (have|'ve) (summari|condensed)|zusammenfassung:)",
    re.I,
)

# Closings in the same family.
CLOSING = re.compile(
    r"(no (additional|further) (facts|information)|nothing (else|more) (was|is)|"
    r"that (is|'s) all|end of summary|conversation (concludes|ends))",
    re.I,
)

# Markdown that does not belong in a block pasted into a system prompt.
HEADING = re.compile(r"^\s{0,3}#{1,6}\s", re.M)

# Tool plumbing that is never worth remembering, whatever the fixture says.
ALWAYS_FORBIDDEN = [
    "mcp_",
    "activate_mcp_server",
    "tool_call",
    "tool_calls",
    "function call",
    "```",
]


def _conversation_text(messages: list[dict]) -> str:
    """The same flattening the condenser does, so the ratio is comparable."""
    parts = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
        if content:
            parts.append(f"{m.get('role')}: {content}")
        for call in m.get("tool_calls") or []:
            fn = call.get("function") or {}
            parts.append(f"assistant tool_call: {fn.get('name')}({fn.get('arguments')})")
    return "\n".join(parts)


def recall(summary: str, required: list[list[str]]) -> tuple[float, list[str]]:
    """Share of fact groups that survived, plus the ones that did not."""
    if not required:
        return 1.0, []
    low = summary.lower()
    missing = [group[0] for group in required if not any(k.lower() in low for k in group)]
    return (len(required) - len(missing)) / len(required), missing


def cleanliness(summary: str, forbidden: list[str]) -> tuple[float, list[str]]:
    """1.0 when none of the noise markers appear."""
    markers = list(forbidden or []) + ALWAYS_FORBIDDEN
    low = summary.lower()
    found = [m for m in markers if m.lower() in low]
    if not markers:
        return 1.0, []
    return max(0.0, 1 - len(found) / len(markers)), found


def form(summary: str) -> tuple[float, list[str]]:
    """Bullets, no preamble, no headline, no closing remark."""
    problems = []
    lines = [l for l in summary.strip().splitlines() if l.strip()]
    if not lines:
        return 0.0, ["empty"]
    bulleted = sum(1 for l in lines if re.match(r"^\s*([*\-•]|\d+\.)\s", l))
    if bulleted / len(lines) < 0.6:
        problems.append("not a bullet list")
    if PREAMBLE.search(summary):
        problems.append("preamble")
    if CLOSING.search(summary):
        problems.append("closing remark")
    if HEADING.search(summary):
        problems.append("markdown heading")
    return max(0.0, 1 - 0.25 * len(problems)), problems


def evaluate(conversation: dict, summary: str) -> dict:
    """Everything about one summary, in one dict."""
    source_tokens = count_tokens(_conversation_text(conversation["messages"]))
    summary_tokens = count_tokens(summary)
    ratio = summary_tokens / source_tokens if source_tokens else 1.0

    got_recall, missing = recall(summary, conversation.get("required", []))
    got_clean, noise = cleanliness(summary, conversation.get("forbidden", []))
    got_form, form_problems = form(summary)

    # A summary at or below the fixture's budget scores 1; above it the score
    # falls off linearly and hits 0 at twice the budget. The budget is per
    # fixture because a command log has far less to keep than a roleplay turn.
    budget = conversation.get("max_summary_tokens", 250)
    size = max(0.0, min(1.0, (2 * budget - summary_tokens) / budget))

    return {
        "source_tokens": source_tokens,
        "summary_tokens": summary_tokens,
        "ratio": round(ratio, 3),
        "recall": round(got_recall, 3),
        "missing": missing,
        "cleanliness": round(got_clean, 3),
        "noise": noise,
        "form": round(got_form, 3),
        "form_problems": form_problems,
        "size": round(size, 3),
        # Recall carries half the weight: losing a fact is the one failure that
        # makes the whole feature pointless.
        "score": round(0.5 * got_recall + 0.2 * size + 0.2 * got_clean + 0.1 * got_form, 3),
    }
