"""Several clients at once, as several apps (or Wingmen) use one HUD server:
each with its own windows and look, all writing into one shared chat."""

import asyncio

from hud_server.tests.harness import STYLE, Demo, area
from hud_server.types import WindowType

TITLE = "Several clients"
M, C, P = WindowType.MESSAGE, WindowType.CHAT, WindowType.PERSISTENT
SHARED_CHAT = "demo_shared_chat"

PILOTS = {
    "Atlas": {"accent_color": "#3b82f6", "anchor": "top_left"},
    "Nova": {"accent_color": "#f59e0b", "anchor": "top_right"},
    "Orion": {"accent_color": "#a855f7", "anchor": "bottom_left"},
}


async def pilot(demo: Demo, name: str, look: dict) -> None:
    """One client's session: its own message window and info panel."""
    client = demo.new_client()
    if not await client.connect():
        demo.fail(f"{name} could not connect")
        return
    try:
        group = f"demo_{name.lower()}"
        style = {**STYLE, "accent_color": look["accent_color"], "layout_mode": "auto", "width": 360,
                 "typewriter_effect": False}
        await client.create_group(group, M, {**style, "anchor": look["anchor"], "priority": 20})
        await client.create_group(group, P, {**style, "anchor": look["anchor"], "priority": 10})
        picture = demo.picture(name, look["accent_color"])
        for step in range(1, 6):
            await client.show_message(group, M, name, f"Step {step} of 5: working on my own windows.",
                                      title_icon=picture, duration=60)
            await client.show_progress(group, P, f"{name}'s job", step * 20, 100)
            await client.send_chat_message(SHARED_CHAT, C, name, f"{name}, step {step}.", icon=picture,
                                           color=look["accent_color"])
            await demo.pause(0.8)
    finally:
        await client.disconnect()


async def run(demo: Demo) -> None:
    await demo.client.create_group(SHARED_CHAT, C, {**STYLE, **area(700, 140, 1220, 900, "bottom"),
                                                    "typewriter_effect": False})

    demo.scene("Three clients at the same time",
               "each fills its own corner; the shared chat in the middle gets all three, in arrival order")
    await asyncio.gather(*(pilot(demo, name, look) for name, look in PILOTS.items()))
    await demo.pause(3)

    demo.scene("A client leaves, its windows stay", "the server keeps what it was given until it is removed")
    groups = (await demo.client.get_groups() or {}).get("groups", [])
    demo.check(any("demo_atlas" in str(g) for g in groups), "Atlas's groups are still on the server")
    await demo.pause(2)

    demo.scene("A burst of messages from everyone", "nothing lost, nothing out of order within a sender")
    picture = {name: demo.picture(name, look["accent_color"]) for name, look in PILOTS.items()}

    async def burst(name):
        client = demo.new_client()
        await client.connect()
        try:
            for i in range(1, 6):
                await client.send_chat_message(SHARED_CHAT, C, name, f"{name} #{i}", icon=picture[name],
                                               color=PILOTS[name]["accent_color"])
        finally:
            await client.disconnect()

    await asyncio.gather(*(burst(name) for name in PILOTS))
    await demo.pause(4)
