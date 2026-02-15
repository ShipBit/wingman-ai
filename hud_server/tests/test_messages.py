"""
Test Messages - Basic message display and markdown rendering tests.
"""

import asyncio
import random
from hud_server.tests.test_session import TestSession


# =============================================================================
# Test Data
# =============================================================================

SHORT_MESSAGES = [
    "Hello, I'm ready to assist.",
    "Command executed successfully.",
    "Processing your request...",
    "Target acquired.",
    "Systems nominal.",
]

MARKDOWN_SAMPLES = [
    """**Bold text** and *italic text* mixed together.
Also `inline code` and ~~strikethrough~~ for variety.""",

    """## Mission Briefing

### Objective
Retrieve the artifact from **Alpha Station**.

### Intel
1. Station has 3 docking bays
2. Security level: *Medium*
3. Expected resistance: `Minimal`""",

    """Here's a checklist:
- [x] Primary systems online
- [x] Navigation calibrated
- [ ] Cargo secured
- [ ] Jump coordinates verified""",

    """Configuration:
```
target = "Alpha Centauri"
fuel = 87.5
stealth = True
```
Ready for departure.""",

    """| Parameter | Value | Status |
|-----------|-------|--------|
| Power     | 95%   | OK     |
| Shields   | 78%   | WARN   |
| Hull      | 100%  | OK     |

> **Note:** Shields recharging""",
]

LONG_MESSAGE = """## Comprehensive Status Report

### Navigation Systems
All navigation systems are **fully operational**. Current heading: `045.7 deg`

### Communication Array
Minor interference detected on channels 4-6. Switching to backup frequencies.

### Resource Status
| Resource | Level | Rate |
|----------|-------|------|
| Fuel     | 67%   | -2%/h |
| O2       | 98%   | -0.1%/h |
| Power    | 85%   | +5%/h |

### Recommendations
1. Refuel at next station
2. Run diagnostics on comm array
3. Continue current heading

> *ETA to destination: 4h 32m*"""


# =============================================================================
# Tests
# =============================================================================

async def test_basic_messages(session: TestSession, delay: float = 2.0):
    """Test basic message display."""
    print(f"[{session.name}] Testing basic messages...")

    await session.draw_user_message("Show me a status update")
    await asyncio.sleep(delay)

    await session.draw_assistant_message(random.choice(SHORT_MESSAGES))
    await asyncio.sleep(delay)

    await session.draw_assistant_message(
        "This is a medium-length response that provides "
        "more context and information about the current situation."
    )
    await asyncio.sleep(delay)

    await session.hide()
    print(f"[{session.name}] Basic messages complete")


async def test_markdown(session: TestSession, delay: float = 3.0):
    """Test markdown rendering."""
    print(f"[{session.name}] Testing markdown...")

    for i, sample in enumerate(MARKDOWN_SAMPLES):
        await session.draw_assistant_message(sample)
        await asyncio.sleep(delay)

    await session.hide()
    print(f"[{session.name}] Markdown test complete")


async def test_long_message(session: TestSession, delay: float = 5.0):
    """Test long message with scrolling."""
    print(f"[{session.name}] Testing long message...")

    await session.draw_assistant_message(LONG_MESSAGE)
    await asyncio.sleep(delay)

    await session.hide()
    print(f"[{session.name}] Long message test complete")


async def test_loading_indicator(session: TestSession, delay: float = 1.0):
    """Test loading indicator."""
    print(f"[{session.name}] Testing loading indicator...")

    await session.draw_user_message("What's the weather?")
    await asyncio.sleep(delay)

    await session.set_loading(True)
    await asyncio.sleep(delay * 2)

    await session.set_loading(False)
    await session.draw_assistant_message("The weather is sunny with 22°C.")
    await asyncio.sleep(delay * 2)

    await session.hide()
    print(f"[{session.name}] Loading indicator test complete")


async def test_loader_only(session: TestSession, delay: float = 1.0):
    """Test loading indicator without any message content."""
    print(f"[{session.name}] Testing loader-only (no message)...")

    # Show loader without any prior message
    await session.set_loading(True)
    await asyncio.sleep(delay * 3)

    # Hide loader
    await session.set_loading(False)
    await asyncio.sleep(delay)

    await session.hide()
    print(f"[{session.name}] Loader-only test complete")


async def test_sequential_messages(session: TestSession, delay: float = 1.5):
    """Test sequential messages to verify cache invalidation."""
    print(f"[{session.name}] Testing sequential messages...")

    messages = [
        "First message - this should display properly.",
        "Second message - cache should invalidate.",
        "Third message with **markdown** formatting.",
        "Fourth message - all messages should render correctly.",
    ]

    for i, msg in enumerate(messages, 1):
        await session.draw_assistant_message(msg)
        await asyncio.sleep(delay)

    await session.hide()
    print(f"[{session.name}] Sequential messages test complete")


async def test_message_bottom_fade(session: TestSession, delay: float = 2.0):
    """Test bottom fade effect when message content overflows."""
    print(f"[{session.name}] Testing message bottom fade...")

    # Very long message that will overflow a small window
    long_message = """# Comprehensive Status Report

## Navigation Systems
All navigation systems are **fully operational**. Current heading: `045.7 deg`

## Communication Array
Minor interference detected on channels 4-6. Switching to backup frequencies.

## Resource Status
| Resource | Level | Rate |
|----------|-------|------|
| Fuel     | 67%   | -2%/h |
| O2       | 98%   | -0.1%/h |
| Power    | 85%   | +5%/h |

## Recommendations
1. Refuel at next station
2. Run diagnostics on comm array
3. Continue current heading

## Additional Intel
- Sector scan complete
- No hostile contacts detected
- Friendly vessels in vicinity: 3

> *ETA to destination: 4h 32m*

## Mission Details
- Objective: Survey nebula region
- Timeline: 48 hours
- Support: Available on demand

## Final Notes
All systems nominal. Ready for next assignment.
"""

    # Use a small max_height to force overflow and trigger bottom fade
    await session.draw_message_with_props(
        "Wingman",
        long_message,
        custom_props={"max_height": 150, "scroll_fade_height": 30}
    )
    await asyncio.sleep(delay)

    # Also test with loading indicator (should reserve 30px at bottom)
    await session.set_loading(True)
    await asyncio.sleep(delay)
    await session.set_loading(False)

    await session.hide()
    print(f"[{session.name}] Bottom fade test complete")


# =============================================================================
# Run All Tests
# =============================================================================

async def run_all_message_tests(session: TestSession):
    """Run all message tests."""
    await test_basic_messages(session)
    await asyncio.sleep(1)
    await test_markdown(session)
    await asyncio.sleep(1)
    await test_long_message(session)
    await asyncio.sleep(1)
    await test_loading_indicator(session)
    await asyncio.sleep(1)
    await test_loader_only(session)
    await asyncio.sleep(1)
    await test_sequential_messages(session)
    await asyncio.sleep(1)
    await test_message_bottom_fade(session)


if __name__ == "__main__":
    from hud_server.tests.test_runner import run_interactive_test
    run_interactive_test(run_all_message_tests)

