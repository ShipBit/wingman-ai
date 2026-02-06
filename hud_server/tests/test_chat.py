"""
Test Chat - Chat window tests with natural conversation simulation.

Tests the chat window HUD type with:
- Natural conversation flow with realistic timing
- Full markdown support in messages
- Multiple participants with custom colors
- Consecutive same-sender message merging
- Auto-hide and manual show/hide
- Message overflow with fade effect
"""

import asyncio
from hud_server.tests.test_session import TestSession

# Emoji constants using Unicode escape sequences (avoids file encoding issues)
EMOJI_ROCKET = "\U0001F680"     # 🚀
EMOJI_WARNING = "\u26A0\uFE0F"  # ⚠️
EMOJI_SPARKLES = "\u2728"       # ✨
ARROW_RIGHT = "\u2192"          # →


# =============================================================================
# Conversation Data - Natural AI Assistant Scenario
# =============================================================================

CONVERSATION_WINGMAN = [
    # (sender, message, delay_after)
    ("System", "Voice connection established", 0.5),
    ("User", "Hey, what's my current status?", 1.5),
    ("Wingman", """Your ship status looks **good**:

- Hull: `100%`
- Shields: *92%* (charging)
- Fuel: **67%**

You're currently in safe space near *Hurston*.
""", 2.5),
    ("User", "Where's the nearest refuel station?", 1.5),
    ("Wingman", """I found **3 stations** nearby:

1. **Everus Harbor** - 45km
   - Full service, `moderate` traffic
2. **HDMS-Oparei** - 120km  
   - Fuel only, *low* traffic
3. **Lorville Gates** - 200km
   - Full service, ~~closed~~ **open**

> Recommend: *Everus Harbor* for fastest refuel
""", 3.0),
    ("User", "Set course for Everus Harbor", 1.2),
    ("Wingman", f"""Course set! {EMOJI_ROCKET}

| Parameter | Value |
|-----------|-------|
| Distance  | 45km  |
| ETA       | 2m 30s |
| Speed     | 300m/s |

*Autopilot engaged*
""", 2.0),
    ("System", f"{EMOJI_WARNING} Quantum Travel spooling...", 1.5),
    ("Wingman", "QT drive ready. Jump in **3... 2... 1...**", 2.0),
    ("System", "Arrived at destination", 1.0),
    ("User", "Thanks! Request landing", 1.5),
    ("Wingman", """Landing request sent to **Everus Harbor** ATC.

```
Clearance: GRANTED
Pad: H-07
Bay: Hangar 2
```

Follow the guide markers. Safe landing! {EMOJI_SPARKLES}
""", 2.5),
]

CONVERSATION_CODING = [
    ("User", "Help me write a Python function", 1.5),
    ("Assistant", """Sure! What should the function do?

I can help with:
- Data processing
- API calls
- File operations
- **Algorithms**
""", 2.0),
    ("User", "Calculate fibonacci numbers", 1.2),
    ("Assistant", """Here's an efficient implementation:

```python
def fibonacci(n: int) -> int:
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
```

This uses **O(n)** time and **O(1)** space.

Usage:
- `fibonacci(10)` returns `55`
- `fibonacci(20)` returns `6765`
""", 3.0),
    ("User", "Can you add memoization?", 1.5),
    ("Assistant", """Here's the memoized version:

```python
from functools import lru_cache

@lru_cache(maxsize=None)
def fib_memo(n: int) -> int:
    if n <= 1:
        return n
    return fib_memo(n-1) + fib_memo(n-2)
```

> **Note:** The `@lru_cache` decorator automatically handles caching.

| Approach | Time | Space |
|----------|------|-------|
| Iterative | O(n) | O(1) |
| Memoized | O(n) | O(n) |
| Recursive | O(2^n) | O(n) |
""", 2.5),
    ("User", "Perfect, thanks!", 1.0),
    ("Assistant", "You're welcome! Let me know if you need anything else.", 1.5),
]

CONVERSATION_GAME = [
    ("Player", "What's in my inventory?", 1.2),
    ("Game", """## Inventory

### Weapons
- **Sword of Dawn** (+25 ATK)
- *Wooden Bow* (+10 ATK)

### Items
| Item | Qty | Effect |
|------|-----|--------|
| Health Potion | 5 | +50 HP |
| Mana Crystal | 3 | +30 MP |
| ~~Old Key~~ | 0 | *Used* |

### Gold
`1,234` coins
""", 2.5),
    ("Player", "Use health potion", 1.0),
    ("Game", """**Health Potion** used!

- HP: ~~45/100~~ -> **95/100**
- Potions remaining: `4`

> *You feel rejuvenated!*
""", 2.0),
    ("System", "Enemy approaching!", 0.8),
    ("Game", """**Battle Started!**

*Goblin Warrior* appears!
- Level: 5
- HP: `80/80`
- Weakness: *Fire*

Your turn! Choose:
1. [x] Attack
2. [ ] Defend  
3. [ ] Magic
4. [ ] Flee
""", 2.0),
]


# =============================================================================
# Tests
# =============================================================================

async def test_chat_basic(session: TestSession):
    """Basic chat window test."""
    print(f"[{session.name}] Testing basic chat...")

    chat_name = f"chat_{session.session_id}"

    await session.create_chat_window(
        name=chat_name,
        anchor=session.config.get("anchor", "top_left"),
        priority=50,  # High priority - appears first
        layout_mode="auto",
        width=session.config["hud_width"],
        max_height=300,
        auto_hide=False,
        bg_color=session.config["bg_color"],
        text_color=session.config["text_color"],
        accent_color=session.config["accent_color"],
        opacity=session.config["opacity"],
    )
    await asyncio.sleep(0.5)

    await session.send_chat_message(chat_name, "User", "Hello!")
    await asyncio.sleep(1)
    await session.send_chat_message(chat_name, session.name, "Hi there! How can I help?")
    await asyncio.sleep(1)
    await session.send_chat_message(chat_name, "User", "Just testing the chat window")
    await asyncio.sleep(1)
    await session.send_chat_message(chat_name, session.name, "Looks like it's working!")
    await asyncio.sleep(2)

    await session.delete_chat_window(chat_name)
    print(f"[{session.name}] Basic chat test complete")


async def test_chat_markdown(session: TestSession):
    """Test markdown rendering in chat messages."""
    print(f"[{session.name}] Testing chat markdown...")

    chat_name = f"md_chat_{session.session_id}"

    await session.create_chat_window(
        name=chat_name,
        anchor=session.config.get("anchor", "top_left"),
        priority=40,  # Second priority
        layout_mode="auto",
        width=450,
        max_height=400,
        auto_hide=False,
        sender_colors={
            "User": session.config["user_color"],
            session.name: session.config["accent_color"],
            "System": "#888888",
        },
    )
    await asyncio.sleep(0.5)

    # Test various markdown features (alternate senders so each renders separately)
    await session.send_chat_message(chat_name, "User", "Show me markdown features")
    await asyncio.sleep(1.5)

    await session.send_chat_message(chat_name, session.name,
        "**Bold**, *italic*, `code`, ~~strike~~")
    await asyncio.sleep(1.5)

    await session.send_chat_message(chat_name, "User", "How about lists?")
    await asyncio.sleep(1.5)

    await session.send_chat_message(chat_name, session.name, """Here's a list:
- First item
- Second item
  - Nested item
- Third item""")
    await asyncio.sleep(2)

    await session.send_chat_message(chat_name, "User", "And code?")
    await asyncio.sleep(1.5)

    await session.send_chat_message(chat_name, session.name, """Code block:
```python
print("Hello!")
```""")
    await asyncio.sleep(2)

    await session.send_chat_message(chat_name, "User", "Tables?")
    await asyncio.sleep(1.5)

    await session.send_chat_message(chat_name, session.name, """| Col1 | Col2 |
|------|------|
| A    | B    |
| C    | D    |""")
    await asyncio.sleep(2)

    await session.send_chat_message(chat_name, "System", "> This is a quote block")
    await asyncio.sleep(2)

    await session.delete_chat_window(chat_name)
    print(f"[{session.name}] Chat markdown test complete")


async def test_chat_conversation(session: TestSession, conversation: list = None):
    """Test natural conversation flow."""
    if conversation is None:
        conversation = CONVERSATION_WINGMAN

    print(f"[{session.name}] Testing conversation flow...")

    chat_name = f"conv_{session.session_id}"

    # Determine unique senders for colors
    senders = list(set(msg[0] for msg in conversation))
    colors = ["#4cd964", "#00aaff", "#ff9500", "#9b59b6", "#888888"]
    sender_colors = {s: colors[i % len(colors)] for i, s in enumerate(senders)}

    await session.create_chat_window(
        name=chat_name,
        anchor=session.config.get("anchor", "top_left"),
        priority=30,  # Third priority
        layout_mode="auto",
        width=450,
        max_height=400,
        auto_hide=True,
        auto_hide_delay=10.0,
        fade_old_messages=True,
        sender_colors=sender_colors,
        bg_color=session.config["bg_color"],
        opacity=0.92,
    )
    await asyncio.sleep(0.5)

    for sender, message, delay in conversation:
        await session.send_chat_message(chat_name, sender, message)
        await asyncio.sleep(delay)

    # Let it sit visible for a moment
    await asyncio.sleep(3)

    await session.delete_chat_window(chat_name)
    print(f"[{session.name}] Conversation test complete")


async def test_chat_auto_hide(session: TestSession):
    """Test auto-hide functionality."""
    print(f"[{session.name}] Testing chat auto-hide...")

    chat_name = f"autohide_{session.session_id}"

    await session.create_chat_window(
        name=chat_name,
        anchor=session.config.get("anchor", "top_left"),
        priority=20,  # Fourth priority
        layout_mode="auto",
        width=350,
        max_height=250,
        auto_hide=True,
        auto_hide_delay=3.0,  # Short delay for testing
    )
    await asyncio.sleep(0.5)

    await session.send_chat_message(chat_name, "Test", "This will auto-hide in 3 seconds...")
    await asyncio.sleep(1)
    await session.send_chat_message(chat_name, "Info", "Timer resets with each message")
    await asyncio.sleep(4)  # Wait for auto-hide

    # Should be hidden now, send new message to show again
    await session.send_chat_message(chat_name, "Test", "I'm back!")
    await asyncio.sleep(2)

    await session.delete_chat_window(chat_name)
    print(f"[{session.name}] Auto-hide test complete")


async def test_chat_overflow(session: TestSession):
    """Test message overflow and fade effect."""
    print(f"[{session.name}] Testing chat overflow...")

    chat_name = f"overflow_{session.session_id}"

    await session.create_chat_window(
        name=chat_name,
        anchor=session.config.get("anchor", "top_left"),
        priority=10,  # Fifth priority
        layout_mode="auto",
        width=400,
        max_height=200,  # Small height to trigger overflow
        fade_old_messages=True,
    )
    await asyncio.sleep(0.5)

    # Send many messages to overflow (unique senders per message to prevent merging)
    for i in range(15):
        await session.send_chat_message(chat_name, f"User{i}", f"Message #{i+1}: Testing overflow behavior")
        await asyncio.sleep(0.4)

    await asyncio.sleep(2)
    await session.delete_chat_window(chat_name)
    print(f"[{session.name}] Overflow test complete")


async def test_chat_message_merging(session: TestSession):
    """Test that consecutive messages from the same sender are merged."""
    print(f"[{session.name}] Testing message merging...")

    chat_name = f"merge_{session.session_id}"

    await session.create_chat_window(
        name=chat_name,
        anchor=session.config.get("anchor", "top_left"),
        priority=45,
        layout_mode="auto",
        width=400,
        max_height=300,
        auto_hide=False,
        sender_colors={
            "Alice": "#4cd964",
            "Bob": "#00aaff",
        },
    )
    await asyncio.sleep(0.5)

    # Same sender consecutive - should merge into one block
    await session.send_chat_message(chat_name, "Alice", "Hello!")
    await asyncio.sleep(0.8)
    await session.send_chat_message(chat_name, "Alice", "How are you?")
    await asyncio.sleep(0.8)
    await session.send_chat_message(chat_name, "Alice", "I have a question.")
    await asyncio.sleep(1.5)

    # Different sender - should start a new block
    await session.send_chat_message(chat_name, "Bob", "Hi Alice!")
    await asyncio.sleep(0.8)
    await session.send_chat_message(chat_name, "Bob", "I'm doing great.")
    await asyncio.sleep(1.5)

    # Switch back - new block for Alice again
    await session.send_chat_message(chat_name, "Alice", "Glad to hear it!")
    await asyncio.sleep(2)

    await session.delete_chat_window(chat_name)
    print(f"[{session.name}] Message merging test complete")


async def test_chat_wingman(session: TestSession):
    """Run the Wingman conversation scenario."""
    await test_chat_conversation(session, CONVERSATION_WINGMAN)


async def test_chat_coding(session: TestSession):
    """Run the coding assistant conversation scenario."""
    await test_chat_conversation(session, CONVERSATION_CODING)


async def test_chat_game(session: TestSession):
    """Run the game UI conversation scenario."""
    await test_chat_conversation(session, CONVERSATION_GAME)


# =============================================================================
# Run All Tests
# =============================================================================

async def run_all_chat_tests(session: TestSession):
    """Run all chat tests."""
    await test_chat_basic(session)
    await asyncio.sleep(1)
    await test_chat_markdown(session)
    await asyncio.sleep(1)
    await test_chat_message_merging(session)
    await asyncio.sleep(1)
    await test_chat_auto_hide(session)
    await asyncio.sleep(1)
    await test_chat_overflow(session)
    await asyncio.sleep(1)
    await test_chat_wingman(session)


if __name__ == "__main__":
    from hud_server.tests.test_runner import run_interactive_test
    run_interactive_test(run_all_chat_tests)
