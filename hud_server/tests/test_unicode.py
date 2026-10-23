"""Unicode and emoji everywhere: titles, text, chips, names, panels."""

from hud_server.tests.harness import CHAT, INFO, MESSAGE, STYLE, Demo, area
from hud_server.types import WindowType

TITLE = "Unicode and emoji"
M, C, P = WindowType.MESSAGE, WindowType.CHAT, WindowType.PERSISTENT

ROCKET, FIRE, CHECK, CROSS, WARNING = "\U0001F680", "\U0001F525", "✅", "❌", "⚠️"
SHIELD, GEAR, SATELLITE, FUEL, TROPHY = "\U0001F6E1️", "⚙️", "\U0001F4E1", "⛽", "\U0001F3C6"
# Sequences: skin tone, zero width joiners, a flag, a keycap
WAVE_TONE = "\U0001F44B\U0001F3FD"
ASTRONAUT = "\U0001F9D1‍\U0001F680"
FAMILY = "\U0001F468‍\U0001F469‍\U0001F467‍\U0001F466"
FLAG_DE = "\U0001F1E9\U0001F1EA"
KEYCAP_3 = "3️⃣"

SCRIPTS = (
    "German: Grüße aus Köln, Straße, ÄÖÜ\n\n"
    "Polish: Zażółć gęślą jaźń\n\n"
    "Greek: Γειά σου κόσμε\n\n"
    "Russian: Привет, пилот!\n\n"
    "Japanese: 宇宙船の準備ができました\n\n"
    "Chinese: 量子驱动已就绪\n\n"
    "Korean: 착륙 허가\n\n"
    "Arabic: مرحبا بالطيار\n\n"
    "Hebrew: שלום טייס\n\n"
    "Hindi: नमस्ते पायलट\n\n"
    "Thai: สวัสดีนักบิน"
)

SYMBOLS = (
    "Arrows: ← ↑ → ↓ ↔ ⇒ ⟶\n\n"
    "Maths: ∑ ∫ √ ∞ ≈ ≠ ≤ ≥ ± × ÷ π µ Ω\n\n"
    "Money: € £ ¥ ₿ ¢ ₹\n\n"
    "Boxes: ┌─┬─┐ │ ├─┼─┤ └─┴─┘ ░▒▓█\n\n"
    "Combining: é (é), ñ (ñ), Z̶a̶l̶g̶o̶\n\n"
    "Superscript: E = mc² · H₂O · 10⁻⁶\n\n"
    "A word with no room: " + "Quantenverschränkungsantrieb" * 3
)


async def run(demo: Demo) -> None:
    client = demo.client
    await client.create_group(MESSAGE, M, {**STYLE, **area(40, 40, 620, 1000), "typewriter_effect": False})
    await client.create_group(CHAT, C, {**STYLE, **area(680, 40, 1200, 1000, "bottom"), "typewriter_effect": False})
    await client.create_group(INFO, P, {**STYLE, **area(1260, 40, 1780, 1000)})

    demo.scene("Emoji in titles and text", "colour emoji, sequences drawn as one: skin tone, astronaut, family, flag")
    await client.show_message(MESSAGE, M, f"{ROCKET} Launch {FIRE}",
                              f"{CHECK} Ready {CROSS} Blocked {WARNING} Careful\n\n"
                              f"Sequences: {WAVE_TONE} {ASTRONAUT} {FAMILY} {FLAG_DE} {KEYCAP_3}\n\n"
                              f"**Bold {TROPHY}**, *italic {SATELLITE}*, `code {GEAR}`\n\n"
                              f"| Status | System |\n|---|---|\n| {CHECK} | {SHIELD} Shields |\n| {WARNING} | {FUEL} Fuel |",
                              duration=60)
    await demo.pause(5)

    demo.scene("Scripts", "Latin with accents, Greek, Cyrillic, CJK, right-to-left, Indic, Thai")
    await client.show_message(MESSAGE, M, "Hello, pilot", SCRIPTS, duration=60)
    await demo.pause(6)

    demo.scene("Symbols, combining marks, a word longer than a line", "the long word breaks instead of overflowing")
    await client.show_message(MESSAGE, M, "Symbols", SYMBOLS, duration=60)
    await demo.pause(6)

    demo.scene("Emotion tags are not shown", "[happy] and [sigh] vanish; links and checkboxes stay")
    await client.show_message(MESSAGE, M, "Orionis", "[happy] Docking complete. [sigh] Finally.\n\n"
                              "- [x] Doors\n- [ ] Lights\n\nSee [the manual](https://wingman-ai.com).", duration=60)
    await demo.pause(4)

    demo.scene("In the chat and its chips", "emoji names, emoji tool labels")
    await client.send_chat_message(CHAT, C, f"{ASTRONAUT} Jay", f"{WAVE_TONE} Status? {FLAG_DE}", own=True)
    await client.send_chat_message(CHAT, C, f"{ROCKET} Orionis", "", icon=demo.picture("Orionis", "#d84f4f"), tools=[
        {"name": "scan", "source": f"{SATELLITE} Scanner", "icon": None},
        {"name": "scan", "source": f"{SATELLITE} Scanner", "icon": None},
        {"name": "fuel", "source": f"{FUEL} 燃料", "icon": None},
    ])
    await client.send_chat_message(CHAT, C, f"{ROCKET} Orionis", f"{CHECK} Alles grün. Привет! 準備完了 {TROPHY}",
                                   icon=demo.picture("Orionis", "#d84f4f"))
    await demo.pause(4)

    demo.scene("On the info panel", "emoji titles, a timer and a bar with emoji")
    await client.add_item(INFO, P, f"{SHIELD} Shields", f"{CHECK} Front · {CHECK} Rear · {WARNING} Left")
    await client.show_timer(INFO, P, f"{ROCKET} Quantum", 30, auto_close=False)
    await client.show_progress(INFO, P, f"{FUEL} Refuel 燃料", 60, 100, description="Ø 1.2 SCU/s · ≈ 30 s")
    await client.add_item(INFO, P, f"{FAMILY} Crew", f"{ASTRONAUT} × 4 · {FLAG_DE}")
    await demo.pause(5)
