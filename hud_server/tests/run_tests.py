"""Run the HUD demos: they drive a HUD server through its HTTP API and show
every feature on screen, then list what the server refused.

    python -m hud_server.tests.run_tests                # quick check: each element once
    python -m hud_server.tests.run_tests chat info      # some suites
    python -m hud_server.tests.run_tests --all          # every suite (not the game)
    python -m hud_server.tests.run_tests --list         # what there is
    python -m hud_server.tests.run_tests snake          # the Snake game

Options:
    --headless   in this process, no windows, no pauses: checks that every
                 request is accepted and nothing breaks the drawing
    --speed X    pauses X times shorter (2 = twice as fast)
    --port P     the HUD server's port (default 7862)
    --screen N   the monitor for a server started here (default 1)
    --no-web     skip pictures from the web

With Core running and its HUD on, the demos use Core's HUD server, in groups
of their own; Core's chat, info panel and settings are left as they were.
"""

import argparse
import asyncio
import sys

from hud_server.tests import (
    test_chat,
    test_images,
    test_info,
    test_layout,
    test_look,
    test_messages,
    test_multiuser,
    test_preview,
    test_profiles,
    test_settings,
    test_snake,
    test_unicode,
)
from hud_server.tests.harness import CHAT, INFO, MESSAGE, STYLE, Demo, area
from hud_server.types import WindowType

SUITES = {
    "messages": test_messages,
    "chat": test_chat,
    "info": test_info,
    "images": test_images,
    "layout": test_layout,
    "profiles": test_profiles,
    "look": test_look,
    "preview": test_preview,
    "settings": test_settings,
    "multiuser": test_multiuser,
    "unicode": test_unicode,
}
GAMES = {"snake": test_snake}

try:
    sys.stdout.reconfigure(line_buffering=True, errors="replace")
except AttributeError:
    pass  # stdout may be redirected and not support reconfigure


async def quick_check(demo: Demo) -> None:
    """Each element once: a message with tools and the loader, the chat, the
    info panel with a timer and a bar, the preview."""
    client = demo.client
    M, C, P = WindowType.MESSAGE, WindowType.CHAT, WindowType.PERSISTENT
    demo.check(await client.health_check(), "health check")
    await client.create_group(MESSAGE, M, {**STYLE, **area(40, 40, 520, 500)})
    await client.create_group(CHAT, C, {**STYLE, **area(580, 40, 1080, 600, "bottom")})
    await client.create_group(INFO, P, {**STYLE, **area(1140, 40, 1620, 600)})
    picture = demo.picture("Orionis", "#d84f4f")

    demo.scene("Message window", "an answer with a picture, tool chips and the loader")
    await client.show_loader(MESSAGE, M, True)
    await client.show_message(MESSAGE, M, "Orionis", "Landing granted on **pad 04**.", title_icon=picture, duration=30,
                              tools=[{"name": "status", "source": "Ship Status", "icon": None}] * 2)
    await demo.pause(3)
    await client.show_loader(MESSAGE, M, False)

    demo.scene("Chat flow", "your bubble on the right, the Wingman's answer with its picture")
    await client.send_chat_message(CHAT, C, "Jay", "Status?", own=True)
    await client.send_chat_message(CHAT, C, "Orionis", "All systems green.", icon=picture)
    await demo.pause(3)

    demo.scene("Info panel", "a countdown and a progress bar")
    await client.show_timer(INFO, P, "Quantum Spool", 20, auto_close=False)
    await client.show_progress(INFO, P, "Refinery Job", 40, 100, description="Processing Quantanium")
    await demo.pause(3)

    demo.scene("Preview", "the containers with sample content, framed")
    await client.set_preview({
        "chat": {**STYLE, **area(580, 640, 1080, 1000), "chat_flow": True, "sample_user": "Jay"},
        "info": {**STYLE, **area(1140, 640, 1620, 1000)},
    })
    await demo.pause(3)
    await client.clear_preview()


async def run_suites(names: list, options) -> int:
    results = []
    async with Demo(headless=options.headless, speed=options.speed, port=options.port, screen=options.screen,
                    web=not options.no_web) as demo:
        for name in names:
            module = SUITES.get(name) or GAMES.get(name)
            print("\n" + "=" * 60 + f"\n{module.TITLE if module else 'Quick check'}\n" + "=" * 60)
            failures, errors = len(demo.failures), len(demo.overlay_errors)
            try:
                await (module.run(demo) if module else quick_check(demo))
            except Exception as e:  # a broken demo should not hide the others
                demo.fail(f"{name} stopped: {type(e).__name__}: {e}")
            await demo.clean_up()
            await demo.settle()
            results.append((name, len(demo.failures) - failures, len(demo.overlay_errors) - errors))

    print("\n" + "=" * 60 + "\nSummary\n" + "=" * 60)
    for name, failures, errors in results:
        state = "ok" if not failures and not errors else f"{failures} refused, {errors} overlay errors"
        print(f"  {name:10s} {state}")
    for what in demo.failures:
        print(f"  refused: {what}")
    for what in demo.overlay_errors:
        print(f"  overlay: {what}")
    if not demo.own_server:
        print("  (Overlay errors of Core's HUD server are in Core's log.)")
    return 1 if demo.failures or demo.overlay_errors else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hud_server.tests.run_tests",
        description="Show the HUD's features on screen and check that the server accepts every request.",
    )
    parser.add_argument("suites", nargs="*", help=f"suites to run: {', '.join(SUITES)}, or the game: snake")
    parser.add_argument("--all", action="store_true", help="run every suite")
    parser.add_argument("--list", action="store_true", help="list the suites")
    parser.add_argument("--headless", action="store_true", help="no windows, no pauses")
    parser.add_argument("--speed", type=float, default=None, help="pauses this many times shorter")
    parser.add_argument("--port", type=int, default=7862)
    parser.add_argument("--screen", type=int, default=1)
    parser.add_argument("--no-web", action="store_true", help="skip pictures from the web")
    options = parser.parse_args(argv)

    if options.list:
        for name, module in {**SUITES, **GAMES}.items():
            print(f"  {name:10s} {module.TITLE}")
        return 0
    names = list(SUITES) if options.all else [n.lower() for n in options.suites] or ["quick"]
    unknown = [n for n in names if n != "quick" and n not in SUITES and n not in GAMES]
    if unknown:
        parser.error(f"unknown suite(s): {', '.join(unknown)}. Try --list.")
    return asyncio.run(run_suites(names, options))


if __name__ == "__main__":
    sys.exit(main())
