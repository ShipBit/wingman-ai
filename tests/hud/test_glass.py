"""The HUD's glass look: smooth shapes, a shadow only around a panel, and
windows that move smoothly without redrawing more often than they change."""

import time

import pytest

from hud_server.overlay.overlay import HeadsUpOverlay
from hud_server.rendering import glass
from hud_server.rendering.glass import SHADOW
from tests.support import FakeHudBackend, bottom_edge, make_overlay, overlay_errors, run_frames


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    return now


def show(overlay, content="Hold short", **props):
    overlay._handle_message({
        "type": "show_message", "group": "atc", "element": "message", "title": "ATC",
        "content": content, "props": {"typewriter_effect": False, "width": 360, **props},
    })


def test_rounded_corners_are_smooth():
    mask = glass.rounded_mask(40, 30, 12)

    assert mask.getpixel((0, 0)) == 0
    assert mask.getpixel((20, 15)) == 255
    assert any(0 < mask.getpixel((x, x)) < 255 for x in range(12))


def test_a_see_through_panel_keeps_its_own_colour_with_the_shadow_only_around_it():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    show(overlay, bg_color="#20222780")
    run_frames(overlay)

    image = backend.window("HUD_message_atc").image
    bottom = SHADOW.top + overlay._windows["message_atc"]["body_height"]
    assert image.getpixel((SHADOW.left + 300, bottom - 8))[3] == 0x80
    below = image.getpixel((SHADOW.left + 180, bottom + 8))
    assert below[:3] == (0, 0, 0) and 0 < below[3] < 0x80
    assert overlay_errors(overlay) == []


def test_a_window_rises_into_place_while_it_fades_in():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    overlay._handle_message({
        "type": "create_group", "group": "atc", "element": "message",
        "props": {"layout_mode": "manual", "x": 100, "y": 200},
    })
    show(overlay)

    run_frames(overlay, 1)
    rising = backend.window("HUD_message_atc").rect[1]
    run_frames(overlay, 20)
    settled = backend.window("HUD_message_atc").rect[1]

    assert settled == 200 - SHADOW.top
    assert rising > settled


def test_a_frame_in_which_only_the_loader_moves_comes_at_most_30_times_a_second(clock):
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    presented = []
    present = backend.present
    backend.present = lambda window, image, opacity: (presented.append(clock[0]), present(window, image, opacity))
    show(overlay)
    overlay._handle_message({"type": "set_loader", "group": "atc", "show": True})
    for _ in range(30):
        clock[0] += 1 / 60
        run_frames(overlay, 1)
    presented.clear()

    for _ in range(120):  # two seconds at 60 frames a second
        clock[0] += 1 / 60
        run_frames(overlay, 1)

    assert 55 <= len(presented) <= 62


def test_an_info_item_without_a_title_has_no_icon():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    overlay._handle_message({"type": "create_group", "group": "mic", "element": "persistent",
                             "props": {"accent_color": "#00ff00", "text_color": "#ffffff"}})
    green = lambda: sum(1 for p in backend.window("HUD_persistent_mic").image.getdata()
                        if p[1] > 150 and p[0] < 100 and p[2] < 100 and p[3] > 100)

    # As the mic status shows its icon: a panel with a blank title
    overlay._handle_message({"type": "add_item", "group": "mic", "element": "persistent",
                             "title": " ", "description": "Listening"})
    run_frames(overlay)
    assert green() == 0

    overlay._handle_message({"type": "add_item", "group": "mic", "element": "persistent",
                             "title": "Mission", "description": "Deliver the cargo."})
    run_frames(overlay)
    assert green() > 0


def test_the_loader_takes_no_room():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    show(overlay, "Checking the hangar.")
    run_frames(overlay)
    height = overlay._windows["message_atc"]["body_height"]

    overlay._handle_message({"type": "set_loader", "group": "atc", "show": True})
    run_frames(overlay)

    assert overlay._windows["message_atc"]["body_height"] == height


def test_the_glow_fades_out_after_the_loader_stops():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    show(overlay, "Checking the hangar.", accent_color="#ff0000", bg_color="#000000")
    overlay._handle_message({"type": "set_loader", "group": "atc", "show": True})
    run_frames(overlay, 20)

    overlay._handle_message({"type": "set_loader", "group": "atc", "show": False})
    run_frames(overlay, 1)
    fading = bottom_edge(backend, overlay, "message_atc")
    run_frames(overlay, 20)
    gone = bottom_edge(backend, overlay, "message_atc")

    assert fading[0] > fading[1] + 20
    assert gone[0] < gone[1] + 10


@pytest.mark.parametrize("seconds, shown", [(42, "0:42"), (125, "2:05"), (3723, "1:02:03"), (90061, "1d 1:01:01")])
def test_time_left_reads_as_a_clock(seconds, shown):
    assert HeadsUpOverlay._format_remaining(seconds) == shown
