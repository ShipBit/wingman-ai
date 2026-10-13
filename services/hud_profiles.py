"""HUD profiles: the rules between them, and what a profile tells the HUD server.

A profile holds the layout and look of the HUD. Exactly one is the default; it
applies to every config (channel) no profile names. A config is named by at
most one profile. Everything here works on the list from the settings and has
no Core state, so the HUD service and the tests share it.
"""

import copy
import re
import uuid
from typing import Any, Optional

from api.interface import HudArea, HudProfile
from hud_server.constants import GROUP_CHAT, GROUP_INFO


class HudProfileError(ValueError):
    """A change the profile rules do not allow."""


def find_profile(profiles: list[HudProfile], profile_id: str) -> HudProfile:
    for profile in profiles:
        if profile.id == profile_id:
            return profile
    raise KeyError(profile_id)


def normalize(profiles: list[HudProfile], default_id: Optional[str] = None) -> None:
    """Exactly one default (`default_id` if given), each config in one profile.

    With no default left, the first profile becomes it, so the last remaining
    profile is always the default.
    """
    if default_id is None or not any(p.id == default_id for p in profiles):
        default_id = next((p.id for p in profiles if p.is_default), None)
    if default_id is None and profiles:
        default_id = profiles[0].id
    for profile in profiles:
        profile.is_default = profile.id == default_id

    seen: set[str] = set()
    for profile in profiles:
        unique = []
        for config in profile.configs:
            if config not in seen:
                seen.add(config)
                unique.append(config)
        profile.configs = unique


def active_profile(profiles: list[HudProfile], config_name: Optional[str]) -> Optional[HudProfile]:
    """The profile that names the config, otherwise the default."""
    if config_name:
        for profile in profiles:
            if config_name in profile.configs:
                return profile
    return next((p for p in profiles if p.is_default), profiles[0] if profiles else None)


def assign_configs(profiles: list[HudProfile], profile_id: str, configs: list[str]) -> None:
    """Give `configs` to one profile; any other profile naming them lets go."""
    for profile in profiles:
        if profile.id == profile_id:
            profile.configs = list(dict.fromkeys(configs))
        else:
            profile.configs = [c for c in profile.configs if c not in configs]


def rename_config(profiles: list[HudProfile], old: str, new: str) -> bool:
    changed = False
    for profile in profiles:
        if old in profile.configs:
            profile.configs = [new if c == old else c for c in profile.configs]
            changed = True
    return changed


def remove_config(profiles: list[HudProfile], name: str) -> bool:
    changed = False
    for profile in profiles:
        if name in profile.configs:
            profile.configs = [c for c in profile.configs if c != name]
            changed = True
    return changed


def delete_profile(profiles: list[HudProfile], profile_id: str) -> None:
    profile = find_profile(profiles, profile_id)
    if profile.is_default:
        raise HudProfileError("The default profile cannot be deleted. Make another profile the default first.")
    profiles.remove(profile)
    normalize(profiles)


def new_profile(name: str, source: HudProfile) -> HudProfile:
    """A copy of `source` under a new id, not the default, naming no config."""
    profile = copy.deepcopy(source)
    profile.id = uuid.uuid4().hex[:8]
    profile.name = name
    profile.is_default = False
    profile.configs = []
    return profile


# ─────────────────────────────── HUD server props ─────────────────────────────── #


_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def merge_alpha(hex_color: str, opacity_percent: float) -> str:
    """#RRGGBBAA with the alpha taken from a 0-100 percentage. Any alpha the
    colour had is replaced; an invalid colour comes back unchanged."""
    if not isinstance(hex_color, str) or not _HEX.match(hex_color):
        return hex_color
    digits = hex_color[1:]
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    alpha = max(0, min(255, round(opacity_percent / 100 * 255)))
    return f"#{digits[:6]}{alpha:02x}"


def style_props(profile: HudProfile) -> dict[str, Any]:
    """The look every HUD window inherits."""
    style = profile.style
    return {
        "font_size": style.font_size,
        "font_family": style.font_family,
        "accent_color": style.accent_color,
        "bg_color": merge_alpha(style.bg_color, style.bg_opacity),
        "text_color": style.text_color,
        "border_radius": style.border_radius,
        "content_padding": style.content_padding,
        "opacity": max(0, min(100, style.opacity)) / 100,
        "typewriter_effect": style.typewriter_effect,
    }


def area_props(area: HudArea) -> dict[str, Any]:
    """A container's area as HUD server props (manual placement)."""
    x1, x2 = sorted((area.x1, area.x2))
    y1, y2 = sorted((area.y1, area.y2))
    return {
        "layout_mode": "manual",
        "x": x1,
        "y": y1,
        "width": max(1, x2 - x1),
        "max_height": max(1, y2 - y1),
        "align": area.align.value,
    }


def hud_defaults(profile: HudProfile) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """What the HUD server uses for values calls leave out: the style for every
    group, the areas for the two shared containers."""
    return style_props(profile), {
        GROUP_CHAT: area_props(profile.chat),
        GROUP_INFO: area_props(profile.info),
    }


def preview_containers(profile: HudProfile) -> dict[str, dict[str, Any]]:
    style = style_props(profile)
    return {
        "chat": {**style, **area_props(profile.chat)},
        "info": {**style, **area_props(profile.info)},
    }


def area_from_rect(area: HudArea, x1: int, y1: int, x2: int, y2: int) -> HudArea:
    return HudArea(x1=x1, y1=y1, x2=x2, y2=y2, align=area.align)
