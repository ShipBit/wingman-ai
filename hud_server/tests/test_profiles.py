"""HUD profiles: the look and areas Core sets as server defaults. Switching
profiles moves and restyles the containers live; what they show stays."""

from hud_server.tests.harness import CHAT, INFO, STYLE, Demo, area
from hud_server.types import WindowType

TITLE = "HUD profiles"
C, P = WindowType.CHAT, WindowType.PERSISTENT

PROFILES = {
    "Default": (
        STYLE,
        {CHAT: area(40, 40, 560, 700, "bottom"), INFO: area(1360, 40, 1880, 700)},
    ),
    "Combat": (
        {**STYLE, "accent_color": "#f59e0b", "bg_color": "#101215f2", "text_color": "#f0f0f0", "font_size": 18,
         "border_radius": 4, "content_padding": 14},
        {CHAT: area(660, 640, 1260, 1040, "bottom"), INFO: area(40, 40, 520, 600, "top")},
    ),
    "Minimal": (
        {**STYLE, "accent_color": "#14b8a6", "bg_color": "#20222766", "font_size": 14, "border_radius": 20,
         "content_padding": 20, "opacity": 0.8},
        {CHAT: area(1300, 300, 1880, 780, "center"), INFO: area(40, 300, 460, 780, "center")},
    ),
}


async def run(demo: Demo) -> None:
    client = demo.client

    async def switch(name):
        props, groups = PROFILES[name]
        demo.check(await client.set_defaults(props, groups), f"set_defaults {name}")
        defaults = await client.get_defaults()
        demo.check(defaults and defaults.get("groups", {}).get(CHAT, {}).get("x") == groups[CHAT]["x"],
                   f"the server keeps profile {name}")

    demo.scene("The containers, as Core creates them", "no props of their own: the defaults decide")
    await switch("Default")
    await client.create_group(CHAT, C)
    await client.create_group(INFO, P)
    orionis = demo.picture("Orionis", "#d84f4f")
    await client.send_chat_message(CHAT, C, "Jay", "Status?", own=True)
    await client.send_chat_message(CHAT, C, "Orionis", "All systems green. Shields at **96 %**.", icon=orionis)
    await client.show_timer(INFO, P, "Quantum Spool", 90, auto_close=False)
    await client.add_item(INFO, P, "Mission", "Deliver the cargo to **Port Olisar**.")
    await demo.pause(4)

    for name in ("Combat", "Minimal", "Default"):
        demo.scene(f"Profile '{name}'", "both containers move and change their look; the conversation stays")
        await switch(name)
        await demo.pause(4)

    demo.scene("A group's own props outrank the profile", "the info panel keeps its green accent through the switches")
    demo.check(await client.update_group(INFO, P, {"accent_color": "#22c55e"}), "update_group")
    await demo.pause(2)
    for name in ("Combat", "Default"):
        await switch(name)
        await demo.pause(2.5)
