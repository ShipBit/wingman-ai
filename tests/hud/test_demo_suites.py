"""The HUD demos in hud_server/tests run against the HUD server without a
refused request or an error in the overlay. Headless: the server runs in this
process, is reached without a port and draws into windows never shown."""

import asyncio

import pytest

from hud_server.tests.harness import Demo
from hud_server.tests.run_tests import SUITES


@pytest.mark.parametrize("name", list(SUITES))
def test_a_demo_runs_without_a_refused_request_or_an_overlay_error(name):
    async def run():
        async with Demo(headless=True) as demo:
            await SUITES[name].run(demo)
            await demo.settle()
        return demo

    demo = asyncio.run(run())

    assert demo.failures == []
    assert demo.overlay_errors == []
    assert demo.backend.presented > 0
