# -*- coding: utf-8 -*-
"""
Test Unicode Stress - Comprehensive Unicode, emoji, and special character tests.

This is a stress test for:
- Emojis in all contexts (messages, persistent info, chat)
- Unicode symbols (arrows, math, currency, etc.)
- Emojis combined with markdown formatting
- Multi-character emoji sequences (skin tones, ZWJ, flags)
- Edge cases and unusual characters
"""

import asyncio
from hud_server.tests.test_session import TestSession

# =============================================================================
# Unicode Constants - Using escape sequences to avoid file encoding issues
# =============================================================================

# Basic Emojis
EMOJI_ROCKET = "\U0001F680"        # 🚀
EMOJI_FIRE = "\U0001F525"          # 🔥
EMOJI_SPARKLES = "\u2728"          # ✨
EMOJI_STAR = "\u2B50"              # ⭐
EMOJI_CHECK = "\u2705"             # ✅
EMOJI_CROSS = "\u274C"             # ❌
EMOJI_WARNING = "\u26A0\uFE0F"     # ⚠️
EMOJI_INFO = "\u2139\uFE0F"        # ℹ️
EMOJI_QUESTION = "\u2753"          # ❓
EMOJI_EXCLAIM = "\u2757"           # ❗

# Objects & Symbols
EMOJI_GEAR = "\u2699\uFE0F"        # ⚙️
EMOJI_WRENCH = "\U0001F527"        # 🔧
EMOJI_HAMMER = "\U0001F528"        # 🔨
EMOJI_SHIELD = "\U0001F6E1\uFE0F"  # 🛡️
EMOJI_SWORD = "\u2694\uFE0F"       # ⚔️
EMOJI_TARGET = "\U0001F3AF"        # 🎯
EMOJI_TROPHY = "\U0001F3C6"        # 🏆
EMOJI_MEDAL = "\U0001F3C5"         # 🏅
EMOJI_CROWN = "\U0001F451"         # 👑
EMOJI_GEM = "\U0001F48E"           # 💎

# Tech & Gaming
EMOJI_CONTROLLER = "\U0001F3AE"    # 🎮
EMOJI_COMPUTER = "\U0001F4BB"      # 💻
EMOJI_SATELLITE = "\U0001F4E1"     # 📡
EMOJI_BATTERY = "\U0001F50B"       # 🔋
EMOJI_PLUG = "\U0001F50C"          # 🔌
EMOJI_DISK = "\U0001F4BE"          # 💾
EMOJI_FOLDER = "\U0001F4C1"        # 📁
EMOJI_CHART = "\U0001F4CA"         # 📊
EMOJI_CLIPBOARD = "\U0001F4CB"     # 📋
EMOJI_LOCK = "\U0001F512"          # 🔒

# Nature & Weather
EMOJI_SUN = "\u2600\uFE0F"         # ☀️
EMOJI_MOON = "\U0001F319"          # 🌙
EMOJI_CLOUD = "\u2601\uFE0F"       # ☁️
EMOJI_LIGHTNING = "\u26A1"         # ⚡
EMOJI_SNOWFLAKE = "\u2744\uFE0F"   # ❄️
EMOJI_DROPLET = "\U0001F4A7"       # 💧
EMOJI_TREE = "\U0001F333"          # 🌳
EMOJI_MOUNTAIN = "\u26F0\uFE0F"    # ⛰️

# Faces & People
EMOJI_SMILE = "\U0001F604"         # 😄
EMOJI_THINK = "\U0001F914"         # 🤔
EMOJI_COOL = "\U0001F60E"          # 😎
EMOJI_ROBOT = "\U0001F916"         # 🤖
EMOJI_ALIEN = "\U0001F47D"         # 👽
EMOJI_GHOST = "\U0001F47B"         # 👻
EMOJI_SKULL = "\U0001F480"         # 💀
EMOJI_THUMBSUP = "\U0001F44D"      # 👍
EMOJI_WAVE = "\U0001F44B"          # 👋
EMOJI_CLAP = "\U0001F44F"          # 👏

# Arrows
ARROW_RIGHT = "\u2192"             # →
ARROW_LEFT = "\u2190"              # ←
ARROW_UP = "\u2191"                # ↑
ARROW_DOWN = "\u2193"              # ↓
ARROW_DOUBLE = "\u21D2"            # ⇒
ARROW_CYCLE = "\U0001F504"         # 🔄

# Math & Currency
SYMBOL_INFINITY = "\u221E"         # ∞
SYMBOL_PLUSMINUS = "\u00B1"        # ±
SYMBOL_DEGREE = "\u00B0"           # °
SYMBOL_MICRO = "\u00B5"            # µ
SYMBOL_OMEGA = "\u03A9"            # Ω
SYMBOL_DELTA = "\u0394"            # Δ
SYMBOL_PI = "\u03C0"               # π
SYMBOL_SIGMA = "\u03A3"            # Σ
CURRENCY_DOLLAR = "\u0024"         # $
CURRENCY_EURO = "\u20AC"           # €
CURRENCY_POUND = "\u00A3"          # £
CURRENCY_YEN = "\u00A5"            # ¥
CURRENCY_BITCOIN = "\u20BF"        # ₿

# Box Drawing & Shapes
BOX_HORIZONTAL = "\u2500"          # ─
BOX_VERTICAL = "\u2502"            # │
BOX_CORNER_TL = "\u250C"           # ┌
BOX_CORNER_TR = "\u2510"           # ┐
BOX_CORNER_BL = "\u2514"           # └
BOX_CORNER_BR = "\u2518"           # ┘
SHAPE_SQUARE = "\u25A0"            # ■
SHAPE_CIRCLE = "\u25CF"            # ●
SHAPE_TRIANGLE = "\u25B2"          # ▲
SHAPE_DIAMOND = "\u25C6"           # ◆

# Bullets & Lists
BULLET_ROUND = "\u2022"            # •
BULLET_TRIANGLE = "\u2023"         # ‣
BULLET_STAR = "\u2605"             # ★
BULLET_CHECK = "\u2713"            # ✓
BULLET_CROSS = "\u2717"            # ✗

# Colored Circles (for status indicators)
CIRCLE_RED = "\U0001F534"          # 🔴
CIRCLE_ORANGE = "\U0001F7E0"       # 🟠
CIRCLE_YELLOW = "\U0001F7E1"       # 🟡
CIRCLE_GREEN = "\U0001F7E2"        # 🟢
CIRCLE_BLUE = "\U0001F535"         # 🔵
CIRCLE_PURPLE = "\U0001F7E3"       # 🟣


# =============================================================================
# Test Functions
# =============================================================================

async def test_emoji_messages(session: TestSession, delay: float = 3.0):
    """Test emojis in basic messages."""
    print(f"[{session.name}] Testing emoji messages...")

    # Simple emoji message
    await session.draw_assistant_message(
        f"""## {EMOJI_ROCKET} Mission Control {EMOJI_ROCKET}

Welcome aboard, Commander! {EMOJI_STAR}

Systems Status:
{EMOJI_CHECK} Navigation: Online
{EMOJI_CHECK} Shields: Active  
{EMOJI_CHECK} Weapons: Armed
{EMOJI_WARNING} Fuel: 67%

{EMOJI_TARGET} Current objective: Reach **Alpha Centauri**
{EMOJI_INFO} ETA: `4h 32m`

> {EMOJI_SPARKLES} *All systems nominal* {EMOJI_SPARKLES}
"""
    )
    await asyncio.sleep(delay)

    # Tech-themed message
    await session.draw_assistant_message(
        f"""## {EMOJI_COMPUTER} System Diagnostics {EMOJI_GEAR}

Running full system check...

{EMOJI_BATTERY} Power: `98%` {ARROW_RIGHT} Optimal
{EMOJI_SATELLITE} Signal: `Strong` {EMOJI_CHECK}
{EMOJI_DISK} Storage: `1.2TB / 2TB`
{EMOJI_LOCK} Security: **Enabled**

### Component Status
| Module | Status | Temp |
|--------|--------|------|
| CPU {EMOJI_COMPUTER} | {CIRCLE_GREEN} OK | 45{SYMBOL_DEGREE}C |
| GPU {EMOJI_CONTROLLER} | {CIRCLE_GREEN} OK | 52{SYMBOL_DEGREE}C |
| RAM {EMOJI_CHART} | {CIRCLE_YELLOW} 78% | 38{SYMBOL_DEGREE}C |
| SSD {EMOJI_DISK} | {CIRCLE_GREEN} OK | 35{SYMBOL_DEGREE}C |

{EMOJI_THUMBSUP} All checks passed!
"""
    )
    await asyncio.sleep(delay)

    await session.hide()
    print(f"[{session.name}] Emoji messages test complete")


async def test_emoji_markdown_combo(session: TestSession, delay: float = 4.0):
    """Test emojis combined with various markdown elements."""
    print(f"[{session.name}] Testing emoji + markdown combinations...")

    # Headers with emojis
    await session.draw_assistant_message(
        f"""## {EMOJI_TROPHY} Achievement Unlocked! {EMOJI_CROWN}

You've earned the **Legendary** rank! {EMOJI_MEDAL}

### {EMOJI_STAR} Stats Summary
- {EMOJI_SWORD} Battles Won: **1,337**
- {EMOJI_SHIELD} Damage Blocked: *2.5M*
- {EMOJI_TARGET} Accuracy: `98.7%`
- {EMOJI_GEM} Loot Collected: ~~1000~~ **1500** items

### {EMOJI_CHART} Progress
1. [x] Complete tutorial {EMOJI_CHECK}
2. [x] Win first battle {EMOJI_SWORD}
3. [x] Reach level 50 {EMOJI_TROPHY}
4. [ ] Defeat final boss {EMOJI_SKULL}

> {EMOJI_SPARKLES} *"The stars await, Commander!"* {EMOJI_ROCKET}

---

{ARROW_DOUBLE} Next objective: **Sector 7** {EMOJI_ALIEN}
"""
    )
    await asyncio.sleep(delay)

    # Code blocks with emojis
    await session.draw_assistant_message(
        f"""## {EMOJI_WRENCH} Configuration

Here's your config file {EMOJI_FOLDER}:

```yaml
# {EMOJI_GEAR} Settings
server:
  host: "localhost"
  port: 8080  # {EMOJI_PLUG}
  
features:
  - {EMOJI_SHIELD} shields
  - {EMOJI_ROCKET} turbo
  - {EMOJI_SATELLITE} radar
```

{EMOJI_INFO} **Note:** Changes require restart {ARROW_CYCLE}

Math symbols: {SYMBOL_PI} = 3.14159, {SYMBOL_INFINITY} loops, {SYMBOL_PLUSMINUS}5%
Currency: {CURRENCY_DOLLAR}99.99 / {CURRENCY_EURO}89.99 / {CURRENCY_BITCOIN}0.002
"""
    )
    await asyncio.sleep(delay)

    await session.hide()
    print(f"[{session.name}] Emoji + markdown combo test complete")


async def test_emoji_persistent_info(session: TestSession, delay: float = 2.5):
    """Test emojis in persistent info panels."""
    print(f"[{session.name}] Testing emoji persistent info...")

    # Status indicators with colored circles
    await session.add_persistent_info(
        f"{EMOJI_SATELLITE} Comm Status",
        f"""{CIRCLE_GREEN} Primary: **Online**
{CIRCLE_GREEN} Backup: *Standby*
{CIRCLE_YELLOW} Emergency: `Charging`
{CIRCLE_RED} Deep Space: ~~Offline~~ **Connecting...**"""
    )
    await asyncio.sleep(delay)

    # Ship systems
    await session.add_persistent_info(
        f"{EMOJI_ROCKET} Ship Systems",
        f"""{EMOJI_SHIELD} Shields: `100%` {EMOJI_CHECK}
{EMOJI_BATTERY} Power: `87%` {EMOJI_LIGHTNING}
{EMOJI_GEAR} Engine: *Optimal* {EMOJI_FIRE}
{EMOJI_SATELLITE} Radar: **Active** {EMOJI_TARGET}"""
    )
    await asyncio.sleep(delay)

    # Weather/environment
    await session.add_persistent_info(
        f"{EMOJI_CLOUD} Environment",
        f"""{EMOJI_SUN} Solar radiation: **Low**
{EMOJI_MOON} Night cycle in: `2h 15m`
{EMOJI_SNOWFLAKE} Hull temp: -127{SYMBOL_DEGREE}C
{EMOJI_DROPLET} Humidity: 0% (vacuum)"""
    )
    await asyncio.sleep(delay)

    # Mission objectives with checkmarks
    await session.add_persistent_info(
        f"{EMOJI_TARGET} Mission Objectives",
        f"""{BULLET_CHECK} Objective 1: ~~Collect samples~~ **Done**
{BULLET_CHECK} Objective 2: ~~Deploy beacon~~ **Done**  
{BULLET_STAR} Objective 3: **Explore crater** {ARROW_LEFT} Current
{BULLET_ROUND} Objective 4: Return to base"""
    )
    await asyncio.sleep(delay)

    # Inventory with mixed symbols
    await session.add_persistent_info(
        f"{EMOJI_CLIPBOARD} Inventory",
        f"""{SHAPE_DIAMOND} Credits: {CURRENCY_DOLLAR}15,000
{EMOJI_GEM} Crystals: **42** {EMOJI_SPARKLES}
{EMOJI_WRENCH} Repair kits: `3`
{EMOJI_BATTERY} Fuel cells: *5 / 10*"""
    )
    await asyncio.sleep(delay * 2)

    # Clear and show we're done
    await session.clear_all_persistent_info()
    print(f"[{session.name}] Emoji persistent info test complete")


async def test_emoji_progress_bars(session: TestSession, delay: float = 0.4):
    """Test emojis in progress bar titles."""
    print(f"[{session.name}] Testing emoji progress bars...")

    # Multiple progress bars with emoji titles
    await session.show_progress(f"{EMOJI_BATTERY} Charging", 0, 100, "Initializing...")
    await session.show_progress(f"{EMOJI_DISK} Saving", 0, 100, "Preparing...")
    await session.show_progress(f"{EMOJI_SATELLITE} Uploading", 0, 100, "Connecting...")

    # Animate all three
    for i in range(0, 101, 5):
        await session.show_progress(f"{EMOJI_BATTERY} Charging", i, 100, f"{i}% {EMOJI_LIGHTNING}")
        await session.show_progress(f"{EMOJI_DISK} Saving", min(i + 10, 100), 100, f"Saving... {EMOJI_CHECK if i >= 90 else ''}")
        await session.show_progress(f"{EMOJI_SATELLITE} Uploading", max(0, i - 20), 100, f"Sending data {ARROW_UP}")
        await asyncio.sleep(delay)

    await asyncio.sleep(1)
    await session.clear_all_persistent_info()
    print(f"[{session.name}] Emoji progress bars test complete")


async def test_emoji_chat(session: TestSession, delay: float = 1.5):
    """Test emojis in chat messages."""
    print(f"[{session.name}] Testing emoji chat...")

    chat_name = f"{session.name}_emoji_chat"

    # Create chat with emoji-rich sender names
    await session.create_chat_window(
        chat_name,
        max_messages=20,
        auto_hide=False,
        sender_colors={
            f"Captain {EMOJI_CROWN}": "#FFD700",
            f"Engineer {EMOJI_WRENCH}": "#00AAFF",
            f"Pilot {EMOJI_ROCKET}": "#FF6B6B",
            f"AI {EMOJI_ROBOT}": "#00FF88",
            "System": "#888888",
        }
    )

    # Chat conversation with lots of emojis
    conversation = [
        ("System", f"{EMOJI_CHECK} Communication channel open"),
        (f"Captain {EMOJI_CROWN}", f"All stations, report! {EMOJI_SATELLITE}"),
        (f"Engineer {EMOJI_WRENCH}", f"Engineering ready! Shields at **100%** {EMOJI_SHIELD}"),
        (f"Pilot {EMOJI_ROCKET}", f"Navigation locked {EMOJI_TARGET} {ARROW_RIGHT} Alpha Centauri"),
        (f"AI {EMOJI_ROBOT}", f"All systems nominal {EMOJI_CHECK}{EMOJI_CHECK}{EMOJI_CHECK}"),
        (f"Captain {EMOJI_CROWN}", f"Excellent! {EMOJI_THUMBSUP} Prepare for jump!"),
        ("System", f"{EMOJI_WARNING} Quantum drive spooling..."),
        (f"Engineer {EMOJI_WRENCH}", f"Power levels: {EMOJI_LIGHTNING}{EMOJI_LIGHTNING}{EMOJI_LIGHTNING}"),
        (f"Pilot {EMOJI_ROCKET}", f"3... 2... 1... {EMOJI_FIRE}"),
        ("System", f"{EMOJI_SPARKLES} Jump complete! Welcome to **Alpha Centauri** {EMOJI_STAR}"),
        (f"AI {EMOJI_ROBOT}", f"Scanning... {EMOJI_SATELLITE} Found: 3 planets, 2 moons {EMOJI_MOON}"),
        (f"Captain {EMOJI_CROWN}", f"{EMOJI_TROPHY} Great work team! {EMOJI_CLAP}{EMOJI_CLAP}"),
    ]

    for sender, text in conversation:
        await session.send_chat_message(chat_name, sender, text)
        await asyncio.sleep(delay)

    await asyncio.sleep(2)
    await session.delete_chat_window(chat_name)
    print(f"[{session.name}] Emoji chat test complete")


async def test_special_unicode(session: TestSession, delay: float = 3.0):
    """Test special Unicode characters and edge cases."""
    print(f"[{session.name}] Testing special Unicode characters...")

    # Box drawing characters
    await session.draw_assistant_message(
        f"""## Box Drawing Characters

Custom borders and frames:

{BOX_CORNER_TL}{BOX_HORIZONTAL}{BOX_HORIZONTAL}{BOX_HORIZONTAL}{BOX_HORIZONTAL}{BOX_HORIZONTAL}{BOX_CORNER_TR}
{BOX_VERTICAL} DATA {BOX_VERTICAL}
{BOX_CORNER_BL}{BOX_HORIZONTAL}{BOX_HORIZONTAL}{BOX_HORIZONTAL}{BOX_HORIZONTAL}{BOX_HORIZONTAL}{BOX_CORNER_BR}

Shapes: {SHAPE_SQUARE} {SHAPE_CIRCLE} {SHAPE_TRIANGLE} {SHAPE_DIAMOND}
Arrows: {ARROW_LEFT} {ARROW_UP} {ARROW_DOWN} {ARROW_RIGHT} {ARROW_DOUBLE} {ARROW_CYCLE}
Bullets: {BULLET_ROUND} {BULLET_TRIANGLE} {BULLET_STAR} {BULLET_CHECK} {BULLET_CROSS}
"""
    )
    await asyncio.sleep(delay)

    # Math and science
    await session.draw_assistant_message(
        f"""## Math & Science {SYMBOL_SIGMA}

### Mathematical Expressions

Area of circle: {SYMBOL_PI}r{SYMBOL_DEGREE}
Temperature: 25{SYMBOL_DEGREE}C {SYMBOL_PLUSMINUS} 2{SYMBOL_DEGREE}
Resistance: 47k{SYMBOL_OMEGA}
Change: {SYMBOL_DELTA}v = 15 m/s
Sum: {SYMBOL_SIGMA}(1..n) = n(n+1)/2
Limit: x {ARROW_RIGHT} {SYMBOL_INFINITY}

### Scientific Notation
- 6.022 {SYMBOL_MICRO} x 10^23
- Wavelength: 550nm ({EMOJI_SUN} visible)
"""
    )
    await asyncio.sleep(delay)

    # Currency showcase
    await session.draw_assistant_message(
        f"""## Currency Exchange {EMOJI_CHART}

### Current Rates

| Currency | Symbol | Rate |
|----------|--------|------|
| USD | {CURRENCY_DOLLAR} | 1.00 |
| EUR | {CURRENCY_EURO} | 0.92 |
| GBP | {CURRENCY_POUND} | 0.79 |
| JPY | {CURRENCY_YEN} | 149.50 |
| BTC | {CURRENCY_BITCOIN} | 0.000023 |

{EMOJI_SPARKLES} *Updated in real-time* {ARROW_CYCLE}
"""
    )
    await asyncio.sleep(delay)

    await session.hide()
    print(f"[{session.name}] Special Unicode test complete")


async def test_emoji_status_indicators(session: TestSession, delay: float = 2.0):
    """Test colored circle emojis as status indicators."""
    print(f"[{session.name}] Testing status indicators...")

    # Server status panel
    await session.add_persistent_info(
        f"{EMOJI_COMPUTER} Server Status",
        f"""{CIRCLE_GREEN} API Server: **Running**
{CIRCLE_GREEN} Database: **Connected**
{CIRCLE_YELLOW} Cache: **Warming up**
{CIRCLE_RED} Backup: **Offline**
{CIRCLE_BLUE} CDN: **Syncing**
{CIRCLE_PURPLE} ML Engine: **Training**"""
    )
    await asyncio.sleep(delay)

    # Player status
    await session.add_persistent_info(
        f"{EMOJI_CONTROLLER} Squad Status",
        f"""{CIRCLE_GREEN} Player1 {EMOJI_CROWN}: *In Game*
{CIRCLE_GREEN} Player2 {EMOJI_SWORD}: *In Game*
{CIRCLE_YELLOW} Player3 {EMOJI_SHIELD}: *AFK*
{CIRCLE_RED} Player4 {EMOJI_ALIEN}: *Disconnected*"""
    )
    await asyncio.sleep(delay)

    # Alert levels
    await session.add_persistent_info(
        f"{EMOJI_WARNING} Alert Level",
        f"""Current: {CIRCLE_YELLOW} **CAUTION**

{CIRCLE_GREEN} Green: All clear
{CIRCLE_YELLOW} Yellow: Caution advised
{EMOJI_FIRE} Orange: High alert
{CIRCLE_RED} Red: Emergency"""
    )
    await asyncio.sleep(delay * 2)

    await session.clear_all_persistent_info()
    print(f"[{session.name}] Status indicators test complete")


async def test_extreme_emoji_density(session: TestSession, delay: float = 4.0):
    """Stress test with extremely high emoji density."""
    print(f"[{session.name}] Testing extreme emoji density (stress test)...")

    # Message packed with emojis
    await session.draw_assistant_message(
        f"""## {EMOJI_FIRE}{EMOJI_FIRE}{EMOJI_FIRE} STRESS TEST {EMOJI_FIRE}{EMOJI_FIRE}{EMOJI_FIRE}

{EMOJI_ROCKET}{EMOJI_STAR}{EMOJI_SPARKLES}{EMOJI_TROPHY}{EMOJI_MEDAL}{EMOJI_CROWN}{EMOJI_GEM}{EMOJI_TARGET}

### {EMOJI_LIGHTNING} Every {EMOJI_LIGHTNING} Word {EMOJI_LIGHTNING} Has {EMOJI_LIGHTNING} Emoji {EMOJI_LIGHTNING}

{EMOJI_CHECK} Test {EMOJI_CHECK} One {EMOJI_CHECK} Two {EMOJI_CHECK} Three {EMOJI_CHECK}

| {EMOJI_STAR} | {EMOJI_FIRE} | {EMOJI_ROCKET} | {EMOJI_SHIELD} |
|---|---|---|---|
| {CIRCLE_RED} | {CIRCLE_ORANGE} | {CIRCLE_YELLOW} | {CIRCLE_GREEN} |
| {EMOJI_THUMBSUP} | {EMOJI_CLAP} | {EMOJI_WAVE} | {EMOJI_COOL} |

- {EMOJI_SWORD}{EMOJI_SHIELD} Combat: **Ready** {EMOJI_CHECK}
- {EMOJI_SATELLITE}{EMOJI_COMPUTER} Systems: *Online* {EMOJI_GEAR}
- {EMOJI_BATTERY}{EMOJI_PLUG} Power: `100%` {EMOJI_LIGHTNING}

> {EMOJI_ROBOT} *"Processing {SYMBOL_INFINITY} possibilities..."* {EMOJI_ALIEN}

{ARROW_UP}{ARROW_RIGHT}{ARROW_DOWN}{ARROW_LEFT} Navigation {ARROW_CYCLE}

{EMOJI_SKULL}{EMOJI_GHOST}{EMOJI_ALIEN}{EMOJI_ROBOT}{EMOJI_COOL}{EMOJI_THINK}{EMOJI_SMILE}

**{CURRENCY_DOLLAR}1000 {CURRENCY_EURO}920 {CURRENCY_POUND}790 {CURRENCY_YEN}149500 {CURRENCY_BITCOIN}0.023**

{EMOJI_SPARKLES}{EMOJI_STAR}{EMOJI_SPARKLES}{EMOJI_STAR}{EMOJI_SPARKLES}{EMOJI_STAR}{EMOJI_SPARKLES}
"""
    )
    await asyncio.sleep(delay)

    await session.hide()
    print(f"[{session.name}] Extreme emoji density test complete")


# =============================================================================
# Run All Tests
# =============================================================================

async def run_all_unicode_stress_tests(session: TestSession):
    """Run all Unicode and emoji stress tests."""
    print("\n" + "=" * 60)
    print("UNICODE & EMOJI STRESS TEST SUITE")
    print("=" * 60)

    await test_emoji_messages(session)
    await asyncio.sleep(1)

    await test_emoji_markdown_combo(session)
    await asyncio.sleep(1)

    await test_emoji_persistent_info(session)
    await asyncio.sleep(1)

    await test_emoji_progress_bars(session)
    await asyncio.sleep(1)

    await test_emoji_chat(session)
    await asyncio.sleep(1)

    await test_special_unicode(session)
    await asyncio.sleep(1)

    await test_emoji_status_indicators(session)
    await asyncio.sleep(1)

    await test_extreme_emoji_density(session)

    print("\n" + "=" * 60)
    print("UNICODE & EMOJI STRESS TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    from hud_server.tests.test_runner import run_interactive_test
    run_interactive_test(run_all_unicode_stress_tests)
