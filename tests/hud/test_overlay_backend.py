"""The overlay renders on any OS and draws through its platform backend."""

import time

from hud_server.platform import OsFamily, Pointer, create_backend
from tests.support import FakeHudBackend, make_overlay, overlay_errors, run_frames


def test_a_message_is_drawn_into_a_backend_window():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)

    overlay._handle_message({
        "type": "show_message", "group": "atc", "element": "message",
        "title": "ATC", "content": "Cleared for **landing**", "props": {"width": 360},
    })
    run_frames(overlay)

    window = backend.window("HUD_message_atc")
    assert window.shown
    assert window.image is not None and window.image.size[0] == 360
    assert window.opacity > 0
    assert overlay_errors(overlay) == []


def test_a_hidden_message_hides_its_window_once_faded_out():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    overlay._handle_message({
        "type": "show_message", "group": "atc", "element": "message",
        "title": "ATC", "content": "Hold short",
    })
    run_frames(overlay)

    overlay._handle_message({"type": "hide_message", "group": "atc", "element": "message"})
    run_frames(overlay)

    assert not backend.window("HUD_message_atc").shown


def test_a_window_the_os_failed_to_draw_is_drawn_on_the_next_frame():
    class FailsOnRequest(FakeHudBackend):
        failures = 0

        def present(self, window, image, opacity):
            if self.failures:
                self.failures -= 1
                raise RuntimeError("no bitmap")
            super().present(window, image, opacity)

    def message(text):
        return {
            "type": "show_message", "group": "atc", "element": "message",
            "title": "ATC", "content": text, "props": {"typewriter_effect": False},
        }

    backend = FailsOnRequest()
    overlay = make_overlay(backend)
    overlay.dt = 1.0  # faded in at once, so later frames have nothing to redraw
    overlay._handle_message(message("Hold short"))
    run_frames(overlay, 3)
    window = backend.window("HUD_message_atc")
    before = window.image.tobytes()

    backend.failures = 1
    overlay._handle_message(message("Line up, wait"))
    run_frames(overlay, 3)

    assert window.image.tobytes() != before
    assert [e["context"] for e in overlay_errors(overlay)] == ["blit_window"]


def test_dragging_a_preview_container_reports_its_new_area():
    backend = FakeHudBackend()
    events = []
    overlay = make_overlay(backend, events)
    overlay._handle_message({
        "type": "set_preview", "interactive": True,
        "containers": {"chat": {"x": 100, "y": 100, "width": 500, "max_height": 300}},
    })
    run_frames(overlay, 1)
    window = backend.window("HUD_preview_chat")
    assert not window.click_through

    # Pull the bottom edge 100 px down
    backend.pointer(window, Pointer.PRESS, 300, 398)
    assert backend.captured is window
    backend.pointer(window, Pointer.MOVE, 300, 498)
    backend.pointer(window, Pointer.RELEASE, 300, 498)

    assert backend.captured is None
    assert events[-1] == {
        "type": "preview_changed", "container": "chat",
        "x1": 100, "y1": 100, "x2": 600, "y2": 500, "final": True,
    }


def test_the_overlay_does_not_start_where_the_os_has_no_backend():
    overlay = make_overlay(create_backend(OsFamily.LINUX))

    overlay.run()

    [report] = overlay_errors(overlay)
    assert report["context"] == "init"
    assert "Linux" in report["error"]


def test_hovering_the_preview_leaves_its_picture_as_it_was():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    overlay._handle_message({
        "type": "set_preview", "interactive": True,
        "containers": {"chat": {"x": 100, "y": 100, "width": 400, "max_height": 300}},
    })
    run_frames(overlay, 3)
    window = backend.window("HUD_preview_chat")
    first = window.image.copy()

    for i in range(6):
        backend.pointer(window, Pointer.MOVE, 300 if i % 2 == 0 else 102, 250)
        run_frames(overlay, 2)
    backend.pointer(window, Pointer.MOVE, 300, 250)
    run_frames(overlay, 2)

    assert window.image.getpixel((200, 150)) == first.getpixel((200, 150))


def test_with_the_chat_flow_the_preview_shows_a_conversation():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    chat = {"x": 0, "y": 0, "width": 400, "max_height": 300, "accent_color": "#00ff00",
            "bg_color": "#000000", "opacity": 1.0}

    def preview(flow):
        overlay._handle_message({"type": "set_preview", "interactive": False,
                                 "containers": {"chat": {**chat, "chat_flow": flow}}})
        run_frames(overlay, 3)
        image = backend.window("HUD_preview_chat").image
        # The user's bubble: the accent's tint on the right half, inside the frame
        return sum(1 for p in image.crop((200, 10, 388, 150)).getdata()
                   if p[1] > 60 and p[0] < 40 and p[2] < 40)

    assert preview(False) < 50
    assert preview(True) > 300
    assert preview(False) < 50
    assert overlay_errors(overlay) == []


class RecordingBackend(FakeHudBackend):
    """Also remembers every opacity a window was drawn with, and what it
    showed at the moment it was shown."""

    def present(self, window, image, opacity):
        super().present(window, image, opacity)
        window.presented = getattr(window, "presented", []) + [opacity]

    def show_window(self, window):
        window.image_when_shown = window.image.copy() if window.image else None
        super().show_window(window)


def say(overlay, text, **props):
    overlay._handle_message({
        "type": "show_message", "group": "atc", "element": "message", "title": "ATC",
        "content": text, "props": {"duration": 0, "typewriter_effect": False, **props},
    })


def frames_on_a_clock(overlay, clock, count):
    """Frames 50 ms apart: the time a message stays is wall-clock time."""
    for _ in range(count):
        clock[0] += 0.05
        run_frames(overlay, 1)


def test_a_message_fades_out_before_its_window_hides(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    backend = RecordingBackend()
    overlay = make_overlay(backend)

    say(overlay, "Hold short")
    frames_on_a_clock(overlay, clock, 30)

    window = backend.window("HUD_message_atc")
    fading = window.presented[window.presented.index(max(window.presented)):]
    assert len(fading) > 2 and fading == sorted(fading, reverse=True)
    assert not window.shown


def test_a_window_shown_again_shows_its_new_picture_not_the_old_one(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    backend = RecordingBackend()
    overlay = make_overlay(backend)
    say(overlay, "Hold short")
    frames_on_a_clock(overlay, clock, 30)

    say(overlay, "Cleared for takeoff, runway two seven")
    frames_on_a_clock(overlay, clock, 3)

    window = backend.window("HUD_message_atc")
    assert window.shown
    assert window.image_when_shown.tobytes() == window.image.tobytes()


def test_the_info_panel_steps_aside_while_its_message_covers_it():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    area = {"layout_mode": "manual", "x": 50, "y": 50, "width": 400, "max_height": 400}
    overlay._handle_message({"type": "create_group", "group": "atc", "props": area})
    overlay._handle_message({"type": "add_item", "group": "atc", "element": "persistent",
                             "title": "Pad", "description": "04"})
    run_frames(overlay, 10)
    panel = backend.window("HUD_persistent_atc")
    assert panel.shown

    say(overlay, "Hold short", duration=60, **area)
    run_frames(overlay, 30)
    assert not panel.shown

    overlay._handle_message({"type": "hide_message", "group": "atc", "element": "message"})
    run_frames(overlay, 30)
    assert panel.shown

