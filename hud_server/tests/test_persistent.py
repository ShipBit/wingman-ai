# -*- coding: utf-8 -*-
"""
Test Persistent - Persistent info panel tests.
"""

import asyncio
from hud_server.tests.test_session import TestSession

# Emoji constants using Unicode escape sequences (avoids file encoding issues)
EMOJI_TARGET = "\U0001F3AF"    # 🎯
EMOJI_SHIELD = "\U0001F6E1\uFE0F"  # 🛡️
EMOJI_TIMER = "\u23F1\uFE0F"   # ⏱️


async def test_persistent_info(session: TestSession, delay: float = 2.0):
    """Test persistent info add/update/remove."""
    print(f"[{session.name}] Testing persistent info...")

    # Add items
    await session.add_persistent_info(f"{EMOJI_TARGET} Objective", "Deliver cargo to **Station Alpha**")
    await asyncio.sleep(delay)

    await session.add_persistent_info(f"{EMOJI_SHIELD} Shields", "Front: **100%** | Rear: *78%*")
    await asyncio.sleep(delay)

    await session.add_persistent_info(f"{EMOJI_TIMER} Timer", "Auto-remove in 5s", duration=5.0)
    await asyncio.sleep(delay)

    # Update
    await session.update_persistent_info(f"{EMOJI_SHIELD} Shields", "Front: **100%** | Rear: **95%** *(charging)*")
    await asyncio.sleep(delay)

    # Remove
    await session.remove_persistent_info(f"{EMOJI_TARGET} Objective")
    await asyncio.sleep(delay)

    # Wait for timer to expire
    await asyncio.sleep(3)

    await session.clear_all_persistent_info()
    print(f"[{session.name}] Persistent info test complete")


async def test_persistent_markdown(session: TestSession, delay: float = 3.0):
    """Test markdown in persistent info."""
    print(f"[{session.name}] Testing persistent markdown...")

    await session.add_persistent_info("Status", """**Online** - All systems go
- Power: `98%`
- Fuel: *67%*
- Hull: ~~damaged~~ **repaired**""")

    await asyncio.sleep(delay * 2)

    await session.add_persistent_info("Tasks", """1. [x] Launch sequence
2. [x] Clear atmosphere  
3. [ ] Set course
4. [ ] Engage autopilot""")

    await asyncio.sleep(delay * 2)
    await session.clear_all_persistent_info()
    print(f"[{session.name}] Persistent markdown test complete")


# =============================================================================
# Run All Tests
# =============================================================================

async def run_all_persistent_tests(session: TestSession):
    """Run all persistent tests."""
    await test_persistent_info(session)
    await asyncio.sleep(1)
    await test_persistent_markdown(session)
