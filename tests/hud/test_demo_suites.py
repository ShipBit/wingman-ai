"""The HUD demos in hud_server/tests run against the HUD server without a
refused request or an error in the overlay. Headless: the server runs in this
process, is reached without a port and draws into windows never shown. All
suites share one server, as in the demo runner."""

import asyncio

from hud_server.tests.harness import Demo
from hud_server.tests.run_tests import SUITES


def test_the_demos_run_without_a_refused_request_or_an_overlay_error():
    async def run():
        async with Demo(headless=True) as demo:
            for suite in SUITES.values():
                await suite.run(demo)
                await demo.clean_up()
                await demo.settle()
        return demo

    demo = asyncio.run(run())

    assert demo.failures == []
    assert demo.overlay_errors == []
    assert demo.backend.presented > 0
