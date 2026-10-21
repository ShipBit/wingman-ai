"""A message's loader glows in the profile's accent color, and its tables
are a shade of the panel's background, as see-through as the background."""

from tests.support import FakeHudBackend, bottom_edge, make_overlay, overlay_errors, run_frames

RED = "#ff0000"
TABLE = "| Ship | Fuel |\n|---|---|\n| Cutlass | 80 % |\n| Prospector | 45 % |\n| Vulture | 12 % |"


def show(overlay, content, **props):
    overlay._handle_message({
        "type": "show_message", "group": "atc", "element": "message", "title": " ",
        "content": content, "props": {"typewriter_effect": False, **props},
    })


def drawn(backend, overlay):
    run_frames(overlay)
    assert overlay_errors(overlay) == []
    return list(backend.window("HUD_message_atc").image.getdata())


def table_pixels(pixels, panel, lighter):
    """Neutral pixels a little lighter (or darker) than the panel, at about its opacity."""
    def shaded(p):
        neutral = max(p[:3]) - min(p[:3]) <= max(panel) - min(panel) + 6
        moved = all(c > b for c, b in zip(p[:3], panel)) if lighter else all(c < b for c, b in zip(p[:3], panel))
        return neutral and moved and 128 <= p[3] <= 150
    return [p for p in pixels if shaded(p)]


def test_a_table_is_a_lighter_shade_of_a_dark_background_and_as_see_through():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    show(overlay, TABLE, accent_color=RED, bg_color="#1e212b80")

    pixels = drawn(backend, overlay)

    assert len(table_pixels(pixels, (30, 33, 43), lighter=True)) > 10_000
    # Not the accent: only the red header text leans red
    assert sum(1 for p in pixels if p[0] > p[1] + 5 and p[3] < 250) < 2_000


def test_on_a_light_background_a_table_is_a_darker_shade():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    show(overlay, TABLE, accent_color=RED, bg_color="#f0f0f080", text_color="#202020")

    assert len(table_pixels(drawn(backend, overlay), (240, 240, 240), lighter=False)) > 10_000


def test_the_loader_glows_on_the_bottom_edge_in_the_accent_color():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    show(overlay, "Checking the hangar", accent_color=RED, bg_color="#000000")
    run_frames(overlay)
    r, g, b, _ = bottom_edge(backend, overlay, "message_atc")
    assert r < g + 10

    overlay._handle_message({"type": "set_loader", "group": "atc", "show": True})
    run_frames(overlay)

    r, g, b, _ = bottom_edge(backend, overlay, "message_atc")
    assert r > g + 40 and r > b + 40
    assert overlay_errors(overlay) == []
