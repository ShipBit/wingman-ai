"""Pictures: in messages, the chat and the info panel; files, data URIs, the web."""

from hud_server.tests.harness import CHAT, INFO, MESSAGE, PHOTO, STYLE, WIDE_IMAGE, Demo, area
from hud_server.types import WindowType

TITLE = "Pictures"
M, C, P = WindowType.MESSAGE, WindowType.CHAT, WindowType.PERSISTENT
WEB_IMAGE = "https://www.python.org/static/community_logos/python-logo-generic.svg"
WEB_PNG = "https://www.python.org/static/img/python-logo.png"


def path(file: str) -> str:
    # Forward slashes: a backslash in Markdown escapes the next character
    return file.replace("\\", "/")


async def run(demo: Demo) -> None:
    client = demo.client
    await client.create_group(MESSAGE, M, {**STYLE, **area(40, 40, 600, 900)})
    await client.create_group(CHAT, C, {**STYLE, **area(660, 40, 1180, 900, "bottom")})
    await client.create_group(INFO, P, {**STYLE, **area(1240, 40, 1760, 900)})
    orionis = demo.picture("Orionis", "#d84f4f")

    demo.scene("Files", "a wide picture scaled to the window, a photo, both kept in proportion")
    await client.show_message(MESSAGE, M, "Orionis", f"The station:\n\n![wide]({path(WIDE_IMAGE)})\n\n"
                              f"And from the pad:\n\n![photo]({path(PHOTO)})", title_icon=orionis, duration=60)
    await demo.pause(5)

    demo.scene("A data URI, as a tool hands back a screenshot")
    await client.show_message(MESSAGE, M, "Orionis", f"Scan result:\n\n![scan]({demo.data_uri(PHOTO, 320, photo=True)})",
                              title_icon=orionis, duration=60)
    await demo.pause(4)

    demo.scene("A picture that is not there", "its description shows instead, nothing breaks")
    await client.show_message(MESSAGE, M, "Orionis", "![the missing map](C:/nowhere/map.png)\n\nThe text goes on.",
                              title_icon=orionis, duration=60)
    await demo.pause(3)

    if demo.web:
        demo.scene("From the web", "downloads beside the HUD, shows once it arrived")
        await client.show_message(MESSAGE, M, "Orionis", f"From the web:\n\n![python]({WEB_PNG})\n\n"
                                  f"An SVG cannot be drawn: ![svg]({WEB_IMAGE})", title_icon=orionis, duration=60)
        await demo.pause(5)

    demo.scene("Pictures of people and tools", "round avatars in the chat, icons in the tool chips")
    await client.send_chat_message(CHAT, C, "Jay", "Show me the target.", own=True)
    await client.send_chat_message(CHAT, C, "Orionis", "", icon=orionis, tools=[
        {"name": "scan", "source": "Scanner", "icon": demo.icon("Scanner", "#22c55e")},
        {"name": "lookup", "source": "UEX Corp", "icon": demo.icon("UEX", "#f59e0b")},
    ])
    await client.send_chat_message(CHAT, C, "Orionis", f"Target acquired:\n\n![target]({demo.data_uri(PHOTO, 200, photo=True)})",
                                   icon=orionis)
    await client.send_chat_message(CHAT, C, "Jay", f"Like this one? ![mine]({demo.data_uri(orionis, 64)})", own=True)
    await demo.pause(5)

    demo.scene("A picture on the info panel", "and a person's picture beside a panel's title")
    await client.add_item(INFO, P, "Wanted", f"![bounty]({path(PHOTO)})\n\n**Reward:** 25,000 aUEC")
    await client.add_item(INFO, P, "Orionis", "Port Tressler · docking bay 3\nHas a job for you.", icon=orionis)
    await demo.pause(4)
