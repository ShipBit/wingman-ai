"""The server's own settings, changed while it runs: frame rate, the margin to
the screen's edges, the spacing of stacked windows, the monitor. Only on a
server this run started: Core's settings are left alone."""

import httpx

from hud_server import constants as hud_const
from hud_server.tests.harness import STYLE, Demo
from hud_server.types import WindowType

TITLE = "Server settings"
M = WindowType.MESSAGE
STACK = ("demo_settings_a", "demo_settings_b", "demo_settings_c")


async def update(demo: Demo, **settings) -> None:
    """POST /settings/update takes the settings as query parameters."""
    client = demo.client._client
    if client is None:
        demo.fail("settings: not connected")
        return
    try:
        await client.post("/settings/update", params=settings)  # a refusal is recorded by the demo's client
    except httpx.HTTPError as e:
        demo.fail(f"settings {settings}: {e}")


async def run(demo: Demo) -> None:
    if not demo.own_server:
        print("\n-- Skipped: these change the settings of a HUD server this run did not start (Core's).")
        return

    client = demo.client
    for i, group in enumerate(STACK):
        await client.show_message(group, M, f"Window {i + 1}", "Stacked at the top left.", duration=120,
                                  props={**STYLE, "anchor": "top_left", "priority": 30 - i, "width": 360,
                                         "typewriter_effect": False})
    await client.show_loader(STACK[0], M, True)

    demo.scene("Frame rate", "the loader's glow breathes at 10, then 120 frames a second")
    for framerate in (10, 120, hud_const.DEFAULT_FRAMERATE):
        await update(demo, framerate=framerate)
        await demo.pause(2.5)

    demo.scene("Margin to the screen's edges", "the stack moves away from the corner and back")
    for margin in (80, 5, hud_const.DEFAULT_LAYOUT_MARGIN):
        await update(demo, layout_margin=margin)
        await demo.pause(2)

    demo.scene("Spacing between stacked windows")
    for spacing in (60, 0, hud_const.DEFAULT_LAYOUT_SPACING):
        await update(demo, layout_spacing=spacing)
        await demo.pause(2)

    demo.scene("Another monitor", "with a second monitor the stack moves there and back; with one it stays")
    await update(demo, screen=2)
    await demo.pause(3)
    await update(demo, screen=demo.screen)
    await demo.pause(2)

    demo.scene("Everything at once, the content stays")
    await update(demo, framerate=45, layout_margin=30, layout_spacing=25)
    await demo.pause(2)
    await update(demo, framerate=hud_const.DEFAULT_FRAMERATE, layout_margin=hud_const.DEFAULT_LAYOUT_MARGIN,
                 layout_spacing=hud_const.DEFAULT_LAYOUT_SPACING)
    await client.show_loader(STACK[0], M, False)
    await demo.pause(2)
    for group in STACK:
        await client.delete_group(group, M)
