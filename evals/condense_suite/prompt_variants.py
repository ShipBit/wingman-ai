"""Candidate condensation prompts, including the one currently shipped.

``shipped`` is read from ``prompts/condense-conversation.md`` so the baseline is
always whatever production actually uses. The rest are candidates; the harness
scores them side by side and the winner replaces the file.

What the shipped prompt gets wrong, measured 2026-09-14 on a real ATC session:
44 messages became a 956-token summary and saved 53 tokens. It says "extract ALL
facts", "every topic gets at least one bullet", "do NOT merge" and "include tool
results" — that is the specification for a transcript, not for a summary. The
candidates below all attack that from different angles, because a 2B model and a
frontier model do not fail the same way.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

SHIPPED = (ROOT / "prompts/condense-conversation.md").read_text().strip()


# Direct opposite of the shipped prompt: compress hard, name a budget, and say
# out loud which categories are worthless. Written for a strong model.
TERSE_RULES = """\
You compress a conversation into a short fact sheet for an AI assistant to read later.

Write bullet points starting with *. Nothing else: no headline, no intro, no closing remark.

Keep:
- Who the user is: name, how they want to be addressed, preferences, dislikes
- What they own, fly, use, or are saving for
- Decisions made and plans agreed
- Answers and results the user will refer back to

Drop:
- Anything the assistant could not do or did not have access to
- Tool and server names, activation notices, raw tool payloads
- Individual commands that were executed and acknowledged
- Greetings, filler, and restating the question

Merge related facts into one bullet. Aim for roughly one tenth the length of the
conversation. If nothing is worth keeping, output nothing at all.\
"""


# Same intent, but every rule phrased as a short imperative and the examples
# inline. Small models follow examples better than they follow prose.
EXAMPLE_LED = """\
Compress the conversation into a short fact sheet. Output only bullet points.

Format: one fact per line, starting with "* ". No headline. No intro. No closing line.

Good:
* Pilot is Marcus, dislikes being called commander
* Flies a Drake Cutlass Black, sold his Aurora for it
* Saving for an Idris with his friend Tobias, about 12 million so far
* Refuses mining work

Bad (never do this):
* The user asked about cargo status
* The assistant said it does not have access to the manifest
* The wingman_starhead server was activated
* The available tools are mcp_get_ships, mcp_get_shops

Keep names, ships, orgs, preferences, plans and results. Drop commands that were
just executed, tool names, and anything the assistant could not do. Merge related
facts. Be short — about one tenth of the conversation. Output nothing if there is
nothing worth keeping.\
"""


# The shortest prompt that still names the two failure modes. Tests whether the
# long rule lists are doing any work at all.
MINIMAL = """\
Summarise the conversation as a short bullet list of facts worth remembering.

* one fact per line, no headline, no intro, no closing remark
* keep names, possessions, preferences, decisions and results
* drop tool names, server activations, executed commands, and anything the
  assistant could not do
* merge related facts, keep it to about a tenth of the original length\
"""


# Explicit budget in tokens rather than a ratio. A ratio needs the model to
# estimate the input length; a hard ceiling does not.
BUDGETED = """\
You write the running memory of an AI copilot.

Produce at most 15 bullet points. Fewer is better. Each line starts with "* ".
No headline, no introduction, no closing remark, no markdown besides the bullets.

Each bullet is one thing the assistant should still know in an hour:
who the user is, what they own or want, what was decided, what was found out.

Never write a bullet about:
- a command that was carried out and acknowledged
- something the assistant could not access or did not know
- which tool or server was used, or what it was called
- the conversation itself

Merge facts that belong together. If there is nothing worth remembering, write
nothing.\
"""


VARIANTS = {
    "shipped": SHIPPED,
    "terse_rules": TERSE_RULES,
    "example_led": EXAMPLE_LED,
    "minimal": MINIMAL,
    "budgeted": BUDGETED,
}


def user_prompt(conversation_text: str, existing_summary: str = "") -> str:
    """The user half, shaped like the one ``conversation_condenser`` builds."""
    prefix = ""
    if existing_summary:
        prefix = (
            "EXISTING SUMMARY (incorporate and update — do not repeat verbatim):\n"
            + existing_summary
            + "\n\n"
        )
    return f"{prefix}CONVERSATION TO SUMMARISE:\n{conversation_text}"
