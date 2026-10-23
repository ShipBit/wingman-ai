"""The profile preview: the chat and info containers with sample content,
filling their areas, as the HUD settings page shows them. In interactive mode
they can be moved and resized with the mouse."""

from hud_server.tests.harness import STYLE, Demo, area

TITLE = "Profile preview"


def containers(chat_flow: bool, **style) -> dict:
    look = {**STYLE, **style}
    return {
        "chat": {**look, **area(80, 80, 600, 560), "chat_flow": chat_flow, "sample_user": "Jay"},
        "info": {**look, **area(80, 620, 600, 940)},
    }


async def run(demo: Demo) -> None:
    client = demo.client

    demo.scene("The preview", "both containers fill their areas, framed, with their size in the corner")
    demo.check(await client.set_preview(containers(chat_flow=False)), "set_preview")
    state = await client.get_preview()
    demo.check(state and state.get("active") and set(state.get("containers", {})) == {"chat", "info"},
               "the server reports the preview")
    await demo.pause(4)

    demo.scene("With the chat flow", "the chat container shows a conversation instead of a single answer")
    demo.check(await client.set_preview(containers(chat_flow=True)), "set_preview chat flow")
    await demo.pause(4)

    demo.scene("Restyled while it shows", "accent, size and corners change on the spot")
    for style in ({"accent_color": "#3b82f6"}, {"font_size": 19}, {"border_radius": 2, "bg_color": "#101215f2"}):
        demo.check(await client.set_preview(containers(chat_flow=True, **style)), f"restyle {style}")
        await demo.pause(1.5)

    demo.scene("Drag it", "move a container by its middle, resize it by an edge or corner (15 seconds)")
    demo.check(await client.set_preview(containers(chat_flow=True), interactive=True), "interactive preview")
    if not demo.headless:
        last = None
        for _ in range(30):
            await demo.pause(0.5)
            state = await client.get_preview() or {}
            now = {name: tuple(c.get(k) for k in ("x", "y", "width", "max_height"))
                   for name, c in state.get("containers", {}).items()}
            if now != last and last is not None:
                print(f"   moved: {now}")
            last = now

    demo.scene("The preview ends", "the containers go; the real ones would come back")
    demo.check(await client.clear_preview(), "clear_preview")
    state = await client.get_preview()
    demo.check(state is not None and not state.get("active"), "no preview left")
    await demo.pause(1)
