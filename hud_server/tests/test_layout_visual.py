"""
Visual Layout Integration Test - Tests layout manager with actual HUD content.

This test creates multiple HUD groups with different anchors and priorities,
displays content in them, and verifies the layout system stacks them correctly.

Usage:
    python -m hud_server.tests.test_layout_visual

Requirements:
    - HUD Server must be running (will be auto-started)
    - Windows only (overlay uses Win32 API)
"""
import sys
import asyncio

sys.path.insert(0, ".")

from hud_server.tests.test_runner import TestContext
from hud_server.types import Anchor, LayoutMode, HudColor, MessageProps, WindowType


# =============================================================================
# ANCHOR CONFIGURATION - All 9 anchor points
# =============================================================================

ANCHOR_CONFIG = {
    Anchor.TOP_LEFT: {
        "label": "TOP LEFT",
        "color": HudColor.ERROR,
        "emoji_fallback": "[TL]",
    },
    Anchor.TOP_CENTER: {
        "label": "TOP CENTER",
        "color": HudColor.ACCENT_ORANGE,
        "emoji_fallback": "[TC]",
    },
    Anchor.TOP_RIGHT: {
        "label": "TOP RIGHT",
        "color": HudColor.ACCENT_GREEN,
        "emoji_fallback": "[TR]",
    },
    Anchor.RIGHT_CENTER: {
        "label": "RIGHT CENTER",
        "color": HudColor.CYAN,
        "emoji_fallback": "[RC]",
    },
    Anchor.BOTTOM_RIGHT: {
        "label": "BOTTOM RIGHT",
        "color": HudColor.BLUE,
        "emoji_fallback": "[BR]",
    },
    Anchor.BOTTOM_CENTER: {
        "label": "BOTTOM CENTER",
        "color": HudColor.MAGENTA,
        "emoji_fallback": "[BC]",
    },
    Anchor.BOTTOM_LEFT: {
        "label": "BOTTOM LEFT",
        "color": HudColor.YELLOW,
        "emoji_fallback": "[BL]",
    },
    Anchor.LEFT_CENTER: {
        "label": "LEFT CENTER",
        "color": "#ff8855",
        "emoji_fallback": "[LC]",
    },
    Anchor.CENTER: {
        "label": "CENTER",
        "color": HudColor.WHITE,
        "emoji_fallback": "[C]",
    },
}


def _get_value(val):
    """Get the string value from an enum or return as-is."""
    return val.value if hasattr(val, 'value') else val


async def cleanup_groups(client, group_names):
    """Helper to clean up groups."""
    for name in group_names:
        try:
            await client.hide_message(name, WindowType.MESSAGE)
        except:
            pass
    await asyncio.sleep(0.5)


async def test_all_nine_anchors(session):
    """Test all 9 anchor positions simultaneously."""
    print("\n" + "=" * 70)
    print("TEST 1: All 9 Anchor Positions")
    print("=" * 70)
    print("Creating windows at all 9 anchor points...")

    client = session._client
    groups = []

    for anchor, config in ANCHOR_CONFIG.items():
        group_name = f"anchor_{_get_value(anchor)}"
        groups.append(group_name)

        props = MessageProps(
            anchor=_get_value(anchor),
            priority=10,
            layout_mode=LayoutMode.AUTO.value,
            width=280,
            accent_color=_get_value(config["color"]),
        )
        await client.create_group(group_name, WindowType.MESSAGE, props=props)

        await client.show_message(
            group_name,
            WindowType.MESSAGE,
            title=f"{config['emoji_fallback']} {config['label']}",
            content=f"Anchor: **{_get_value(anchor)}**\n\nThis window is positioned at the {config['label'].lower()} of the screen.",
            duration=30.0
        )
        await asyncio.sleep(0.15)

    print("\nAll 9 windows displayed!")
    print("Visual verification:")
    print("  - TOP ROW: Left, Center, Right")
    print("  - MIDDLE ROW: Left edge, Center (if visible), Right edge")
    print("  - BOTTOM ROW: Left, Center, Right")

    await asyncio.sleep(6)
    await cleanup_groups(client, groups)
    print("[OK] Test 1 complete\n")


async def test_priority_stacking(session):
    """Test priority-based stacking at each anchor."""
    print("\n" + "=" * 70)
    print("TEST 2: Priority-Based Stacking")
    print("=" * 70)

    client = session._client
    groups = []

    # Test stacking at TOP_LEFT with 3 priority levels
    priorities = [
        ("stack_high", 30, HudColor.ERROR, "HIGH Priority (30)"),
        ("stack_med", 20, HudColor.ACCENT_GREEN, "MEDIUM Priority (20)"),
        ("stack_low", 10, HudColor.INFO, "LOW Priority (10)"),
    ]

    print("Creating 3 windows at TOP_LEFT with different priorities...")

    for name, priority, color, label in priorities:
        groups.append(name)
        props = MessageProps(
            anchor=Anchor.TOP_LEFT.value,
            priority=priority,
            layout_mode=LayoutMode.AUTO.value,
            width=380,
            accent_color=_get_value(color),
        )
        await client.create_group(name, WindowType.MESSAGE, props=props)

        await client.show_message(
            name,
            WindowType.MESSAGE,
            title=label,
            content=f"Priority value: **{priority}**\n\nHigher priority = closer to anchor point (top).",
            duration=20.0
        )
        await asyncio.sleep(0.2)

    print("\nExpected order (top to bottom):")
    print("  1. RED - High (30)")
    print("  2. GREEN - Medium (20)")
    print("  3. BLUE - Low (10)")

    await asyncio.sleep(5)

    # Now add windows to TOP_RIGHT to show parallel stacking
    print("\nAdding 2 windows to TOP_RIGHT...")

    for name, priority, color in [("right_a", 25, HudColor.ACCENT_ORANGE), ("right_b", 15, HudColor.ACCENT_PURPLE)]:
        groups.append(name)
        props = MessageProps(
            anchor=Anchor.TOP_RIGHT.value,
            priority=priority,
            layout_mode=LayoutMode.AUTO.value,
            width=320,
            accent_color=_get_value(color),
        )
        await client.create_group(name, WindowType.MESSAGE, props=props)

        await client.show_message(
            name,
            WindowType.MESSAGE,
            title=f"Right Side (P:{priority})",
            content=f"Independent stack on right side.\nPriority: {priority}",
            duration=15.0
        )
        await asyncio.sleep(0.2)

    print("Both sides now have independent stacks!")

    await asyncio.sleep(5)
    await cleanup_groups(client, groups)
    print("[OK] Test 2 complete\n")


async def test_dynamic_height_changes(session):
    """Test that windows reflow when heights change dynamically."""
    print("\n" + "=" * 70)
    print("TEST 3: Dynamic Height Changes & Reflow")
    print("=" * 70)

    client = session._client
    groups = ["dyn_top", "dyn_bottom"]

    # Create two stacked windows
    top_props = MessageProps(
        anchor=Anchor.TOP_LEFT.value,
        priority=20,
        layout_mode=LayoutMode.AUTO.value,
        width=420,
        accent_color=HudColor.ACCENT_ORANGE.value,
    )
    await client.create_group("dyn_top", WindowType.MESSAGE, props=top_props)

    bottom_props = MessageProps(
        anchor=Anchor.TOP_LEFT.value,
        priority=10,
        layout_mode=LayoutMode.AUTO.value,
        width=420,
        accent_color=HudColor.ACCENT_BLUE.value,
    )
    await client.create_group("dyn_bottom", WindowType.MESSAGE, props=bottom_props)

    # Phase 1: Short top window
    print("Phase 1: Top window is SHORT")
    await client.show_message(
        "dyn_top",
        WindowType.MESSAGE,
        title="Top Window - SHORT",
        content="This is a short message.",
        duration=30.0
    )
    await asyncio.sleep(0.3)

    await client.show_message(
        "dyn_bottom",
        WindowType.MESSAGE,
        title="Bottom Window",
        content="Watch me move as the top window changes height!",
        duration=30.0
    )
    await asyncio.sleep(3)

    # Phase 2: Tall top window
    print("Phase 2: Top window GROWS - bottom should move DOWN")
    await client.show_message(
        "dyn_top",
        WindowType.MESSAGE,
        title="Top Window - TALL",
        content="""This window has grown significantly!

## Content Section

Here's a list of items:
- First important item
- Second important item  
- Third important item
- Fourth important item

### Additional Details

The bottom window should have automatically
repositioned itself below this content.

```
No manual adjustment needed!
Layout manager handles it.
```
""",
        duration=25.0
    )
    await asyncio.sleep(4)

    # Phase 3: Short again
    print("Phase 3: Top window SHRINKS - bottom should move UP")
    await client.show_message(
        "dyn_top",
        WindowType.MESSAGE,
        title="Top Window - SHORT again",
        content="Shrunk back down.",
        duration=20.0
    )
    await asyncio.sleep(3)

    # Phase 4: Medium height
    print("Phase 4: Top window MEDIUM height")
    await client.show_message(
        "dyn_top",
        WindowType.MESSAGE,
        title="Top Window - MEDIUM",
        content="Now at a medium height.\n\nWith a bit more content.\n\nJust enough to demonstrate.",
        duration=15.0
    )
    await asyncio.sleep(3)

    await cleanup_groups(client, groups)
    print("[OK] Test 3 complete\n")


async def test_visibility_reflow(session):
    """Test that hiding windows causes others to reflow."""
    print("\n" + "=" * 70)
    print("TEST 4: Visibility Changes & Reflow")
    print("=" * 70)

    client = session._client
    groups = ["vis_1", "vis_2", "vis_3"]

    colors = [HudColor.RED, HudColor.GREEN, HudColor.BLUE]
    labels = ["First (Red)", "Second (Green)", "Third (Blue)"]

    for i, (name, color, label) in enumerate(zip(groups, colors, labels)):
        props = MessageProps(
            anchor=Anchor.TOP_LEFT.value,
            priority=30 - (i * 10),
            layout_mode=LayoutMode.AUTO.value,
            width=380,
            accent_color=_get_value(color),
        )
        await client.create_group(name, WindowType.MESSAGE, props=props)

    # Show all three
    print("Phase 1: All 3 windows visible")
    for name, label in zip(groups, labels):
        await client.show_message(name, WindowType.MESSAGE, title=label, content=f"Window: {label}", duration=30.0)
        await asyncio.sleep(0.2)
    await asyncio.sleep(3)

    # Hide middle (green)
    print("Phase 2: HIDING middle (Green) - Blue should move UP")
    await client.hide_message("vis_2", WindowType.MESSAGE)
    await asyncio.sleep(3)

    # Show middle again
    print("Phase 3: SHOWING middle (Green) - Blue should move DOWN")
    await client.show_message("vis_2", WindowType.MESSAGE, title="Second (Green) - BACK!", content="I'm back in the stack!", duration=20.0)
    await asyncio.sleep(3)

    # Hide first (red)
    print("Phase 4: HIDING first (Red) - Both should move UP")
    await client.hide_message("vis_1", WindowType.MESSAGE)
    await asyncio.sleep(3)

    # Hide all except blue
    print("Phase 5: Only Blue remains")
    await client.hide_message("vis_2", WindowType.MESSAGE)
    await asyncio.sleep(2)

    await cleanup_groups(client, groups)
    print("[OK] Test 4 complete\n")


async def test_opposite_anchors(session):
    """Test opposite corners simultaneously."""
    print("\n" + "=" * 70)
    print("TEST 5: Opposite Corners (Diagonal)")
    print("=" * 70)

    client = session._client
    groups = []

    pairs = [
        ("diag_tl", Anchor.TOP_LEFT, HudColor.RED, "TOP-LEFT Corner"),
        ("diag_br", Anchor.BOTTOM_RIGHT, HudColor.GREEN, "BOTTOM-RIGHT Corner"),
        ("diag_tr", Anchor.TOP_RIGHT, HudColor.BLUE, "TOP-RIGHT Corner"),
        ("diag_bl", Anchor.BOTTOM_LEFT, HudColor.YELLOW, "BOTTOM-LEFT Corner"),
    ]

    print("Creating windows at all 4 corners...")

    for name, anchor, color, label in pairs:
        groups.append(name)
        props = MessageProps(
            anchor=_get_value(anchor),
            priority=10,
            layout_mode=LayoutMode.AUTO.value,
            width=320,
            accent_color=_get_value(color),
        )
        await client.create_group(name, WindowType.MESSAGE, props=props)

        await client.show_message(
            name,
            WindowType.MESSAGE,
            title=label,
            content=f"Anchor: **{_get_value(anchor)}**\n\nDiagonal positioning test.",
            duration=15.0
        )
        await asyncio.sleep(0.15)

    print("All 4 corners populated - verify no overlaps!")

    await asyncio.sleep(5)
    await cleanup_groups(client, groups)
    print("[OK] Test 5 complete\n")


async def test_center_anchors(session):
    """Test center and edge-center anchors."""
    print("\n" + "=" * 70)
    print("TEST 6: Center and Edge-Center Anchors")
    print("=" * 70)

    client = session._client
    groups = []

    # First show center
    groups.append("center_main")
    center_props = MessageProps(
        anchor=Anchor.CENTER.value,
        priority=10,
        layout_mode=LayoutMode.AUTO.value,
        width=350,
        accent_color=HudColor.WHITE.value,
    )
    await client.create_group("center_main", WindowType.MESSAGE, props=center_props)

    await client.show_message(
        "center_main",
        WindowType.MESSAGE,
        title="CENTER",
        content="This window is in the absolute center of the screen.",
        duration=20.0
    )

    print("Center window displayed")
    await asyncio.sleep(2)

    # Add edge centers
    edge_centers = [
        ("edge_top", Anchor.TOP_CENTER, HudColor.ACCENT_ORANGE, "TOP CENTER EDGE"),
        ("edge_bottom", Anchor.BOTTOM_CENTER, HudColor.ACCENT_PURPLE, "BOTTOM CENTER EDGE"),
        ("edge_left", Anchor.LEFT_CENTER, HudColor.ACCENT_GREEN, "LEFT CENTER EDGE"),
        ("edge_right", Anchor.RIGHT_CENTER, HudColor.ACCENT_PINK, "RIGHT CENTER EDGE"),
    ]

    print("Adding edge-center windows...")

    for name, anchor, color, label in edge_centers:
        groups.append(name)
        props = MessageProps(
            anchor=_get_value(anchor),
            priority=10,
            layout_mode=LayoutMode.AUTO.value,
            width=260,
            accent_color=_get_value(color),
        )
        await client.create_group(name, WindowType.MESSAGE, props=props)

        await client.show_message(
            name,
            WindowType.MESSAGE,
            title=label,
            content=f"Positioned at the {_get_value(anchor).replace('_', ' ')}.",
            duration=15.0
        )
        await asyncio.sleep(0.2)

    print("All edge-center windows displayed!")
    print("Should form a cross pattern around the center.")

    await asyncio.sleep(5)
    await cleanup_groups(client, groups)
    print("[OK] Test 6 complete\n")


async def test_stacking_at_edge_centers(session):
    """Test that edge-center anchors also support stacking."""
    print("\n" + "=" * 70)
    print("TEST 7: Stacking at Edge-Center Anchors")
    print("=" * 70)

    client = session._client
    groups = []

    # Stack 3 windows at left_center
    print("Stacking 3 windows at LEFT_CENTER...")

    for i, (priority, color) in enumerate([(30, HudColor.ERROR), (20, HudColor.SUCCESS), (10, HudColor.INFO)]):
        name = f"left_stack_{i}"
        groups.append(name)

        props = MessageProps(
            anchor=Anchor.LEFT_CENTER.value,
            priority=priority,
            layout_mode=LayoutMode.AUTO.value,
            width=280,
            accent_color=_get_value(color),
        )
        await client.create_group(name, WindowType.MESSAGE, props=props)

        await client.show_message(
            name,
            WindowType.MESSAGE,
            title=f"Left Stack (P:{priority})",
            content=f"Priority: {priority}\nVertically centered stack.",
            duration=20.0
        )
        await asyncio.sleep(0.2)

    # Stack 2 windows at right_center
    print("Stacking 2 windows at RIGHT_CENTER...")

    for i, (priority, color) in enumerate([(25, HudColor.ACCENT_ORANGE), (15, HudColor.ACCENT_PURPLE)]):
        name = f"right_stack_{i}"
        groups.append(name)

        props = MessageProps(
            anchor=Anchor.RIGHT_CENTER.value,
            priority=priority,
            layout_mode=LayoutMode.AUTO.value,
            width=280,
            accent_color=_get_value(color),
        )
        await client.create_group(name, WindowType.MESSAGE, props=props)

        await client.show_message(
            name,
            WindowType.MESSAGE,
            title=f"Right Stack (P:{priority})",
            content=f"Priority: {priority}\nMirrored stack on right.",
            duration=20.0
        )
        await asyncio.sleep(0.2)

    print("Both side stacks visible - should be vertically centered!")

    await asyncio.sleep(5)
    await cleanup_groups(client, groups)
    print("[OK] Test 7 complete\n")


async def test_mixed_content_with_progress(session):
    """Test layout with mixed content types including progress bars."""
    print("\n" + "=" * 70)
    print("TEST 8: Mixed Content Types (Messages + Progress)")
    print("=" * 70)

    client = session._client
    groups = ["msg_group", "progress_group"]

    # Message window at top
    msg_props = MessageProps(
        anchor=Anchor.TOP_LEFT.value,
        priority=20,
        layout_mode=LayoutMode.AUTO.value,
        width=400,
        accent_color=HudColor.ACCENT_BLUE.value,
    )
    await client.create_group("msg_group", WindowType.MESSAGE, props=msg_props)

    await client.show_message(
        "msg_group",
        WindowType.MESSAGE,
        title="System Status",
        content="Active operations are displayed below.\n\nProgress bars update in real-time.",
        duration=30.0
    )

    # Progress window below
    progress_props = MessageProps(
        anchor=Anchor.TOP_LEFT.value,
        priority=10,
        layout_mode=LayoutMode.AUTO.value,
        width=380,
        accent_color=HudColor.ACCENT_ORANGE.value,
    )
    await client.create_group("progress_group", WindowType.MESSAGE, props=progress_props)

    # Add progress bar
    await client.show_progress(
        "progress_group",
        WindowType.MESSAGE,
        title="Download Progress",
        current=0,
        maximum=100,
        description="Starting download..."
    )

    print("Message and progress bar displayed")
    print("Animating progress...")

    # Animate progress
    for i in range(0, 101, 5):
        await client.show_progress(
            "progress_group",
            WindowType.MESSAGE,
            title="Download Progress",
            current=i,
            maximum=100,
            description=f"Downloading... {i}%"
        )
        await asyncio.sleep(0.15)

    print("Progress complete!")
    await asyncio.sleep(2)

    await cleanup_groups(client, groups)
    await client.remove_item("progress_group", WindowType.MESSAGE, "Download Progress")
    print("[OK] Test 8 complete\n")


async def test_rapid_show_hide(session):
    """Stress test with rapid show/hide cycles."""
    print("\n" + "=" * 70)
    print("TEST 9: Rapid Show/Hide Stress Test")
    print("=" * 70)

    client = session._client
    groups = ["rapid_1", "rapid_2", "rapid_3"]
    colors = [HudColor.RED, HudColor.GREEN, HudColor.BLUE]

    for i, name in enumerate(groups):
        props = MessageProps(
            anchor=Anchor.TOP_LEFT.value,
            priority=30 - (i * 10),
            layout_mode=LayoutMode.AUTO.value,
            width=350,
            accent_color=colors[i].value,
        )
        await client.create_group(name, WindowType.MESSAGE, props=props)

    print("Performing 5 rapid show/hide cycles...")

    for cycle in range(5):
        print(f"  Cycle {cycle + 1}/5")

        # Show all
        for name in groups:
            await client.show_message(name, WindowType.MESSAGE, title=f"Window {name}", content=f"Cycle {cycle + 1}", duration=10.0)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)

        # Hide middle
        await client.hide_message("rapid_2", WindowType.MESSAGE)
        await asyncio.sleep(0.3)

        # Show middle
        await client.show_message("rapid_2", WindowType.MESSAGE, title="Window rapid_2", content=f"Back! Cycle {cycle + 1}", duration=10.0)
        await asyncio.sleep(0.3)

        # Hide first
        await client.hide_message("rapid_1", WindowType.MESSAGE)
        await asyncio.sleep(0.3)

        # Show first
        await client.show_message("rapid_1", WindowType.MESSAGE, title="Window rapid_1", content=f"Back! Cycle {cycle + 1}", duration=10.0)
        await asyncio.sleep(0.2)

    print("Stress test complete - checking final state...")
    await asyncio.sleep(2)

    await cleanup_groups(client, groups)
    print("[OK] Test 9 complete\n")


async def run_all_layout_visual_tests(session):
    """Run all visual layout tests."""
    print("\n" + "=" * 70)
    print("  SOPHISTICATED VISUAL LAYOUT INTEGRATION TEST SUITE")
    print("  Testing all 9 anchor points and complex scenarios")
    print("=" * 70)
    print("\nThis test will display HUD windows on your screen.")
    print("Watch for correct positioning and stacking behavior.\n")
    print("Press Ctrl+C to abort at any time.\n")

    await asyncio.sleep(2)

    try:
        await test_all_nine_anchors(session)
        await test_priority_stacking(session)
        await test_dynamic_height_changes(session)
        await test_visibility_reflow(session)
        await test_opposite_anchors(session)
        await test_center_anchors(session)
        await test_stacking_at_edge_centers(session)
        await test_mixed_content_with_progress(session)
        await test_rapid_show_hide(session)

        print("\n" + "=" * 70)
        print("  ALL 9 VISUAL LAYOUT TESTS COMPLETE!")
        print("=" * 70)
        print("\nSummary:")
        print("  [OK] Test 1: All 9 anchor positions")
        print("  [OK] Test 2: Priority-based stacking")
        print("  [OK] Test 3: Dynamic height changes")
        print("  [OK] Test 4: Visibility changes & reflow")
        print("  [OK] Test 5: Opposite corners (diagonal)")
        print("  [OK] Test 6: Center and edge-center anchors")
        print("  [OK] Test 7: Stacking at edge-centers")
        print("  [OK] Test 8: Mixed content types")
        print("  [OK] Test 9: Rapid show/hide stress test")
        print("\nIf windows positioned correctly without overlapping,")
        print("the layout manager is working properly!")

    except KeyboardInterrupt:
        print("\n\nTest aborted by user.")


async def main():
    """Main entry point."""
    print("Starting Sophisticated Visual Layout Integration Tests...")
    print("The HUD overlay will appear on your screen.\n")

    async with TestContext(session_ids=[1]) as ctx:
        session = ctx.sessions[0]
        await run_all_layout_visual_tests(session)

    print("\nTests complete. Server stopped.")


if __name__ == "__main__":
    asyncio.run(main())
