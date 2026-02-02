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


# =============================================================================
# ANCHOR CONFIGURATION - All 9 anchor points
# =============================================================================

ANCHOR_CONFIG = {
    "top_left": {
        "label": "TOP LEFT",
        "color": "#ff5555",
        "emoji_fallback": "[TL]",
    },
    "top_center": {
        "label": "TOP CENTER",
        "color": "#ffaa00",
        "emoji_fallback": "[TC]",
    },
    "top_right": {
        "label": "TOP RIGHT",
        "color": "#55ff55",
        "emoji_fallback": "[TR]",
    },
    "right_center": {
        "label": "RIGHT CENTER",
        "color": "#55ffff",
        "emoji_fallback": "[RC]",
    },
    "bottom_right": {
        "label": "BOTTOM RIGHT",
        "color": "#5555ff",
        "emoji_fallback": "[BR]",
    },
    "bottom_center": {
        "label": "BOTTOM CENTER",
        "color": "#ff55ff",
        "emoji_fallback": "[BC]",
    },
    "bottom_left": {
        "label": "BOTTOM LEFT",
        "color": "#ffff55",
        "emoji_fallback": "[BL]",
    },
    "left_center": {
        "label": "LEFT CENTER",
        "color": "#ff8855",
        "emoji_fallback": "[LC]",
    },
    "center": {
        "label": "CENTER",
        "color": "#ffffff",
        "emoji_fallback": "[C]",
    },
}


async def cleanup_groups(client, group_names):
    """Helper to clean up groups."""
    for name in group_names:
        try:
            await client.hide_message(name)
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
        group_name = f"anchor_{anchor}"
        groups.append(group_name)

        await client.create_group(group_name, props={
            "anchor": anchor,
            "priority": 10,
            "layout_mode": "auto",
            "margin": 25,
            "spacing": 10,
            "width": 280,
            "accent_color": config["color"],
        })

        await client.show_message(
            group_name,
            title=f"{config['emoji_fallback']} {config['label']}",
            content=f"Anchor: **{anchor}**\n\nThis window is positioned at the {config['label'].lower()} of the screen.",
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
        ("stack_high", 30, "#ff3333", "HIGH Priority (30)"),
        ("stack_med", 20, "#33ff33", "MEDIUM Priority (20)"),
        ("stack_low", 10, "#3333ff", "LOW Priority (10)"),
    ]

    print("Creating 3 windows at TOP_LEFT with different priorities...")

    for name, priority, color, label in priorities:
        groups.append(name)
        await client.create_group(name, props={
            "anchor": "top_left",
            "priority": priority,
            "layout_mode": "auto",
            "margin": 20,
            "spacing": 12,
            "width": 380,
            "accent_color": color,
        })

        await client.show_message(
            name,
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

    for name, priority, color in [("right_a", 25, "#ff9900"), ("right_b", 15, "#9900ff")]:
        groups.append(name)
        await client.create_group(name, props={
            "anchor": "top_right",
            "priority": priority,
            "layout_mode": "auto",
            "margin": 20,
            "spacing": 12,
            "width": 320,
            "accent_color": color,
        })

        await client.show_message(
            name,
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
    await client.create_group("dyn_top", props={
        "anchor": "top_left",
        "priority": 20,
        "layout_mode": "auto",
        "margin": 20,
        "spacing": 15,
        "width": 420,
        "accent_color": "#ff6600",
    })

    await client.create_group("dyn_bottom", props={
        "anchor": "top_left",
        "priority": 10,
        "layout_mode": "auto",
        "margin": 20,
        "spacing": 15,
        "width": 420,
        "accent_color": "#0066ff",
    })

    # Phase 1: Short top window
    print("Phase 1: Top window is SHORT")
    await client.show_message(
        "dyn_top",
        title="Top Window - SHORT",
        content="This is a short message.",
        duration=30.0
    )
    await asyncio.sleep(0.3)

    await client.show_message(
        "dyn_bottom",
        title="Bottom Window",
        content="Watch me move as the top window changes height!",
        duration=30.0
    )
    await asyncio.sleep(3)

    # Phase 2: Tall top window
    print("Phase 2: Top window GROWS - bottom should move DOWN")
    await client.show_message(
        "dyn_top",
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
        title="Top Window - SHORT again",
        content="Shrunk back down.",
        duration=20.0
    )
    await asyncio.sleep(3)

    # Phase 4: Medium height
    print("Phase 4: Top window MEDIUM height")
    await client.show_message(
        "dyn_top",
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

    colors = ["#ff0000", "#00ff00", "#0000ff"]
    labels = ["First (Red)", "Second (Green)", "Third (Blue)"]

    for i, (name, color, label) in enumerate(zip(groups, colors, labels)):
        await client.create_group(name, props={
            "anchor": "top_left",
            "priority": 30 - (i * 10),
            "layout_mode": "auto",
            "margin": 20,
            "spacing": 12,
            "width": 380,
            "accent_color": color,
        })

    # Show all three
    print("Phase 1: All 3 windows visible")
    for name, label in zip(groups, labels):
        await client.show_message(name, title=label, content=f"Window: {label}", duration=30.0)
        await asyncio.sleep(0.2)
    await asyncio.sleep(3)

    # Hide middle (green)
    print("Phase 2: HIDING middle (Green) - Blue should move UP")
    await client.hide_message("vis_2")
    await asyncio.sleep(3)

    # Show middle again
    print("Phase 3: SHOWING middle (Green) - Blue should move DOWN")
    await client.show_message("vis_2", title="Second (Green) - BACK!", content="I'm back in the stack!", duration=20.0)
    await asyncio.sleep(3)

    # Hide first (red)
    print("Phase 4: HIDING first (Red) - Both should move UP")
    await client.hide_message("vis_1")
    await asyncio.sleep(3)

    # Hide all except blue
    print("Phase 5: Only Blue remains")
    await client.hide_message("vis_2")
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
        ("diag_tl", "top_left", "#ff0000", "TOP-LEFT Corner"),
        ("diag_br", "bottom_right", "#00ff00", "BOTTOM-RIGHT Corner"),
        ("diag_tr", "top_right", "#0000ff", "TOP-RIGHT Corner"),
        ("diag_bl", "bottom_left", "#ffff00", "BOTTOM-LEFT Corner"),
    ]

    print("Creating windows at all 4 corners...")

    for name, anchor, color, label in pairs:
        groups.append(name)
        await client.create_group(name, props={
            "anchor": anchor,
            "priority": 10,
            "layout_mode": "auto",
            "margin": 20,
            "width": 320,
            "accent_color": color,
        })

        await client.show_message(
            name,
            title=label,
            content=f"Anchor: **{anchor}**\n\nDiagonal positioning test.",
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
    await client.create_group("center_main", props={
        "anchor": "center",
        "priority": 10,
        "layout_mode": "auto",
        "width": 350,
        "accent_color": "#ffffff",
    })

    await client.show_message(
        "center_main",
        title="CENTER",
        content="This window is in the absolute center of the screen.",
        duration=20.0
    )

    print("Center window displayed")
    await asyncio.sleep(2)

    # Add edge centers
    edge_centers = [
        ("edge_top", "top_center", "#ff9900", "TOP CENTER EDGE"),
        ("edge_bottom", "bottom_center", "#9900ff", "BOTTOM CENTER EDGE"),
        ("edge_left", "left_center", "#00ff99", "LEFT CENTER EDGE"),
        ("edge_right", "right_center", "#ff0099", "RIGHT CENTER EDGE"),
    ]

    print("Adding edge-center windows...")

    for name, anchor, color, label in edge_centers:
        groups.append(name)
        await client.create_group(name, props={
            "anchor": anchor,
            "priority": 10,
            "layout_mode": "auto",
            "margin": 20,
            "width": 260,
            "accent_color": color,
        })

        await client.show_message(
            name,
            title=label,
            content=f"Positioned at the {anchor.replace('_', ' ')}.",
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

    for i, (priority, color) in enumerate([(30, "#ff5555"), (20, "#55ff55"), (10, "#5555ff")]):
        name = f"left_stack_{i}"
        groups.append(name)

        await client.create_group(name, props={
            "anchor": "left_center",
            "priority": priority,
            "layout_mode": "auto",
            "margin": 20,
            "spacing": 10,
            "width": 280,
            "accent_color": color,
        })

        await client.show_message(
            name,
            title=f"Left Stack (P:{priority})",
            content=f"Priority: {priority}\nVertically centered stack.",
            duration=20.0
        )
        await asyncio.sleep(0.2)

    # Stack 2 windows at right_center
    print("Stacking 2 windows at RIGHT_CENTER...")

    for i, (priority, color) in enumerate([(25, "#ff9900"), (15, "#9900ff")]):
        name = f"right_stack_{i}"
        groups.append(name)

        await client.create_group(name, props={
            "anchor": "right_center",
            "priority": priority,
            "layout_mode": "auto",
            "margin": 20,
            "spacing": 10,
            "width": 280,
            "accent_color": color,
        })

        await client.show_message(
            name,
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
    await client.create_group("msg_group", props={
        "anchor": "top_left",
        "priority": 20,
        "layout_mode": "auto",
        "margin": 20,
        "spacing": 15,
        "width": 400,
        "accent_color": "#00aaff",
    })

    await client.show_message(
        "msg_group",
        title="System Status",
        content="Active operations are displayed below.\n\nProgress bars update in real-time.",
        duration=30.0
    )

    # Progress window below
    await client.create_group("progress_group", props={
        "anchor": "top_left",
        "priority": 10,
        "layout_mode": "auto",
        "margin": 20,
        "spacing": 15,
        "width": 380,
        "accent_color": "#ffaa00",
    })

    # Add progress bar
    await client.show_progress(
        "progress_group",
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
            title="Download Progress",
            current=i,
            maximum=100,
            description=f"Downloading... {i}%"
        )
        await asyncio.sleep(0.15)

    print("Progress complete!")
    await asyncio.sleep(2)

    await cleanup_groups(client, groups)
    await client.remove_item("progress_group", "Download Progress")
    print("[OK] Test 8 complete\n")


async def test_rapid_show_hide(session):
    """Stress test with rapid show/hide cycles."""
    print("\n" + "=" * 70)
    print("TEST 9: Rapid Show/Hide Stress Test")
    print("=" * 70)

    client = session._client
    groups = ["rapid_1", "rapid_2", "rapid_3"]

    for i, name in enumerate(groups):
        await client.create_group(name, props={
            "anchor": "top_left",
            "priority": 30 - (i * 10),
            "layout_mode": "auto",
            "margin": 20,
            "spacing": 10,
            "width": 350,
            "accent_color": ["#ff0000", "#00ff00", "#0000ff"][i],
        })

    print("Performing 5 rapid show/hide cycles...")

    for cycle in range(5):
        print(f"  Cycle {cycle + 1}/5")

        # Show all
        for name in groups:
            await client.show_message(name, title=f"Window {name}", content=f"Cycle {cycle + 1}", duration=10.0)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)

        # Hide middle
        await client.hide_message("rapid_2")
        await asyncio.sleep(0.3)

        # Show middle
        await client.show_message("rapid_2", title="Window rapid_2", content=f"Back! Cycle {cycle + 1}", duration=10.0)
        await asyncio.sleep(0.3)

        # Hide first
        await client.hide_message("rapid_1")
        await asyncio.sleep(0.3)

        # Show first
        await client.show_message("rapid_1", title="Window rapid_1", content=f"Back! Cycle {cycle + 1}", duration=10.0)
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
