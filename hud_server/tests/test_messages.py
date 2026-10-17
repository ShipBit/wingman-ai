"""The message window: one answer at a time, as with the chat flow off."""

from hud_server.tests.harness import MESSAGE, STYLE, Demo, area
from hud_server.types import WindowType

TITLE = "Message window"
M = WindowType.MESSAGE

MARKDOWN = """# Flight plan
**Bold**, *italic*, ***both***, ~~struck~~, `inline code` and a [link](https://wingman-ai.com).

## Checklist
- [x] Pre-flight checks
- [x] Fuel at **100 %**
- [ ] Clearance from ATC
  - Pad assignment
  - Hangar doors

1. Spool the quantum drive
2. Align with the marker
3. Jump

> Stay out of restricted airspace near Lorville.

```python
def eta(distance_gm, speed_gm_s):
    return distance_gm / speed_gm_s
```

| Leg | Distance | ETA |
|---|---|---|
| Hurston to Crusader | 32.5 Gm | 2 min |
| Crusader to ArcCorp | 28.1 Gm | 1 min 40 s |

---
*All systems nominal.*"""

LONG = "\n\n".join(
    f"**Log {i:02d}.** Scanned sector {i}: {['no contacts', 'two asteroids', 'a derelict Hull C', 'an outpost'][i % 4]}."
    for i in range(1, 31)
) + "\n\n**End of log.** The newest part stays in view; the top fades."


async def run(demo: Demo) -> None:
    client = demo.client
    await client.create_group(MESSAGE, M, {**STYLE, **area(40, 40, 560, 640)})
    orionis = demo.picture("Orionis", "#d84f4f")

    demo.scene("A Wingman answers", "picture with a ring, name, a fine accent line, the text typing itself out")
    await client.show_message(MESSAGE, M, "Orionis", "Landing granted on **pad 04**. Hangar doors open in 30 seconds.",
                              title_icon=orionis, duration=60)
    await demo.pause(4)

    demo.scene("Markdown", "headings, lists, checkboxes, a quote, code, a table with a shaded header")
    await client.show_message(MESSAGE, M, "Orionis", MARKDOWN, title_icon=orionis, duration=60)
    await demo.pause(9)

    demo.scene("Streaming", "an answer arriving in chunks keeps typing where it was")
    await client.show_message(MESSAGE, M, "Orionis", "Plotting the route", title_icon=orionis, duration=60)
    for chunk in (" to Port Olisar.", " Two jumps,", " about **3 minutes**.", "\n\nFuel after arrival: 64 %."):
        await demo.pause(0.8)
        await client.append_message(MESSAGE, M, chunk)
    await demo.pause(3)

    demo.scene("Thinking, tools, answer", "the bottom edge glows, then chips: a tool called 3 times shows once with a 3")
    await client.hide_message(MESSAGE, M)
    await client.show_loader(MESSAGE, M, True)
    await demo.pause(2)
    status = {"name": "get_ship_status", "source": "Ship Status", "icon": demo.icon("Ship Status", "#3b82f6")}
    route = {"name": "plot_route", "source": "SC Tools", "icon": None}
    await client.show_message(MESSAGE, M, "Orionis", "Checking the ship.", tools=[status, status, status, route],
                              title_icon=orionis, duration=60)
    await demo.pause(2.5)
    await client.show_loader(MESSAGE, M, False)
    await client.show_message(MESSAGE, M, "Orionis", "Shields at **96 %**, hull intact, the route is set.",
                              tools=[status, status, status, route], title_icon=orionis, duration=60)
    await demo.pause(4)

    demo.scene("The loader alone, in a colour of its own", "an empty panel glowing at its bottom edge, in green")
    await client.hide_message(MESSAGE, M)
    await demo.pause(1)
    await client.show_loader(MESSAGE, M, True, color="#22c55e")
    await demo.pause(3)
    await client.show_loader(MESSAGE, M, False)

    demo.scene("A long answer", "taller than the window: the end shows, the top fades out")
    await client.show_message(MESSAGE, M, "Orionis", LONG, title_icon=orionis, duration=60)
    await demo.pause(7)

    demo.scene("A title in another colour, without a picture")
    await client.show_message(MESSAGE, M, "Warning", "Hull temperature **rising**. Reduce speed.",
                              color="#f59e0b", duration=60)
    await demo.pause(3)

    demo.scene("Restyled while it shows", "accent, size and width change on the window as it is")
    await client.show_message(MESSAGE, M, "Orionis", "Watch me change.", title_icon=orionis, duration=60)
    await demo.pause(1.5)
    for props in ({"accent_color": "#3b82f6"}, {"font_size": 19}, {"width": 640}, {"accent_color": "#22c55e", "font_size": 15, "width": 460}):
        demo.check(await client.update_group(MESSAGE, M, props), f"update_group {props}")
        await demo.pause(1.5)

    demo.scene("Duration, then gone", "shows for 2 seconds, fades out by itself")
    await client.show_message(MESSAGE, M, "Orionis", "Gone in two seconds.", title_icon=orionis, duration=2)
    await demo.pause(4)
