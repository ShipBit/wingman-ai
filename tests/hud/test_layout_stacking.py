"""How the layout manager places windows by anchor: corners and edges,
stacking by priority, and how a stack follows hidden and growing windows."""

from hud_server.layout import Anchor, LayoutManager, LayoutMode

W, H, MARGIN, SPACING = 1920, 1080, 20, 10


def layout() -> LayoutManager:
    return LayoutManager(screen_width=W, screen_height=H, default_margin=MARGIN, default_spacing=SPACING)


def test_the_highest_priority_sits_nearest_its_anchor_and_nothing_overlaps():
    lm = layout()
    lm.register_window("message_ATC", anchor=Anchor.TOP_LEFT, priority=20, height=100)
    lm.register_window("message_Computer", anchor=Anchor.TOP_LEFT, priority=15, height=150)
    lm.register_window("persistent_ATC", anchor=Anchor.TOP_LEFT, priority=5, height=80)

    pos = lm.compute_positions()

    assert pos["message_ATC"][1] < pos["message_Computer"][1] < pos["persistent_ATC"][1]
    assert lm.find_collisions() == []


def test_every_anchor_puts_its_window_at_its_corner_edge_or_centre():
    lm = layout()
    for anchor in Anchor:
        lm.register_window(anchor.value, anchor=anchor, width=200, height=100)

    pos = lm.compute_positions()

    left, center_x, right = MARGIN, (W - 200) // 2, W - 200 - MARGIN
    top, center_y, bottom = MARGIN, (H - 100) // 2, H - 100 - MARGIN
    assert pos["top_left"] == (left, top)
    assert pos["top_center"] == (center_x, top)
    assert pos["top_right"] == (right, top)
    assert pos["left_center"][0] == left
    assert pos["center"] == (center_x, center_y)
    assert pos["right_center"][0] == right
    assert pos["bottom_left"] == (left, bottom)
    assert pos["bottom_center"] == (center_x, bottom)
    assert pos["bottom_right"] == (right, bottom)


def test_a_stack_at_an_edges_centre_is_centred_as_a_whole():
    lm = layout()
    for name, priority in (("first", 30), ("second", 20), ("third", 10)):
        lm.register_window(name, anchor=Anchor.LEFT_CENTER, priority=priority, width=200, height=100)

    pos = lm.compute_positions()

    start = (H - (3 * 100 + 2 * SPACING)) // 2
    assert [pos[n][1] for n in ("first", "second", "third")] == [start, start + 110, start + 220]
    assert {pos[n][0] for n in ("first", "second", "third")} == {MARGIN}


def test_a_hidden_window_leaves_its_slot_to_the_ones_below():
    lm = layout()
    for name, priority in (("top", 10), ("middle", 5), ("bottom", 1)):
        lm.register_window(name, anchor=Anchor.TOP_LEFT, priority=priority, height=100)
    before = lm.compute_positions()["bottom"][1]

    lm.set_window_visible("middle", False)
    pos = lm.compute_positions(force=True)

    assert "middle" not in pos
    assert pos["bottom"][1] == before - 100 - SPACING


def test_a_growing_window_pushes_the_ones_below_down_by_as_much():
    lm = layout()
    lm.register_window("top", anchor=Anchor.TOP_LEFT, priority=10, height=100)
    lm.register_window("below", anchor=Anchor.TOP_LEFT, priority=5, height=100)
    before = lm.compute_positions()["below"][1]

    lm.update_window_height("top", 200)

    assert lm.compute_positions(force=True)["below"][1] == before + 100


def test_a_manual_window_goes_where_it_is_told_beside_an_automatic_one():
    lm = layout()
    lm.register_window("auto", anchor=Anchor.TOP_LEFT, mode=LayoutMode.AUTO, priority=10, height=100)
    lm.register_window("manual", anchor=Anchor.TOP_LEFT, mode=LayoutMode.MANUAL, priority=5, height=100,
                       manual_x=500, manual_y=500)

    pos = lm.compute_positions()

    assert pos["auto"] == (MARGIN, MARGIN)
    assert pos["manual"] == (500, 500)


def test_overlapping_windows_are_found():
    lm = layout()
    for name, x in (("a", 100), ("b", 150), ("c", 500)):
        lm.register_window(name, mode=LayoutMode.MANUAL, width=200, height=200, manual_x=x, manual_y=x)
    lm.compute_positions()

    assert lm.check_collision("a", "b")
    assert not lm.check_collision("a", "c")
    assert lm.find_collisions() == [("a", "b")]
