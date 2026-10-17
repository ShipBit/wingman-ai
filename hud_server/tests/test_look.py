"""The look: accent colours, the background's opacity, corners, padding,
fonts, a light theme and the window's opacity."""

from hud_server.tests.harness import STYLE, Demo, area
from hud_server.types import WindowType

TITLE = "Glass look"
M, P = WindowType.MESSAGE, WindowType.PERSISTENT

TOOLS = [{"name": "status", "source": "Ship Status", "icon": None}] * 2 + [{"name": "route", "source": "SC Tools", "icon": None}]


async def row(demo: Demo, variants: list, text: str, top: int = 80, width: int = 360, tools=None, timer=False):
    """One window per variant, side by side."""
    client = demo.client
    groups = []
    for i, (label, props) in enumerate(variants):
        group = f"demo_look_{i}"
        groups.append((group, M))
        x = 40 + i * (width + 30)
        await client.create_group(group, M, {**STYLE, **area(x, top, x + width, top + 520), "typewriter_effect": False,
                                             **props})
        await client.show_message(group, M, label, text, tools=tools, duration=60,
                                  title_icon=demo.picture(label, props.get("accent_color", STYLE["accent_color"])))
        if timer:
            groups.append((group, P))
            await client.create_group(group, P, {**STYLE, **area(x, top + 300, x + width, top + 700), **props})
            await client.show_progress(group, P, "Refinery Job", 30 + i * 15, 100, description="Quantanium")
    return groups


async def clear(demo: Demo, groups: list) -> None:
    for group, element in groups:
        await demo.client.delete_group(group, element)


async def run(demo: Demo) -> None:
    demo.scene("Accent colours", "the title, the rule, chips, bars and the loader follow the accent")
    groups = await row(demo, [(name, {"accent_color": color}) for name, color in (
        ("Crimson", "#d84f4f"), ("Azure", "#3b82f6"), ("Emerald", "#22c55e"), ("Amber", "#f59e0b"))],
        "Shields at **96 %**, the route is set.", tools=TOOLS, timer=True)
    for group, element in groups:
        if element == M:
            await demo.client.show_loader(group, M, True)
    await demo.pause(6)
    await clear(demo, groups)

    demo.scene("Background opacity", "from a solid panel to none: the text stays, the background lets more through")
    groups = await row(demo, [(f"{pct} %", {"bg_color": f"#202227{round(pct * 2.55):02x}"}) for pct in (100, 85, 60, 35, 0)],
                       "What lies behind me shows through as much as my background lets it.", width=300)
    await demo.pause(8)
    await clear(demo, groups)

    demo.scene("Corners and padding")
    groups = await row(demo, [(f"r {r}, p {p}", {"border_radius": r, "content_padding": p}) for r, p in (
        (0, 10), (6, 14), (12, 16), (24, 24))], "Same text, different corners and room.", tools=TOOLS)
    await demo.pause(5)
    await clear(demo, groups)

    demo.scene("Fonts and sizes")
    groups = await row(demo, [(f"{family} {size}", {"font_family": family, "font_size": size}) for family, size in (
        ("Segoe UI", 14), ("Segoe UI", 20), ("Verdana", 15), ("Consolas", 16))],
        "The quick brown fox jumps over the lazy dog. **Bold**, *italic*, `code`.")
    await demo.pause(5)
    await clear(demo, groups)

    demo.scene("A light theme", "dark lines on a light panel, tables a darker shade")
    groups = await row(demo, [("Light", {"bg_color": "#f2f2f2e6", "text_color": "#202020", "accent_color": "#2563eb"}),
                              ("Paper", {"bg_color": "#faf6eef2", "text_color": "#3a3226", "accent_color": "#b45309"})],
                       "| Ship | Fuel |\n|---|---|\n| Cutlass | 80 % |\n| Prospector | 45 % |", width=420, tools=TOOLS,
                       timer=True)
    await demo.pause(5)
    await clear(demo, groups)

    demo.scene("The window's opacity", "the whole window, text included, fades")
    groups = await row(demo, [(f"{pct} %", {"opacity": pct / 100}) for pct in (100, 70, 40)], "Fading as a whole.")
    await demo.pause(4)
    await clear(demo, groups)
