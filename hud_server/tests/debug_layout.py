"""
Debug test to trace layout manager behavior with show/hide cycles.
"""
import sys
import asyncio

sys.path.insert(0, ".")

from hud_server.tests.test_runner import TestContext
from hud_server.types import Anchor, LayoutMode, HudColor, MessageProps, WindowType


async def debug_layout_test(session):
    """Debug test showing layout manager state during show/hide."""
    print("\n" + "=" * 70)
    print("DEBUG: Layout Manager Show/Hide Trace")
    print("=" * 70)

    client = session._client

    # Create three groups with different priorities
    groups_config = [
        ("debug_red", 30, HudColor.RED, "RED - Priority 30"),
        ("debug_green", 20, HudColor.GREEN, "GREEN - Priority 20"),
        ("debug_blue", 10, HudColor.BLUE, "BLUE - Priority 10"),
    ]

    print("\n1. Creating groups...")
    for name, priority, color, label in groups_config:
        props = MessageProps(
            anchor=Anchor.TOP_LEFT.value,
            priority=priority,
            layout_mode=LayoutMode.AUTO.value,
            width=400,
            accent_color=color.value,
        )
        await client.create_group(name, WindowType.MESSAGE, props=props)
        print(f"   Created: {name} (priority={priority})")

    await asyncio.sleep(0.5)

    print("\n2. Showing all three messages...")
    for name, priority, color, label in groups_config:
        await client.show_message(name, WindowType.MESSAGE, title=label, content=f"Priority: {priority}", duration=60.0)
        print(f"   Shown: {name}")
        await asyncio.sleep(0.2)

    print("\n   Expected stack (top to bottom): RED, GREEN, BLUE")
    print("   Waiting 3 seconds - verify visually...")
    await asyncio.sleep(3)

    print("\n3. HIDING GREEN (middle)...")
    await client.hide_message("debug_green", WindowType.MESSAGE)
    print("   Expected stack: RED, BLUE (GREEN hidden)")
    print("   BLUE should move UP to where GREEN was")
    print("   Waiting 3 seconds - verify visually...")
    await asyncio.sleep(3)

    print("\n4. SHOWING GREEN again...")
    await client.show_message("debug_green", WindowType.MESSAGE, title="GREEN - BACK!", content="I should be in the MIDDLE!", duration=60.0)
    print("   Expected stack: RED, GREEN, BLUE")
    print("   GREEN should appear BETWEEN RED and BLUE")
    print("   BLUE should move DOWN")
    print("   Waiting 5 seconds - verify visually...")
    await asyncio.sleep(5)

    print("\n5. Cleanup...")
    for name, _, _, _ in groups_config:
        await client.hide_message(name, WindowType.MESSAGE)

    await asyncio.sleep(1)
    print("\n[DONE] Check the console output above and visual behavior")


async def main():
    print("Debug Layout Test - Tracing show/hide behavior\n")

    async with TestContext(session_ids=[1]) as ctx:
        session = ctx.sessions[0]
        await debug_layout_test(session)

    print("\nTest complete.")


if __name__ == "__main__":
    asyncio.run(main())
