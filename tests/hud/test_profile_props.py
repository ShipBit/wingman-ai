"""What a HUD profile tells the HUD server."""

from api.enums import HudAlign
from api.interface import HudArea, HudProfile
from hud_server.constants import GROUP_CHAT, GROUP_INFO
from services import hud_profiles
from tests.support import template


def _profile(**changes) -> HudProfile:
    profile = HudProfile(**template("settings.yaml")["hud_profiles"][0])
    return profile.model_copy(update=changes)


def test_a_container_area_becomes_a_manual_placement():
    profile = _profile(chat=HudArea(x1=100, y1=200, x2=600, y2=900, align=HudAlign.BOTTOM))

    _, groups = hud_profiles.hud_defaults(profile)

    assert groups[GROUP_CHAT] == {
        "layout_mode": "manual", "x": 100, "y": 200, "width": 500, "max_height": 700, "align": "bottom",
    }
    assert GROUP_INFO in groups


def test_an_area_drawn_backwards_still_has_a_size():
    area = HudArea(x1=600, y1=900, x2=100, y2=200, align=HudAlign.TOP)

    props = hud_profiles.area_props(area)

    assert (props["x"], props["y"], props["width"], props["max_height"]) == (100, 200, 500, 700)


def test_the_background_opacity_goes_into_the_colour_and_opacity_becomes_a_fraction():
    profile = _profile()
    profile.style.bg_color = "#1e212b"
    profile.style.bg_opacity = 50
    profile.style.opacity = 85

    props, _ = hud_profiles.hud_defaults(profile)

    assert props["bg_color"] == "#1e212b80"
    assert props["opacity"] == 0.85
