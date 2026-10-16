"""A message draws its table and its loader in the profile's accent color, and
a table is as see-through as the panel's background."""

from statistics import median

from tests.support import FakeHudBackend, make_overlay, overlay_errors, run_frames

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


def test_a_table_is_tinted_with_the_accent_and_as_see_through_as_the_panel():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    show(overlay, TABLE, accent_color=RED, bg_color="#1e212b80")

    tinted = [p[3] for p in drawn(backend, overlay) if p[0] > p[1] + 5 and p[3] < 250]

    # The panel's background is #1e212b at alpha 128, which leans blue, not red
    assert len(tinted) > 10_000
    assert abs(median(tinted) - 128) <= 12


def test_the_loader_runs_in_the_accent_color():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    show(overlay, "Checking the hangar", accent_color=RED)

    overlay._handle_message({"type": "set_loader", "group": "atc", "show": True})

    assert (255, 0, 0, 255) in drawn(backend, overlay)


def test_a_loader_color_given_by_the_call_wins():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    show(overlay, "Checking the hangar", accent_color=RED)

    overlay._handle_message({"type": "set_loader", "group": "atc", "show": True, "color": "#00ff00"})

    pixels = drawn(backend, overlay)
    assert (0, 255, 0, 255) in pixels
    assert (255, 0, 0, 255) not in pixels
