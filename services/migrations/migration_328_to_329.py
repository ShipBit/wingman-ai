"""Migration from version 3.2.8 to 3.2.9.

3.2.9 moves the changelog and the feature requests from Canny to our backend;
neither lives in the config.

The system prompt gets two changes from a real session log: the model ran
ship commands when the pilot only said where they were going or what they had
done, promised things it had no tool for, and gave spoken answers of a whole
minute. The changes are put into the user's own prompt rather than replacing
it, so an edited prompt keeps its edits.

The HUD skill is retired. Core draws the HUD itself now, laid out by HUD
profiles in the settings (services/hud_service.py, docs/hud.md):

- The first Wingman with the HUD skill on hands its skill settings to the
  default HUD profile. The HUD skill settings of every other Wingman are
  dropped. "First" is the HUD a user saw on start: switched-on Wingmen before
  switched-off ones, the config Core loaded on start before the others, then
  by name.
- Its chat and info panel get the pixel areas they had on the HUD screen, so
  the HUD looks the same on the first start. The screen is the one the HUD
  server is set to, measured the way the overlay measures it, Windows display
  scaling included. Anchors turn into an alignment: top_* top, *_center
  center (the screen's center counts as its left center), bottom_* bottom.
- Every Wingman gets the shared chat and the info panel switched on, and so
  does defaults.yaml for Wingmen made later.
- The skill's entry, its name in `discoverable_skills` and its tools in
  `disabled_skill_tools` go, and a custom copy in custom_skills moves to
  retired_skills next to it, where it no longer loads.
  Info panels the skill saved are not carried over; they lived in a folder of
  the old version.

The UEX skill was reworked. A Wingman's saved copy of its old default prompt
goes, so the new prompt applies; a prompt the user edited stays. Its removed
"Add UEX names as hotwords" setting goes too (Core warned about it on every
start).
"""

import hashlib
import os
import re
import shutil
from os import path

from services.config_manager import CONTEXT_FILE, SHIPPED_DEFAULT_CONFIG
from services.file import get_custom_skills_dir, get_users_dir
from services.migrations.base_migration import BaseMigration

OLD_LENGTH_RULE = "- Keep responses concise (1-3 sentences unless more detail is needed)"
NEW_LENGTH_RULE = (
    "- Keep responses short: 1-3 sentences, the answer first. "
    "Go longer only when the user asks for details"
)
ACTIONS_ANCHOR = "# YOUR CAPABILITIES"
ACTIONS_BLOCK = (
    "# ACTIONS\n"
    "- Run a command only when the user asks for that action now. A plan, a "
    "destination or something the user already did is not a request: \"next stop "
    "is Lorville\" or \"I fitted new guns\" means no command.\n"
    "- Say you did something only when a tool did it in this turn. Do not promise "
    "what you have no tool for.\n"
    "- Do not make up places, ship parts, prices or facts that neither the user "
    "nor a tool gave you.\n"
    "\n"
)


_UEX_MODULE = "skills.uexcorp.main"
# sha256 of the stripped prompts the UEX skill shipped with before 3.2.9: a saved copy of one of
# them is the old default, not the user's own text
_UEX_OLD_PROMPTS = {
    "c268bfd35e77a6e371f918392d0702178d65286703c10faa3d8ee0074247ea4e",
    "1598704bb2e60a327686c7a35808d67d8dce8d530ad95acf90ba720e2c1c4958",
}
_UEX_REMOVED_PROPERTIES = {"add_fasterwhisper_hotwords"}


def update_uex_skill(config: dict) -> list[str]:
    """Drops the old default prompt and removed settings from a Wingman's UEX skill entry.
    Returns what changed, for the log."""
    changes = []
    for entry in config.get("skills") or []:
        if not isinstance(entry, dict) or entry.get("module") != _UEX_MODULE:
            continue
        prompt = entry.get("prompt")
        if isinstance(prompt, str) and hashlib.sha256(prompt.strip().encode("utf-8")).hexdigest() in _UEX_OLD_PROMPTS:
            del entry["prompt"]
            changes.append("the UEX skill's old default prompt (the new one applies)")
        properties = entry.get("custom_properties")
        if isinstance(properties, list):
            kept = [p for p in properties if not (isinstance(p, dict) and p.get("id") in _UEX_REMOVED_PROPERTIES)]
            if len(kept) != len(properties):
                entry["custom_properties"] = kept
                changes.append("the UEX skill's removed hotword setting")
    return changes


def update_system_prompt(prompt: str) -> str:
    """The prompt with the 3.2.9 rules. A prompt that has them already, or
    has no place for them, comes back as it was."""
    if not isinstance(prompt, str):
        return prompt
    prompt = prompt.replace(OLD_LENGTH_RULE, NEW_LENGTH_RULE)
    if "# ACTIONS" not in prompt and ACTIONS_ANCHOR in prompt:
        prompt = prompt.replace(ACTIONS_ANCHOR, ACTIONS_BLOCK + ACTIONS_ANCHOR, 1)
    return prompt


_HUD_MODULE = "skills.hud.main"
_HUD_NAME = "HUD"
_HUD_TOOLS = {
    "hud_add_info", "hud_remove_info", "hud_list_info", "hud_clear_all", "hud_restore_info",
    "hud_show_progress", "hud_show_timer", "hud_update_progress", "hud_update_info",
    "hud_hide", "hud_show",
}

# The retired skill's defaults (skills/hud/default_config.yaml in 3.2.8)
SKILL_DEFAULTS = {
    "chat_layout_mode": "auto",
    "persistent_layout_mode": "auto",
    "chat_anchor": "top_left",
    "persistent_anchor": "top_left",
    "font_size": 16,
    "chat_x": 20,
    "persistent_x": 20,
    "chat_y": 20,
    "persistent_y": 20,
    "chat_priority": 20,
    "persistent_priority": 10,
    "hud_width": 400,
    "persistent_width": 400,
    "hud_max_height": 600,
    "persistent_max_height": 600,
    "font_family": "Segoe UI",
    "accent_color": "#00aaff",
    "bg_color": "#1e212b",
    "bg_opacity": 100,
    "text_color": "#f0f0f0",
    "border_radius": 12,
    "content_padding": 16,
    "max_display_time": 5,
    "audio_stop_delay": 1,
    "opacity": 85,
    "typewriter_effect": True,
    "restore_persistent_items": True,
    "show_chat_messages": True,
    "display_tool_names": False,
}

_ANCHORS = {
    "top_left", "top_center", "top_right", "left_center", "center", "right_center",
    "bottom_left", "bottom_center", "bottom_right",
}

# How the old overlay placed a window on start: every window registered with a
# margin of 20 and a spacing of 10 of its own. The settings' layout_margin and
# layout_spacing only applied once they were changed while the HUD ran.
OLD_MARGIN = 20
OLD_SPACING = 10
# It ranked an info panel 5 below its priority, so a message stacked first
OLD_INFO_PRIORITY_OFFSET = 5

FALLBACK_SCREEN = (1920, 1080)
MIN_WIDTH = 100
MIN_HEIGHT = 60

Screen = tuple[int, int]

_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def _int(value, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _hud_entry(wingman: dict) -> dict | None:
    for entry in wingman.get("skills") or []:
        if isinstance(entry, dict) and entry.get("module") == _HUD_MODULE:
            return entry
    return None


def uses_hud(wingman: dict) -> bool:
    return _HUD_NAME in (wingman.get("discoverable_skills") or [])


def skill_values(wingman: dict) -> tuple[dict, set[str]]:
    """The skill's settings the way the skill read them, and which of them the
    Wingman's config had. A saved skill config is not filled up with the
    skill's newer properties; the skill used its defaults for those. Without a
    saved config the skill ran on its default_config, which has them all."""
    values = dict(SKILL_DEFAULTS)
    entry = _hud_entry(wingman)
    if entry is None:
        return values, set(SKILL_DEFAULTS)
    present = set()
    for prop in entry.get("custom_properties") or []:
        if isinstance(prop, dict) and prop.get("id") in values:
            present.add(prop["id"])
            if prop.get("value") is not None:
                values[prop["id"]] = prop["value"]
    return values, present


# ─────────────────────────────── areas ─────────────────────────────── #


def _anchor(values: dict, prefix: str) -> str:
    """The container's anchor. The screen's center counts as its left center."""
    anchor = str(values[f"{prefix}_anchor"]).strip().lower()
    if anchor not in _ANCHORS:
        anchor = "top_left"
    return "left_center" if anchor == "center" else anchor


def _align(anchor: str) -> str:
    if anchor.startswith("top"):
        return "top"
    if anchor.startswith("bottom"):
        return "bottom"
    return "center"


def _manual(values: dict, prefix: str) -> bool:
    return str(values[f"{prefix}_layout_mode"]).strip().lower() == "manual"


def _size(values: dict, prefix: str, screen: Screen) -> tuple[int, int]:
    """Width and maximum height, kept on the screen."""
    width_key, height_key = (
        ("hud_width", "hud_max_height") if prefix == "chat"
        else ("persistent_width", "persistent_max_height")
    )
    width = max(MIN_WIDTH, min(_int(values[width_key], 400), screen[0]))
    height = max(MIN_HEIGHT, min(_int(values[height_key], 600), screen[1]))
    return width, height


def _x(anchor: str, width: int, screen: Screen) -> int:
    if "left" in anchor:
        return OLD_MARGIN
    if "right" in anchor:
        return screen[0] - width - OLD_MARGIN
    return screen[0] // 2 - width // 2


def _area(x: int, y: int, width: int, height: int, align: str, screen: Screen) -> dict:
    """An area on the screen. What sticks out is cut off, so the container keeps
    the edge it grows from."""
    screen_w, screen_h = screen
    x1 = max(0, min(x, screen_w - MIN_WIDTH))
    y1 = max(0, min(y, screen_h - MIN_HEIGHT))
    return {
        "x1": x1,
        "y1": y1,
        "x2": min(screen_w, max(x + width, x1 + MIN_WIDTH)),
        "y2": min(screen_h, max(y + height, y1 + MIN_HEIGHT)),
        "align": align,
    }


def _anchored(anchor: str, size: tuple[int, int], screen: Screen) -> dict:
    """Where a container alone at its anchor was: at the margin from its edge,
    or centered on the screen's height."""
    width, height = size
    align = _align(anchor)
    if align == "top":
        y = OLD_MARGIN
    elif align == "bottom":
        y = screen[1] - OLD_MARGIN - height
    else:
        y = (screen[1] - height) // 2
    return _area(_x(anchor, width, screen), y, width, height, align, screen)


def _stacked(
    anchor: str, near: tuple[int, int], far: tuple[int, int], screen: Screen
) -> tuple[dict, dict]:
    """Two containers that stacked at one anchor. The old HUD moved the one
    further out by the other's current height; an area cannot move. The near
    one keeps the place it had on its own, as on start when nothing else
    showed, and the far one starts where the near one can end."""
    (near_w, near_h), (far_w, far_h) = near, far
    align = _align(anchor)
    if align == "top":
        near_y = OLD_MARGIN
        far_y = near_y + near_h + OLD_SPACING
    elif align == "bottom":
        near_y = screen[1] - OLD_MARGIN - near_h
        far_y = near_y - OLD_SPACING - far_h
    else:
        near_y = (screen[1] - near_h) // 2
        far_y = near_y + near_h + OLD_SPACING
    return (
        _area(_x(anchor, near_w, screen), near_y, near_w, near_h, align, screen),
        _area(_x(anchor, far_w, screen), far_y, far_w, far_h, align, screen),
    )


def container_areas(values: dict, screen: Screen) -> tuple[dict, dict]:
    """The chat's and the info panel's areas, in the HUD screen's pixels."""
    chat_size = _size(values, "chat", screen)
    info_size = _size(values, "persistent", screen)
    chat_anchor = _anchor(values, "chat")
    info_anchor = _anchor(values, "persistent")
    chat_manual = _manual(values, "chat")
    info_manual = _manual(values, "persistent")

    if not chat_manual and not info_manual and chat_anchor == info_anchor:
        # The higher priority sat closer to the anchor; on a tie the chat
        chat_first = _int(values["chat_priority"], 20) >= max(
            0, _int(values["persistent_priority"], 10) - OLD_INFO_PRIORITY_OFFSET
        )
        if chat_first:
            return _stacked(chat_anchor, chat_size, info_size, screen)
        info, chat = _stacked(chat_anchor, info_size, chat_size, screen)
        return chat, info

    def place(prefix: str, anchor: str, manual: bool, size: tuple[int, int]) -> dict:
        if manual:
            # Its top left corner was at x/y, and it grew down
            x, y = _int(values[f"{prefix}_x"], 20), _int(values[f"{prefix}_y"], 20)
            return _area(x, y, size[0], size[1], "top", screen)
        return _anchored(anchor, size, screen)

    return (
        place("chat", chat_anchor, chat_manual, chat_size),
        place("persistent", info_anchor, info_manual, info_size),
    )


# ─────────────────────────────── look ─────────────────────────────── #


def _color(value, default: str) -> str:
    text = str(value or "").strip()
    return text if _HEX.match(text) else default


def _percent(value, default: int) -> int:
    return max(0, min(100, _int(value, default)))


def _background(values: dict, present: set[str]) -> tuple[str, int]:
    """bg_color and bg_opacity as the old HUD drew them. A config saved before
    bg_opacity existed kept the background's transparency in bg_color
    (#RRGGBBAA), and the skill used that."""
    color = _color(values["bg_color"], SKILL_DEFAULTS["bg_color"])
    digits = color[1:]
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    if "bg_opacity" in present:
        opacity = _percent(values["bg_opacity"], 100)
    elif len(digits) == 8:
        opacity = round(int(digits[6:], 16) / 255 * 100)
    else:
        opacity = 100
    return f"#{digits[:6]}", opacity


def build_profile(wingman: dict, screen: Screen) -> dict:
    """The default HUD profile from a Wingman's HUD skill settings."""
    values, present = skill_values(wingman)
    chat, info = container_areas(values, screen)
    bg_color, bg_opacity = _background(values, present)
    d = SKILL_DEFAULTS
    return {
        "id": "default",
        "name": "Default",
        "is_default": True,
        "configs": [],
        "chat": chat,
        "info": info,
        "style": {
            "font_size": max(1, _int(values["font_size"], d["font_size"])),
            "font_family": str(values["font_family"] or d["font_family"]),
            "accent_color": _color(values["accent_color"], d["accent_color"]),
            "bg_color": bg_color,
            "bg_opacity": bg_opacity,
            "text_color": _color(values["text_color"], d["text_color"]),
            "border_radius": max(0, _int(values["border_radius"], d["border_radius"])),
            "content_padding": max(0, _int(values["content_padding"], d["content_padding"])),
            "opacity": _percent(values["opacity"], d["opacity"]),
            "typewriter_effect": bool(values["typewriter_effect"]),
        },
        "max_display_time": max(0.0, _float(values["max_display_time"], d["max_display_time"])),
        "audio_stop_delay": max(0.0, _float(values["audio_stop_delay"], d["audio_stop_delay"])),
        "display_tool_names": bool(values["display_tool_names"]),
        # New with the profiles: the name from the client, the newest message only
        "user_name": "",
        "chat_flow": False,
        "restore_info_items": bool(values["restore_persistent_items"]),
    }


class Migration328To329(BaseMigration):
    """Migration from 3.2.8 to 3.2.9."""

    old_version = "3_2_8"
    new_version = "3_2_9"

    def migrate_settings(self, old: dict) -> dict:
        profiles = old.get("hud_profiles")
        if isinstance(profiles, list) and profiles:
            # Only a development build had profiles: what they miss comes from the template
            self._complete_profiles(profiles)
        else:
            # settings.yaml can come before the Wingmen, so read their old files
            users = self._hud_wingmen()
            if users:
                hud_server = old.get("hud_server") or {}
                screen = self._hud_screen(max(1, _int(hud_server.get("screen"), 1)))
                (config, name, wingman), dropped = users[0], users[1:]
                old["hud_profiles"] = [build_profile(wingman, screen)]
                self.log(f"- the HUD skill settings of {name} ({config}) became the default HUD profile")
                if dropped:
                    self.log(
                        "- dropped the HUD skill settings of "
                        + ", ".join(f"{n} ({c})" for c, n, _ in dropped)
                    )
            # Without anyone on the HUD skill the template's profile comes in at the end
        # The HUD is on for everyone now: each Wingman decides what it shows there
        hud_server = old.get("hud_server")
        if isinstance(hud_server, dict) and not hud_server.get("enabled"):
            hud_server["enabled"] = True
            self.log("- switched the HUD on, it is on for everyone now")
        self._delete_custom_copy()
        return old

    def migrate_defaults(self, old: dict) -> dict:
        old = self._update(old, "defaults")
        old["hud"] = {"chat": True, "info": True}
        self.log("- new Wingmen use the shared chat and the info panel")
        return old

    def migrate_wingman(self, old: dict) -> dict:
        old = self._update(old, old.get("name", "wingman"))
        if self._strip_skill(old):
            self.log("- removed the HUD skill, Core draws the HUD now")
        for change in update_uex_skill(old):
            self.log(f"- removed {change}")
        self._warn_dead_commands(old)
        old["hud"] = {"chat": True, "info": True}
        self.log("- shared chat and info panel on")
        return old

    # ─────────────────────────────── system prompt ─────────────────────────────── #

    def _update(self, config: dict, owner: str) -> dict:
        prompts = config.get("prompts")
        if not isinstance(prompts, dict) or "system_prompt" not in prompts:
            return config
        updated = update_system_prompt(prompts["system_prompt"])
        if updated != prompts["system_prompt"]:
            prompts["system_prompt"] = updated
            self.log(f"- {owner}: system prompt got the rules for commands and answer length")
        return config

    # ─────────────────────────────── HUD profiles ─────────────────────────────── #

    def _complete_profiles(self, profiles: list) -> None:
        """Fields a profile from before them misses, from the shipped profile."""
        try:
            shipped = self.config_manager.read_config(
                path.join(self.templates_dir, "configs", "settings.yaml")
            )["hud_profiles"][0]
        except Exception as e:
            self.log_warning(f"- HUD profiles not completed, no template profile: {e}")
            return
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            for key, value in shipped.items():
                if key not in profile:
                    profile[key] = value
                elif isinstance(value, dict) and isinstance(profile[key], dict):
                    for inner, inner_value in value.items():
                        profile[key].setdefault(inner, inner_value)

    # ─────────────────────────────── the old Wingmen ─────────────────────────────── #

    def _hud_wingmen(self) -> list[tuple[str, str, dict]]:
        """(config, Wingman, its config) of every Wingman with the HUD skill on,
        the HUD a user saw first at the front."""
        configs_dir = path.join(get_users_dir(), self.old_version, "configs")
        if not path.isdir(configs_dir):
            return []
        start_config = self._start_config(configs_dir)
        found = []
        for config in os.listdir(configs_dir):
            config_dir = path.join(configs_dir, config)
            # Hidden folders and files are deleted configs and Wingmen; Core skips them too
            if config.startswith(".") or not path.isdir(config_dir):
                continue
            for filename in os.listdir(config_dir):
                if (
                    filename.startswith(".")
                    or not filename.endswith(".yaml")
                    or filename.endswith("template.yaml")
                ):
                    continue
                try:
                    wingman = self.config_manager.read_config(path.join(config_dir, filename))
                except Exception:
                    continue
                if isinstance(wingman, dict) and uses_hud(wingman):
                    found.append((config, filename[: -len(".yaml")], wingman))
        found.sort(
            key=lambda user: (
                user[2].get("disabled") is True,
                user[0] != start_config,
                user[0].lower(),
                user[1].lower(),
            )
        )
        return found

    def _start_config(self, configs_dir: str) -> str:
        """The config Core loaded on start."""
        try:
            context = self.config_manager.read_config(path.join(configs_dir, CONTEXT_FILE)) or {}
            return str(context.get("default_config") or SHIPPED_DEFAULT_CONFIG)
        except Exception:
            return SHIPPED_DEFAULT_CONFIG

    def _hud_screen(self, screen: int) -> Screen:
        """The HUD screen's size the way the overlay measures it. With Windows
        display scaling that is in scaled pixels, the ones the old HUD drew in:
        3840x2160 at 125 % is 3072x1728."""
        try:
            from hud_server.platform import get_backend

            backend = get_backend()
            if backend.supported:
                monitor = backend.monitor(screen)
                self.log(f"- HUD areas measured on screen {screen}: {monitor.describe()}")
                return monitor.width, monitor.height
            reason = backend.unsupported_reason
        except Exception as e:
            reason = f"{type(e).__name__}: {e}"
        self.log_warning(
            f"- HUD screen {screen} not measured ({reason}), areas placed on "
            f"{FALLBACK_SCREEN[0]}x{FALLBACK_SCREEN[1]}"
        )
        return FALLBACK_SCREEN

    # ─────────────────────────────── the skill ─────────────────────────────── #

    def _strip_skill(self, config: dict) -> bool:
        changed = False
        skills = config.get("skills")
        if isinstance(skills, list):
            kept = [e for e in skills if not (isinstance(e, dict) and e.get("module") == _HUD_MODULE)]
            if len(kept) != len(skills):
                config["skills"] = kept
                changed = True
        names = config.get("discoverable_skills")
        if isinstance(names, list) and _HUD_NAME in names:
            config["discoverable_skills"] = [n for n in names if n != _HUD_NAME]
            changed = True
        disabled = config.get("disabled_skill_tools")
        if isinstance(disabled, list) and any(t in _HUD_TOOLS for t in disabled):
            config["disabled_skill_tools"] = [t for t in disabled if t not in _HUD_TOOLS]
            changed = True
        return changed

    def _warn_dead_commands(self, config: dict) -> None:
        """Commands bound to the skill's Hide/Show HUD have nothing left to call."""
        for command in config.get("commands") or []:
            if not isinstance(command, dict):
                continue
            for action in command.get("actions") or []:
                skill_action = (action or {}).get("skill_action") or {}
                if skill_action.get("skill_name") == _HUD_NAME:
                    self.log_warning(
                        f"- command '{command.get('name', '?')}' calls the retired HUD skill's "
                        f"'{skill_action.get('function_name', '?')}' and does nothing now; edit or delete it"
                    )

    def _delete_custom_copy(self) -> None:
        """Moves the copy out of custom_skills: it no longer loads, and the
        user's own changes to it are still there to look at."""
        folder = path.join(get_custom_skills_dir(), "hud")
        if not path.isdir(folder):
            return
        retired = path.join(path.dirname(get_custom_skills_dir()), "retired_skills")
        target, n = path.join(retired, "hud"), 1
        while path.exists(target):
            n += 1
            target = path.join(retired, f"hud_{n}")
        os.makedirs(retired, exist_ok=True)
        shutil.move(folder, target)
        self.log(f"- moved the custom HUD skill to {target}, Core draws the HUD now")
