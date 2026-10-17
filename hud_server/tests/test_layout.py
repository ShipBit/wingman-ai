"""Where windows go: anchors, stacking, areas and their align, live moves,
collisions and hidden elements. The layout manager's own checks are in
tests/hud/test_layout_stacking.py and tests/hud/test_layout_area.py."""

from hud_server.tests.harness import STYLE, Demo, area
from hud_server.types import WindowType

TITLE = "Layout"
M, P = WindowType.MESSAGE, WindowType.PERSISTENT

ANCHORS = ["top_left", "top_center", "top_right", "left_center", "center", "right_center",
           "bottom_left", "bottom_center", "bottom_right"]


async def run(demo: Demo) -> None:
    client = demo.client

    demo.scene("Nine anchors", "one window at every corner, edge and the centre")
    for anchor in ANCHORS:
        await client.show_message(f"demo_anchor_{anchor}", M, anchor.replace("_", " ").title(), f"`{anchor}`",
                                  props={**STYLE, "anchor": anchor, "layout_mode": "auto", "width": 300,
                                         "typewriter_effect": False}, duration=60)
    await demo.pause(5)
    for anchor in ANCHORS:
        await client.delete_group(f"demo_anchor_{anchor}", M)

    demo.scene("Stacking by priority", "three windows at the top left, the highest priority nearest the corner")
    stack = {"demo_stack_high": 30, "demo_stack_mid": 20, "demo_stack_low": 10}
    for group, priority in stack.items():
        await client.show_message(group, M, f"Priority {priority}", "Stacked by priority.", duration=60,
                                  props={**STYLE, "anchor": "top_left", "priority": priority, "width": 380,
                                         "typewriter_effect": False})
    await demo.pause(3)

    demo.scene("The stack follows", "the top window grows, the others move down; the middle one leaves, the gap closes")
    for line in range(4):
        await client.append_message("demo_stack_high", M, f"\n\nOne more line ({line + 1}).")
        await demo.pause(0.6)
    await demo.pause(1.5)
    await client.hide_message("demo_stack_mid", M)
    await demo.pause(3)
    for group in stack:
        await client.delete_group(group, M)

    demo.scene("Areas and their align", "three areas: content at the top, in the middle, at the bottom of each")
    for i, align in enumerate(("top", "center", "bottom")):
        await client.create_group(f"demo_area_{align}", M, {**STYLE, **area(60 + i * 460, 120, 480 + i * 460, 820, align),
                                                             "typewriter_effect": False})
    for lines in range(1, 7):
        for align in ("top", "center", "bottom"):
            text = "\n\n".join(f"Line {n}" for n in range(1, lines + 1))
            await client.show_message(f"demo_area_{align}", M, f"align: {align}", text, duration=60)
        await demo.pause(0.8)
    await demo.pause(2)

    demo.scene("Moved and resized live", "the window glides to new places and sizes")
    group = "demo_area_center"
    for x, y, width in ((700, 200, 420), (900, 300, 560), (500, 420, 340), (520, 120, 420)):
        demo.check(await client.update_group(group, M, {"x": x, "y": y, "width": width}), "update_group")
        await demo.pause(1)
    for align in ("top", "center", "bottom"):
        await client.delete_group(f"demo_area_{align}", M)

    demo.scene("A message covers its own info panel", "the panel fades while the answer covers it, then comes back")
    pilot = "demo_pilot"
    await client.create_group(pilot, P, {**STYLE, **area(60, 120, 520, 520)})
    await client.create_group(pilot, M, {**STYLE, **area(60, 160, 520, 600)})
    await client.add_item(pilot, P, "Patrol", "Waypoint 3 of 5.")
    await client.show_timer(pilot, P, "Next waypoint", 30, auto_close=False)
    await demo.pause(2.5)
    await client.show_message(pilot, M, "Orionis", "Contact! Two bandits at 2 o'clock.", duration=3)
    await demo.pause(6)

    demo.scene("Hidden, still running", "the panel hides, its timer keeps counting; shown again, time has passed")
    demo.check(await client.hide_element(pilot, P), "hide_element")
    await demo.pause(3)
    demo.check(await client.show_element(pilot, P), "show_element")
    await demo.pause(3)
    await client.delete_group(pilot, P)
    await client.delete_group(pilot, M)

    demo.scene("Groups coming and going quickly", "no flicker, no leftovers")
    for round_ in range(3):
        for i in range(4):
            await client.show_message(f"demo_quick_{i}", M, f"Quick {i}", f"Round {round_ + 1}", duration=60,
                                      props={**STYLE, "anchor": "bottom_right", "priority": i, "width": 260,
                                             "typewriter_effect": False})
        await demo.pause(0.6)
        for i in range(4):
            await client.delete_group(f"demo_quick_{i}", M)
        await demo.pause(0.3)
