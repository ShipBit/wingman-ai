"""The info panel tools every Wingman with `hud.info` on has.

The info panel is shared by all Wingmen, so there is deliberately no tool that
clears it: one Wingman must not wipe what another put there. Any Wingman can
read it, including what other Wingmen and skills put there.
"""

import time
from typing import TYPE_CHECKING, Any, Optional

from hud_server.constants import GROUP_INFO

if TYPE_CHECKING:
    from wingmen.wingman import Wingman

HUD_TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "hud_set_info",
            "description": (
                "Show information on the user's HUD info panel, or replace the panel "
                "with the same title. For things worth keeping in view: lists, tables, "
                "status, reminders. Markdown."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short panel title."},
                    "markdown": {"type": "string", "description": "The content."},
                    "duration_seconds": {
                        "type": "number",
                        "description": "Remove it after this many seconds. Leave out to keep it.",
                    },
                },
                "required": ["title", "markdown"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hud_read_info",
            "description": (
                "Read what is on the user's HUD info panel right now, also what other "
                "Wingmen and skills put there. Without a title: every panel."
            ),
            "parameters": {
                "type": "object",
                "properties": {"title": {"type": "string", "description": "Read only this panel."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hud_remove_info",
            "description": "Remove a panel from the HUD info panel when the user asks.",
            "parameters": {
                "type": "object",
                "properties": {"title": {"type": "string", "description": "The panel's title."}},
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hud_show_progress",
            "description": (
                "Show a progress bar on the HUD info panel, or a countdown when "
                "timer_seconds is given. The same title updates it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "current": {"type": "number"},
                    "maximum": {"type": "number", "description": "Default 100."},
                    "timer_seconds": {"type": "number", "description": "Countdown length instead of a bar."},
                    "description": {"type": "string", "description": "Optional markdown below it."},
                },
                "required": ["title"],
            },
        },
    },
]

HUD_TOOL_NAMES = frozenset(t["function"]["name"] for t in HUD_TOOLS)

# A read returns at most this much, so a big table cannot flood the conversation
PANEL_CHARS = 2400
READ_CHARS = 8000

# Panel titles are spoken, so the same panel comes back worded differently.
# High threshold: removing the wrong panel is worse than "which one?".
SYSTEM_ONE_MIN_CONFIDENCE = 0.7


async def resolve_title(system_one, asked: str, titles: list[str]) -> Optional[str]:
    """The panel the user means, or None if there is no telling.

    The exact title wins; System One only runs when that fails, and only if
    the user has it.
    """
    if asked in titles:
        return asked
    lowered = {t.lower(): t for t in titles}
    if asked.lower() in lowered:
        return lowered[asked.lower()]
    if not system_one or not system_one.available or not titles:
        return None

    criteria = {name: None for name in titles}
    criteria["none_of_these"] = "no panel on the list is the one meant"
    answers = await system_one.decide(
        state={"asked_for": asked, "panels_on_the_hud": titles},
        questions={
            "panel": system_one.choice(
                "Which panel on the HUD is being asked about? The title was "
                "spoken, so it may be shortened or worded differently from "
                "how it was created.",
                criteria,
            )
        },
    )
    picked = answers.choice("panel", min_confidence=SYSTEM_ONE_MIN_CONFIDENCE)
    return None if picked in (None, "none_of_these") else picked


def _seconds(value: float) -> str:
    value = max(0, int(value + 0.5))
    minutes, seconds = divmod(value, 60)
    return f"{minutes} min {seconds} s" if minutes else f"{seconds} s"


def describe_panel(item: dict, now: float, reader: Optional[str] = None) -> str:
    """One panel as the model reads it: title, its state, who added it, its content."""
    notes = []
    if item.get("is_timer"):
        left = item.get("timer_start", now) + item.get("timer_duration", 0) - now
        notes.append(f"countdown: {_seconds(left)} of {_seconds(item.get('timer_duration', 0))} left")
    elif item.get("is_progress"):
        notes.append(f"progress: {item.get('progress_current', 0):g} of {item.get('progress_maximum', 100):g}")
    elif item.get("duration"):
        notes.append(f"goes in {_seconds(item['added_at'] + item['duration'] - now)}")
    added_by = item.get("added_by")
    if added_by:
        notes.append("added by you" if added_by == reader else f"added by {added_by}")
    head = f"### {item['title']}" + (f" ({', '.join(notes)})" if notes else "")
    text = (item.get("description") or "").strip()
    if len(text) > PANEL_CHARS:
        text = text[:PANEL_CHARS] + " … (cut)"
    return f"{head}\n{text}" if text else head


def describe_panels(items: list[dict], now: float, reader: Optional[str] = None) -> str:
    if not items:
        return "The HUD info panel is empty."
    parts = [f"{len(items)} panel(s) on the HUD info panel, oldest first:"]
    used = len(parts[0])
    for index, item in enumerate(items):
        part = describe_panel(item, now, reader)
        if used + len(part) > READ_CHARS:
            rest = ", ".join(f"'{i['title']}'" for i in items[index:])
            parts.append(f"Not shown for length, read them by title: {rest}.")
            break
        parts.append(part)
        used += len(part)
    return "\n\n".join(parts)


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _someone_elses(items: list[dict], title: str, me: str) -> Optional[str]:
    """Who added the panel with this title, if it was not `me`."""
    owner = next((i.get("added_by") for i in items if i["title"] == title), None)
    return owner if owner and owner != me else None


async def run_hud_tool(wingman: "Wingman", name: str, args: dict[str, Any]) -> str:
    from services.hud_service import HudService

    hud = HudService()
    if not hud.available:
        return "The HUD is not running."
    me = getattr(wingman, "name", None)
    title = str(args.get("title") or "").strip()

    if name == "hud_read_info":
        items = hud.info_items()
        if title:
            from wingmen.facade import SkillSystemOne

            found = await resolve_title(
                SkillSystemOne(getattr(wingman, "jev", None)), title, [i["title"] for i in items]
            )
            if found is None:
                return f"No panel '{title}' on the HUD. " + describe_panels(items, time.time(), me)
            items = [i for i in items if i["title"] == found]
        return describe_panels(items, time.time(), me)

    if not title:
        return "No title given."

    if name == "hud_set_info":
        duration = _number(args.get("duration_seconds"))
        other = _someone_elses(hud.info_items(), title, me)
        hud.add_info(
            GROUP_INFO, title, str(args.get("markdown") or ""),
            duration=duration if duration and duration > 0 else None, added_by=me,
        )
        replaced = f" It replaced the panel {other} had added." if other else ""
        return f"'{title}' is on the HUD.{replaced}"

    if name == "hud_remove_info":
        from wingmen.facade import SkillSystemOne

        items = hud.info_items()
        titles = [i["title"] for i in items]
        found = await resolve_title(SkillSystemOne(getattr(wingman, "jev", None)), title, titles)
        if found is None:
            listed = ", ".join(f"'{t}'" for t in titles) or "none"
            return f"No panel '{title}' on the HUD. Panels: {listed}."
        other = _someone_elses(items, found, me)
        hud.remove_info(GROUP_INFO, found)
        return f"Removed '{found}' from the HUD." + (f" {other} had added it." if other else "")

    if name == "hud_show_progress":
        description = str(args.get("description") or "")
        seconds = _number(args.get("timer_seconds"))
        if seconds and seconds > 0:
            hud.show_timer(GROUP_INFO, title, seconds, text=description, added_by=me)
            return f"Countdown '{title}' runs for {seconds:g} seconds."
        current = _number(args.get("current"))
        if current is None:
            return "Give current (and maximum), or timer_seconds."
        maximum = _number(args.get("maximum")) or 100
        hud.show_progress(GROUP_INFO, title, current, maximum, text=description, added_by=me)
        return f"'{title}' is at {current:g} of {maximum:g}."

    return "Unknown HUD tool."
