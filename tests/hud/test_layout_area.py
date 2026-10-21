"""The HUD layout: windows placed in a free area (manual mode) next to
windows that stack at an anchor."""

from hud_server.layout import Align, Anchor, LayoutManager, LayoutMode


def _layout():
    return LayoutManager(screen_width=1920, screen_height=1080, default_margin=20, default_spacing=10)


def test_a_bottom_aligned_window_grows_up_from_the_bottom_of_its_area():
    layout = _layout()
    layout.register_window(
        "message_chat", mode=LayoutMode.MANUAL, manual_x=100, manual_y=500,
        align=Align.BOTTOM, area_height=400, height=150,
    )

    assert layout.get_position("message_chat") == (100, 750)

    layout.update_window_height("message_chat", 300)
    assert layout.get_position("message_chat") == (100, 600)


def test_a_centered_window_stays_in_the_middle_of_its_area_as_it_grows():
    layout = _layout()
    layout.register_window(
        "message_chat", mode=LayoutMode.MANUAL, manual_x=100, manual_y=100,
        align=Align.CENTER, area_height=400, height=100,
    )

    assert layout.get_position("message_chat") == (100, 250)

    layout.update_window_height("message_chat", 300)
    assert layout.get_position("message_chat") == (100, 150)


def test_a_centered_window_taller_than_its_area_stays_on_the_screen():
    layout = _layout()
    layout.register_window(
        "message_chat", mode=LayoutMode.MANUAL, manual_x=100, manual_y=0,
        align=Align.CENTER, area_height=200, height=400,
    )

    assert layout.get_position("message_chat") == (100, 0)


def test_a_manual_window_takes_no_slot_in_its_anchors_stack():
    layout = _layout()
    layout.register_window(
        "message_chat", anchor=Anchor.TOP_LEFT, mode=LayoutMode.MANUAL,
        manual_x=600, manual_y=300, height=200, priority=50,
    )
    layout.register_window("persistent_mic", anchor=Anchor.TOP_LEFT, height=80, priority=10)

    assert layout.get_position("persistent_mic") == (20, 20)


def test_switching_a_window_from_auto_to_manual_moves_it():
    layout = _layout()
    layout.register_window("message_chat", anchor=Anchor.TOP_RIGHT, width=400, height=100)
    assert layout.get_position("message_chat") == (1920 - 400 - 20, 20)

    layout.update_window("message_chat", mode=LayoutMode.MANUAL, manual_x=50, manual_y=60)

    assert layout.get_position("message_chat") == (50, 60)


def test_a_manual_window_is_kept_on_the_screen():
    layout = _layout()
    layout.register_window(
        "message_chat", mode=LayoutMode.MANUAL, manual_x=1800, manual_y=1000, width=400, height=200
    )

    assert layout.get_position("message_chat") == (1920 - 400, 1080 - 200)
