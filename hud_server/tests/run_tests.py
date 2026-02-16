"""
Test script for HUD Server - Quick integration test and test suite runner.

Usage:
    python -m hud_server.tests.run_tests          # Run quick integration test
    python -m hud_server.tests.run_tests --all    # Run all test suites
    python -m hud_server.tests.run_tests --messages   # Run message tests
    python -m hud_server.tests.run_tests --progress   # Run progress tests
    python -m hud_server.tests.run_tests --persistent # Run persistent info tests
    python -m hud_server.tests.run_tests --chat       # Run chat tests
    python -m hud_server.tests.run_tests --unicode    # Run Unicode/emoji stress tests
    python -m hud_server.tests.run_tests --settings  # Run settings update tests
    python -m hud_server.tests.run_tests --layout     # Run layout manager unit tests (no server needed)
    python -m hud_server.tests.run_tests --layout-visual  # Run visual layout tests with actual HUD windows
    python -m hud_server.tests.run_tests --snake      # Run the Snake game (interactive, 2 min)
"""
import sys
import asyncio

try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass  # stdout may be redirected and not support reconfigure


def quick_test():
    """Quick integration test."""
    print("=" * 60)
    print("HUD Server Quick Integration Test")
    print("=" * 60)

    print("\nImporting HudServer...")
    from hud_server import HudServer

    print("Creating server instance...")
    server = HudServer()

    print("Starting server...")
    started = server.start()
    print(f"Server started: {started}")
    print(f"Server running: {server.is_running}")
    print(f"Base URL: {server.base_url}")

    print("\nTesting health endpoint...")
    import httpx
    try:
        response = httpx.get('http://127.0.0.1:7862/health', timeout=5.0)
        print(f"Health response: {response.json()}")
    except Exception as e:
        print(f"Health check failed: {e}")

    print("\nTesting message endpoint...")
    try:
        response = httpx.post('http://127.0.0.1:7862/message', json={
            'group_name': 'test',
            'title': 'Test',
            'content': 'Hello World'
        }, timeout=5.0)
        print(f"Message response: {response.json()}")
    except Exception as e:
        print(f"Message failed: {e}")

    print("\nChecking groups...")
    try:
        response = httpx.get('http://127.0.0.1:7862/groups', timeout=5.0)
        print(f"Groups: {response.json()}")
    except Exception as e:
        print(f"Groups failed: {e}")

    print("\nStopping server...")
    asyncio.run(server.stop())
    print("Server stopped")

    print("\n" + "=" * 60)
    print("Quick test complete!")
    print("=" * 60)


async def run_test_suite(test_name: str):
    """Run a specific test suite."""
    from hud_server.tests.test_runner import TestContext

    print(f"\n{'=' * 60}")
    print(f"Running {test_name} tests...")
    print(f"{'=' * 60}\n")

    async with TestContext(session_ids=[1]) as ctx:
        session = ctx.sessions[0]

        if test_name == "messages":
            from hud_server.tests.test_messages import run_all_message_tests
            await run_all_message_tests(session)
        elif test_name == "progress":
            from hud_server.tests.test_progress import run_all_progress_tests
            await run_all_progress_tests(session)
        elif test_name == "persistent":
            from hud_server.tests.test_persistent import run_all_persistent_tests
            await run_all_persistent_tests(session)
        elif test_name == "chat":
            from hud_server.tests.test_chat import run_all_chat_tests
            await run_all_chat_tests(session)
        elif test_name == "settings":
            from hud_server.tests.test_settings import run_all_settings_tests
            await run_all_settings_tests(session)
        elif test_name == "unicode":
            from hud_server.tests.test_unicode_stress import run_all_unicode_stress_tests
            await run_all_unicode_stress_tests(session)
        elif test_name == "all":
            from hud_server.tests.test_messages import run_all_message_tests
            from hud_server.tests.test_progress import run_all_progress_tests
            from hud_server.tests.test_persistent import run_all_persistent_tests
            from hud_server.tests.test_chat import run_all_chat_tests
            from hud_server.tests.test_unicode_stress import run_all_unicode_stress_tests
            from hud_server.tests.test_settings import run_all_settings_tests

            await run_all_message_tests(session)
            await asyncio.sleep(2)
            await run_all_progress_tests(session)
            await asyncio.sleep(2)
            await run_all_persistent_tests(session)
            await asyncio.sleep(2)
            await run_all_chat_tests(session)
            await asyncio.sleep(2)
            await run_all_unicode_stress_tests(session)
            await asyncio.sleep(2)
            await run_all_settings_tests(session)

    print(f"\n{'=' * 60}")
    print(f"{test_name.capitalize()} tests complete!")
    print(f"{'=' * 60}")


def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower().replace("--", "").replace("-", "_")
        if arg == "layout":
            # Layout unit tests don't need a server
            from hud_server.tests.test_layout import run_all_tests
            success = run_all_tests()
            sys.exit(0 if success else 1)
        elif arg == "layout_visual":
            # Visual layout tests need the full server
            from hud_server.tests.test_layout_visual import main as layout_visual_main
            asyncio.run(layout_visual_main())
        elif arg == "snake":
            # Snake game - interactive fun test
            from hud_server.tests.test_snake import run_snake_test
            asyncio.run(run_snake_test())
        elif arg in ["messages", "progress", "persistent", "chat", "unicode", "settings", "all"]:
            asyncio.run(run_test_suite(arg))
        elif arg == "help":
            print(__doc__)
        else:
            print(f"Unknown argument: {arg}")
            print(__doc__)
    else:
        quick_test()


if __name__ == "__main__":
    main()


