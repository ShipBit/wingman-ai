"""
Test script for the Layout Manager.

Usage:
    python -m hud_server.tests.test_layout
"""
import sys
sys.path.insert(0, ".")

from hud_server.layout import LayoutManager, Anchor, LayoutMode


def test_basic_stacking():
    """Test basic vertical stacking at top-left anchor."""
    print("=" * 60)
    print("Test: Basic Vertical Stacking")
    print("=" * 60)

    layout = LayoutManager(screen_width=1920, screen_height=1080)

    # Register three windows at top-left
    layout.register_window("message_ATC", anchor=Anchor.TOP_LEFT, priority=20, height=100)
    layout.register_window("message_Computer", anchor=Anchor.TOP_LEFT, priority=15, height=150)
    layout.register_window("persistent_ATC", anchor=Anchor.TOP_LEFT, priority=5, height=80)

    positions = layout.compute_positions()

    print("Positions:")
    for name, pos in sorted(positions.items(), key=lambda x: x[1][1]):
        print(f"  {name}: x={pos[0]}, y={pos[1]}")

    # Verify ordering: higher priority windows are closer to anchor (lower y)
    assert positions["message_ATC"][1] < positions["message_Computer"][1], "message_ATC should be above message_Computer"
    assert positions["message_Computer"][1] < positions["persistent_ATC"][1], "message_Computer should be above persistent_ATC"

    # Verify no overlap
    for name1 in positions:
        for name2 in positions:
            if name1 >= name2:
                continue
            assert not layout.check_collision(name1, name2), f"{name1} and {name2} should not overlap"

    print("✓ Basic stacking test passed!\n")


def test_multiple_anchors():
    """Test windows at different anchors."""
    print("=" * 60)
    print("Test: Multiple Anchors")
    print("=" * 60)

    layout = LayoutManager(screen_width=1920, screen_height=1080)

    # Register windows at different corners
    layout.register_window("left_top", anchor=Anchor.TOP_LEFT, width=400, height=100)
    layout.register_window("right_top", anchor=Anchor.TOP_RIGHT, width=400, height=100)
    layout.register_window("left_bottom", anchor=Anchor.BOTTOM_LEFT, width=400, height=100)
    layout.register_window("right_bottom", anchor=Anchor.BOTTOM_RIGHT, width=400, height=100)

    positions = layout.compute_positions()

    print("Positions:")
    for name, pos in positions.items():
        print(f"  {name}: x={pos[0]}, y={pos[1]}")

    # Verify corners
    assert positions["left_top"][0] == 20, "left_top should be at left margin"
    assert positions["left_top"][1] == 20, "left_top should be at top margin"

    assert positions["right_top"][0] == 1920 - 400 - 20, "right_top should be at right edge"
    assert positions["right_top"][1] == 20, "right_top should be at top margin"

    assert positions["left_bottom"][0] == 20, "left_bottom should be at left margin"
    assert positions["left_bottom"][1] == 1080 - 100 - 20, "left_bottom should be at bottom edge"

    assert positions["right_bottom"][0] == 1920 - 400 - 20, "right_bottom should be at right edge"
    assert positions["right_bottom"][1] == 1080 - 100 - 20, "right_bottom should be at bottom edge"

    print("✓ Multiple anchors test passed!\n")


def test_visibility():
    """Test visibility affecting layout."""
    print("=" * 60)
    print("Test: Visibility")
    print("=" * 60)

    layout = LayoutManager(screen_width=1920, screen_height=1080)

    layout.register_window("win1", anchor=Anchor.TOP_LEFT, priority=10, height=100)
    layout.register_window("win2", anchor=Anchor.TOP_LEFT, priority=5, height=100)
    layout.register_window("win3", anchor=Anchor.TOP_LEFT, priority=1, height=100)

    # All visible
    positions = layout.compute_positions()
    print("All visible:")
    for name, pos in sorted(positions.items(), key=lambda x: x[1][1]):
        print(f"  {name}: y={pos[1]}")

    original_win3_y = positions["win3"][1]

    # Hide win2
    layout.set_window_visible("win2", False)
    positions = layout.compute_positions(force=True)
    print("\nWith win2 hidden:")
    for name, pos in sorted(positions.items(), key=lambda x: x[1][1]):
        print(f"  {name}: y={pos[1]}")

    # win3 should move up (lower y value)
    assert positions["win3"][1] < original_win3_y, "win3 should move up when win2 is hidden"
    assert "win2" not in positions, "win2 should not be in positions when hidden"

    print("✓ Visibility test passed!\n")


def test_height_update():
    """Test dynamic height changes."""
    print("=" * 60)
    print("Test: Dynamic Height Updates")
    print("=" * 60)

    layout = LayoutManager(screen_width=1920, screen_height=1080)

    layout.register_window("win1", anchor=Anchor.TOP_LEFT, priority=10, height=100)
    layout.register_window("win2", anchor=Anchor.TOP_LEFT, priority=5, height=100)

    positions = layout.compute_positions()
    original_win2_y = positions["win2"][1]
    print(f"Original: win1 y={positions['win1'][1]}, win2 y={positions['win2'][1]}")

    # Increase win1 height
    layout.update_window_height("win1", 200)
    positions = layout.compute_positions(force=True)
    new_win2_y = positions["win2"][1]
    print(f"After win1 grows: win1 y={positions['win1'][1]}, win2 y={positions['win2'][1]}")

    assert new_win2_y > original_win2_y, "win2 should move down when win1 grows"
    assert new_win2_y == original_win2_y + 100, f"win2 should move down by 100px (got {new_win2_y - original_win2_y})"

    print("✓ Height update test passed!\n")


def test_manual_mode():
    """Test manual positioning mode."""
    print("=" * 60)
    print("Test: Manual Mode")
    print("=" * 60)

    layout = LayoutManager(screen_width=1920, screen_height=1080)

    # One auto, one manual
    layout.register_window("auto_win", anchor=Anchor.TOP_LEFT, mode=LayoutMode.AUTO, priority=10, height=100)
    layout.register_window("manual_win", anchor=Anchor.TOP_LEFT, mode=LayoutMode.MANUAL, priority=5, height=100, manual_x=500, manual_y=500)

    positions = layout.compute_positions()
    print("Positions:")
    for name, pos in positions.items():
        print(f"  {name}: x={pos[0]}, y={pos[1]}")

    assert positions["auto_win"] == (20, 20), "auto_win should be at auto position"
    assert positions["manual_win"] == (500, 500), "manual_win should be at manual position"

    print("✓ Manual mode test passed!\n")


def test_collision_detection():
    """Test collision detection between windows."""
    print("=" * 60)
    print("Test: Collision Detection")
    print("=" * 60)

    layout = LayoutManager(screen_width=1920, screen_height=1080)

    # Create overlapping windows with manual positioning
    layout.register_window("win1", mode=LayoutMode.MANUAL, width=200, height=200, manual_x=100, manual_y=100)
    layout.register_window("win2", mode=LayoutMode.MANUAL, width=200, height=200, manual_x=150, manual_y=150)
    layout.register_window("win3", mode=LayoutMode.MANUAL, width=200, height=200, manual_x=500, manual_y=500)

    positions = layout.compute_positions()

    print("Checking collisions:")
    col_1_2 = layout.check_collision("win1", "win2")
    col_1_3 = layout.check_collision("win1", "win3")
    col_2_3 = layout.check_collision("win2", "win3")

    print(f"  win1 vs win2: {col_1_2}")
    print(f"  win1 vs win3: {col_1_3}")
    print(f"  win2 vs win3: {col_2_3}")

    assert col_1_2, "win1 and win2 should collide"
    assert not col_1_3, "win1 and win3 should not collide"
    assert not col_2_3, "win2 and win3 should not collide"

    collisions = layout.find_collisions()
    print(f"  All collisions: {collisions}")
    assert len(collisions) == 1, "Should find exactly 1 collision"
    assert ("win1", "win2") in collisions, "Should detect win1-win2 collision"

    print("✓ Collision detection test passed!\n")


def test_all_nine_anchors():
    """Test all 9 anchor positions."""
    print("=" * 60)
    print("Test: All 9 Anchor Positions")
    print("=" * 60)

    layout = LayoutManager(screen_width=1920, screen_height=1080)

    # Register windows at all 9 anchors
    anchors = [
        (Anchor.TOP_LEFT, "tl"),
        (Anchor.TOP_CENTER, "tc"),
        (Anchor.TOP_RIGHT, "tr"),
        (Anchor.LEFT_CENTER, "lc"),
        (Anchor.CENTER, "c"),
        (Anchor.RIGHT_CENTER, "rc"),
        (Anchor.BOTTOM_LEFT, "bl"),
        (Anchor.BOTTOM_CENTER, "bc"),
        (Anchor.BOTTOM_RIGHT, "br"),
    ]

    for anchor, name in anchors:
        layout.register_window(name, anchor=anchor, width=200, height=100)

    positions = layout.compute_positions()

    print("Positions for all 9 anchors:")
    for name, pos in sorted(positions.items()):
        print(f"  {name}: x={pos[0]}, y={pos[1]}")

    # Verify key positions
    # Top row
    assert positions["tl"][0] == 20, "top_left x should be margin"
    assert positions["tl"][1] == 20, "top_left y should be margin"

    assert positions["tc"][0] == (1920 - 200) // 2, "top_center x should be centered"
    assert positions["tc"][1] == 20, "top_center y should be margin"

    assert positions["tr"][0] == 1920 - 200 - 20, "top_right x should be right edge"
    assert positions["tr"][1] == 20, "top_right y should be margin"

    # Middle row (left/right center are vertically centered)
    assert positions["lc"][0] == 20, "left_center x should be margin"
    assert positions["rc"][0] == 1920 - 200 - 20, "right_center x should be right edge"

    # Center
    assert positions["c"][0] == (1920 - 200) // 2, "center x should be centered"
    assert positions["c"][1] == (1080 - 100) // 2, "center y should be centered"

    # Bottom row
    assert positions["bl"][0] == 20, "bottom_left x should be margin"
    assert positions["bl"][1] == 1080 - 100 - 20, "bottom_left y should be bottom"

    assert positions["bc"][0] == (1920 - 200) // 2, "bottom_center x should be centered"
    assert positions["bc"][1] == 1080 - 100 - 20, "bottom_center y should be bottom"

    assert positions["br"][0] == 1920 - 200 - 20, "bottom_right x should be right"
    assert positions["br"][1] == 1080 - 100 - 20, "bottom_right y should be bottom"

    print("✓ All 9 anchors test passed!\n")


def test_center_edge_stacking():
    """Test stacking at center-edge anchors (left_center, right_center)."""
    print("=" * 60)
    print("Test: Center-Edge Stacking")
    print("=" * 60)

    layout = LayoutManager(screen_width=1920, screen_height=1080)

    # Stack 3 windows at left_center
    layout.register_window("lc1", anchor=Anchor.LEFT_CENTER, priority=30, width=200, height=100)
    layout.register_window("lc2", anchor=Anchor.LEFT_CENTER, priority=20, width=200, height=100)
    layout.register_window("lc3", anchor=Anchor.LEFT_CENTER, priority=10, width=200, height=100)

    positions = layout.compute_positions()

    print("Left-center stack positions:")
    for name in ["lc1", "lc2", "lc3"]:
        print(f"  {name}: x={positions[name][0]}, y={positions[name][1]}")

    # The stack should be vertically centered
    # Total height = 3 * 100 + 2 * 10 = 320
    # Starting y = (1080 - 320) / 2 = 380
    expected_start_y = (1080 - 320) // 2

    assert positions["lc1"][1] == expected_start_y, f"lc1 should start at y={expected_start_y}"
    assert positions["lc2"][1] == expected_start_y + 110, f"lc2 should be at y={expected_start_y + 110}"
    assert positions["lc3"][1] == expected_start_y + 220, f"lc3 should be at y={expected_start_y + 220}"

    # All should be at left margin
    for name in ["lc1", "lc2", "lc3"]:
        assert positions[name][0] == 20, f"{name} should be at left margin"

    print("✓ Center-edge stacking test passed!\n")


def run_all_tests():
    """Run all layout manager tests."""
    print("\n" + "=" * 60)
    print("LAYOUT MANAGER TEST SUITE")
    print("=" * 60 + "\n")

    try:
        test_basic_stacking()
        test_multiple_anchors()
        test_all_nine_anchors()
        test_center_edge_stacking()
        test_visibility()
        test_height_update()
        test_manual_mode()
        test_collision_detection()

        print("=" * 60)
        print("ALL TESTS PASSED! ✓")
        print("=" * 60)
        return True

    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

    except Exception as e:
        print(f"\n✗ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
