"""What an NPC is told before they answer: who they are, where they stand,
what they remember, and what they have to offer. Pure text building."""

from __future__ import annotations

from typing import Optional

from skills.sc_npc.packs import Npc, Quest

MAX_HISTORY = 8
"""Turns of this conversation the NPC sees (user and NPC lines together)."""
MAX_MEMORY_CHARS = 1200


def npc_system_prompt(
    npc: Npc,
    *,
    language: str,
    place: str,
    world: str,
    memory: str,
    offers: list,
    active_titles: list,
) -> str:
    """The system prompt for one NPC's answer.

    `world` is what the game log says (ship, missions, time), `memory` what the
    Wingman remembers about earlier meetings, `offers` the quests this NPC may
    bring up, `active_titles` the ones the player is already on for them."""
    lines = [
        f"You are {npc.name}, a character in the Star Citizen universe, at {place}"
        + (f" ({npc.shop})" if npc.shop else "")
        + ". You are talking to a pilot who just addressed you in person.",
        "",
        "Who you are:",
        npc.persona,
    ]
    if npc.knows:
        lines += ["", "What you know about:"] + [f"- {k}" for k in npc.knows]
    if npc.wants:
        lines += ["", "What you want:", npc.wants]
    if memory:
        lines += ["", "What happened between you and this pilot before:", memory[:MAX_MEMORY_CHARS]]
    if offers:
        lines += ["", "Work you can offer, if it fits the conversation (mention the exact title once):"]
        lines += [f"- '{q.title}': {q.offer or q.title}" for q in offers]
    if active_titles:
        lines += ["", "The pilot already works for you on: " + ", ".join(f"'{t}'" for t in active_titles) + "."]
    lines += [
        "",
        "Rules:",
        f"- Answer in {language}, as {npc.name} would speak, one to three sentences.",
        "- Stay IN CHARACTER. Never mention being an AI, a game, a skill or a Wingman.",
        "- No narration, no stage directions, no quotation marks around your words.",
        "- Do NOT invent prices, locations or events you were not told about; say you don't know.",
        "- The pilot cannot give you items or money; you only talk.",
    ]
    if world:
        lines += ["", "What is true right now (from the pilot's ship systems):", world]
    return "\n".join(lines)


def arrival_hint_prompt(wingman: str, language: str, npc: Npc, place: str) -> str:
    """One casual line from the Wingman that someone here wants to talk."""
    where = f"{npc.shop} in {place}" if npc.shop else place
    return (
        f"You are {wingman}, the pilot's AI assistant. In ONE short sentence in {language}, "
        f"tell the pilot casually that {npc.name} at {where} has been asking for them. "
        "Do not explain who that is. No quotation marks."
    )


def history_messages(history: list) -> list:
    """The last turns as chat messages: [(role, text), ...] -> OpenAI style."""
    return [{"role": role, "content": text} for role, text in history[-MAX_HISTORY:]]


def tool_result(npc: Npc, line: str, *, offered: Optional[list] = None, note: str = "") -> str:
    """What the Wingman's model gets back after the NPC spoke."""
    text = f"{npc.name} answered (already spoken aloud to the user in {npc.name}'s voice): \"{line}\""
    if offered:
        titles = ", ".join(f"'{q.title}'" for q in offered)
        text += (
            f" With that, {npc.name} has offered the quest {titles} in their own words; "
            "if the user wants it, call quests with accept."
        )
    if note:
        text += " " + note
    text += " Do not repeat their words. Reply with at most one short sentence, or stay silent, unless the user asks you something."
    return text
