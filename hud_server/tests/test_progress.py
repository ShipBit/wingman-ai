# -*- coding: utf-8 -*-
"""
Test Progress - Progress bars and timer tests.
"""
import asyncio
from hud_server.tests.test_session import TestSession

# Emoji constants using Unicode escape sequences (avoids file encoding issues)
EMOJI_DOWNLOAD = "\U0001F4E5"  # 📥
EMOJI_BATTERY = "\U0001F50B"   # 🔋
EMOJI_SATELLITE = "\U0001F4E1" # 📡
EMOJI_TIMER = "\u23F1\uFE0F"   # ⏱️
EMOJI_REFRESH = "\U0001F504"   # 🔄

async def test_progress_bars(session: TestSession, delay: float = 0.3):
    print(f"[{session.name}] Testing progress bars...")
    await session.show_progress(f"{EMOJI_DOWNLOAD} Download", 0, 100, "Starting download...")
    for i in range(0, 101, 10):
        await session.show_progress(f"{EMOJI_DOWNLOAD} Download", i, 100, f"Downloading... {i}%")
        await asyncio.sleep(delay)
    await asyncio.sleep(1)
    await session.remove_persistent_info(f"{EMOJI_DOWNLOAD} Download")
    await session.show_progress(f"{EMOJI_BATTERY} Charging", 0, 100, "Battery", progress_color="#4cd964")
    await session.show_progress(f"{EMOJI_SATELLITE} Upload", 0, 500, "Sending data", progress_color="#ff9500")
    for i in range(10):
        await session.show_progress(f"{EMOJI_BATTERY} Charging", i * 10, 100)
        await session.show_progress(f"{EMOJI_SATELLITE} Upload", i * 50, 500)
        await asyncio.sleep(delay)
    await asyncio.sleep(1)
    await session.clear_all_persistent_info()
    print(f"[{session.name}] Progress bars test complete")

async def test_timers(session: TestSession):
    print(f"[{session.name}] Testing timers...")
    await session.show_timer(f"{EMOJI_TIMER} Cooldown", 5.0, "Jump drive charging...", auto_close=True)
    await asyncio.sleep(2)
    await session.show_timer(f"{EMOJI_REFRESH} Scan", 8.0, "Scanning area...", auto_close=False, progress_color="#9b59b6")
    await asyncio.sleep(6)
    await session.remove_persistent_info(f"{EMOJI_REFRESH} Scan")
    await asyncio.sleep(2)
    await session.clear_all_persistent_info()
    print(f"[{session.name}] Timers test complete")
async def test_auto_close(session: TestSession):
    print(f"[{session.name}] Testing auto-close...")
    await session.show_progress("Auto-Close Test", 0, 100, "Will auto-close at 100%", auto_close=True)
    for i in range(0, 101, 25):
        await session.show_progress("Auto-Close Test", i, 100, f"Progress: {i}%", auto_close=True)
        await asyncio.sleep(0.5)
    await asyncio.sleep(3)
    print(f"[{session.name}] Auto-close test complete")
async def run_all_progress_tests(session: TestSession):
    await test_progress_bars(session)
    await asyncio.sleep(1)
    await test_timers(session)
    await asyncio.sleep(1)
    await test_auto_close(session)
