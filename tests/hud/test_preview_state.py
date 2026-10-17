"""The HUD server's record of the container preview."""

from hud_server.hud_manager import HudManager


def test_a_dragged_container_is_reported_back_with_its_new_area():
    manager = HudManager()
    manager.set_preview({"chat": {"x": 100, "y": 100, "width": 500, "max_height": 300, "font_size": 16}})

    manager.preview_moved("chat", 120, 80, 720, 480)

    assert manager.get_preview()["containers"]["chat"] == {
        "x": 120, "y": 80, "width": 600, "max_height": 400, "font_size": 16,
    }


def test_clearing_the_preview_tells_the_overlay_once():
    manager = HudManager()
    commands = []
    manager.register_command_callback(commands.append)
    manager.set_preview({"info": {"x": 0, "y": 0, "width": 300, "max_height": 300}}, interactive=True)

    manager.clear_preview()
    manager.clear_preview()

    assert [c["type"] for c in commands] == ["set_preview", "clear_preview"]
    assert manager.get_preview() is None
