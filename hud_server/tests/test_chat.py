"""The chat flow: the running conversation, like a messenger."""

from hud_server.tests.harness import CHAT, STYLE, Demo, area
from hud_server.types import WindowType

TITLE = "Chat flow"
C = WindowType.CHAT
USER = "Jay"


async def run(demo: Demo) -> None:
    client = demo.client
    await client.create_group(CHAT, C, {**STYLE, **area(40, 40, 580, 760, "bottom")})
    orionis = demo.picture("Orionis", "#d84f4f")
    nova = demo.picture("Nova", "#3b82f6")

    async def user(text):
        demo.check(await client.send_chat_message(CHAT, C, USER, text, own=True), f"user message {text!r}")

    async def wingman(text, name="Orionis", icon=orionis, tools=None, color=None):
        result = await client.send_chat_message(CHAT, C, name, text, icon=icon, tools=tools, color=color)
        demo.check(result and result.get("message_id"), f"{name}'s message {text!r}")
        return result.get("message_id") if result else None

    demo.scene("A conversation", "your lines as bubbles on the right, each a bubble of its own; Wingmen with their picture")
    await user("Any open tasks?")
    await demo.pause(1)
    await wingman("The Sadaryx gathering is still in progress. No reminders pending.")
    await demo.pause(3)
    await user("And the ship?")
    await demo.pause(0.6)
    await user("Fuel especially.")
    await demo.pause(1)
    await wingman("Fuel at **82 %**, enough for three jumps.")
    await demo.pause(3)

    demo.scene("Two Wingmen", "each with their own picture and colour; one following up goes on under its name")
    await wingman("Nova here. Hangar 3 reports the Cutlass ready.", name="Nova", icon=nova, color="#3b82f6")
    await demo.pause(2)
    await wingman("Shall I request clearance?", name="Nova", icon=nova, color="#3b82f6")
    await demo.pause(3)

    demo.scene("Tool calls between question and answer",
               "the calls join one row of chips under the question's answer; repeats show once with a count")
    await user("Prepare the ship for departure.")
    await demo.pause(0.8)
    capability = {"name": "activate_capability", "source": "activate_capability", "icon": None}
    tasks = {"name": "list_tasks", "source": "list_tasks", "icon": demo.icon("Tasks", "#a855f7")}
    for tool in (capability, capability, tasks, capability):
        await wingman("", tools=[tool])
        await demo.pause(0.5)
    await wingman("Engines warm, doors closing, clearance requested.")
    await demo.pause(4)

    demo.scene("Thinking", "the bottom edge glows softly while the Wingman works")
    await user("How long to Port Olisar?")
    await client.show_loader(CHAT, C, True)
    await demo.pause(2.5)
    await client.show_loader(CHAT, C, False)
    await wingman("About **3 minutes**: two quantum jumps and a short approach. " * 2)
    await demo.pause(5)

    demo.scene("A correction", "the last answer changes in place")
    message_id = await wingman("ETA 4 minutes.")
    await demo.pause(2)
    if message_id:
        demo.check(await client.update_chat_message(CHAT, C, message_id, "ETA **3 minutes**, corrected."), "update")
    await demo.pause(3)

    demo.scene("Markdown and pictures", "a table, code and an image inside a Wingman's message")
    await user("Cargo and the route, please.")
    await wingman("| Cargo | SCU |\n|---|---|\n| Quantanium | 32 |\n| Laranite | 12 |\n\n`route --to olisar`\n\n"
                  f"![route]({demo.data_uri(demo.picture('Route', '#22c55e'), 96)})")
    await demo.pause(5)

    demo.scene("A long conversation", "only what fits shows; older messages fade, the top fades out")
    for i in range(1, 13):
        await user(f"Status {i}?")
        await wingman(f"Status {i}: all green.", name="Nova" if i % 3 == 0 else "Orionis",
                      icon=nova if i % 3 == 0 else orionis, color="#3b82f6" if i % 3 == 0 else None)
        await demo.pause(0.3)
    await demo.pause(3)

    demo.scene("Hidden, and back with the next message", "the history is still there")
    demo.check(await client.hide_chat_window(CHAT, C), "hide")
    await demo.pause(2)
    await wingman("Back again, nothing lost.")
    await demo.pause(3)
    demo.check(await client.hide_chat_window(CHAT, C), "hide")
    await demo.pause(1)
    demo.check(await client.show_chat_window(CHAT, C), "show")
    await demo.pause(2)

    demo.scene("Cleared", "the window empties and fades out")
    demo.check(await client.clear_chat_window(CHAT, C), "clear")
    await demo.pause(2)
