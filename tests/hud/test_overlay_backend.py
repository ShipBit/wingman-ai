"""The overlay renders on any OS and draws through its platform backend."""

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


def test_moving_a_chat_window_puts_it_back_on_top():
    backend = FakeHudBackend()
    overlay = make_overlay(backend)
    overlay._handle_message({"type": "create_chat_window", "name": "squad", "props": {"layout_mode": "manual"}})
    window = backend.window("HeadsUpChat_squad")

    overlay._handle_message({"type": "update_chat_window", "name": "squad", "props": {"x": 300, "y": 200}})

    assert window.rect[:2] == (300, 200)
    assert window.raised == 1


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
