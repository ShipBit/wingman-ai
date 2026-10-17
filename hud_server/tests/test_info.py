"""The info panel: what Wingmen and skills pin on the HUD."""

from hud_server.tests.harness import INFO, STYLE, Demo, area
from hud_server.types import WindowType

TITLE = "Info panel"
P = WindowType.PERSISTENT

MANIFEST = """| Commodity | SCU | Value |
|---|---|---|
| Quantanium | 32 | 284,000 |
| Laranite | 12 | 33,600 |
| Agricium | 6 | 15,300 |"""


async def run(demo: Demo) -> None:
    client = demo.client
    await client.create_group(INFO, P, {**STYLE, **area(1360, 40, 1880, 1040)})

    demo.scene("Panels", "an icon per kind, the title, details below with a table; a fine line between items")
    await client.add_item(INFO, P, "Cargo Manifest", MANIFEST, added_by="Orionis")
    await demo.pause(1.5)
    await client.add_item(INFO, P, "Mission", "**Deliver** the cargo to *Port Olisar*.\n\n- Avoid Yela's belt\n- Dock at pad 2",
                          added_by="Nova")
    await demo.pause(3)

    demo.scene("Countdowns", "time left as a clock on the right, a slim glowing bar")
    await client.show_timer(INFO, P, "Quantum Spool", 25, auto_close=False)
    await client.show_timer(INFO, P, "Refuel", 60, description="Started a while ago", initial_progress=40,
                            auto_close=False)
    await client.show_timer(INFO, P, "Short Countdown", 4, description="Closes itself at zero")
    await demo.pause(7)

    demo.scene("Progress", "the bar eases to each new value; the percentage sits right of the title")
    for value in range(0, 101, 20):
        await client.show_progress(INFO, P, "Refinery Job", value, 100,
                                   description=f"Processing Quantanium, step {value // 20 + 1} of 6")
        await demo.pause(1)
    await client.show_progress(INFO, P, "Shields", 35, 100, color="#3b82f6")
    await client.show_progress(INFO, P, "Download", 40, 100, auto_close=True)
    await demo.pause(1)
    await client.show_progress(INFO, P, "Download", 100, 100, auto_close=True)
    await demo.pause(4)

    demo.scene("Updated in place, and an item that expires", "the mission text changes; 'Expires' leaves after 3 s")
    await client.update_item(INFO, P, "Mission", description="**Delivered.** Payment received: *333,000 aUEC*.")
    await client.add_item(INFO, P, "Expires", "Gone in three seconds.", duration=3)
    await demo.pause(5)

    demo.scene("Removed one by one")
    for title in ("Cargo Manifest", "Shields", "Refinery Job"):
        demo.check(await client.remove_item(INFO, P, title), f"remove {title}")
        await demo.pause(1)

    demo.scene("A full panel", "the newest at the bottom, the oldest fade out at the top")
    for i in range(1, 15):
        await client.add_item(INFO, P, f"Contact {i:02d}", f"Bearing {i * 23 % 360}°, {i * 1.7:.1f} km.")
        await demo.pause(0.25)
    await demo.pause(3)

    demo.scene("Cleared", "the panel empties and fades out")
    demo.check(await client.clear_items(INFO, P), "clear")
    await demo.pause(2)
