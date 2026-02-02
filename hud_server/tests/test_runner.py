"""
Test Runner - Utilities for running tests with the HUD server.
"""

import asyncio
from typing import Callable

from hud_server import HudServer
from hud_server.tests.test_session import TestSession, SESSION_CONFIGS


async def run_test(session: TestSession, test_func: Callable, *args, **kwargs):
    """Run a single async test on a session."""
    try:
        await test_func(session, *args, **kwargs)
    except Exception as e:
        print(f"[{session.name}] Test error: {e}")
        import traceback
        traceback.print_exc()


async def run_tests_sequential(sessions: list[TestSession], test_func: Callable, *args, **kwargs):
    """Run a test function on all sessions sequentially."""
    for session in sessions:
        await run_test(session, test_func, *args, **kwargs)


async def run_tests_parallel(sessions: list[TestSession], test_func: Callable, *args, **kwargs):
    """Run a test function on all sessions in parallel."""
    tasks = [run_test(session, test_func, *args, **kwargs) for session in sessions]
    await asyncio.gather(*tasks)


async def create_sessions(server_url: str = "http://127.0.0.1:7862",
                          session_ids: list[int] = None) -> list[TestSession]:
    """Create and connect test sessions."""
    if session_ids is None:
        session_ids = [1, 2, 3]

    sessions = []
    for sid in session_ids:
        if sid in SESSION_CONFIGS:
            session = TestSession(sid, SESSION_CONFIGS[sid], server_url)
            if await session.start():
                sessions.append(session)
    return sessions


async def cleanup_sessions(sessions: list[TestSession]):
    """Disconnect all sessions."""
    for session in sessions:
        await session.stop()


class TestContext:
    """Context manager for running tests with automatic server and session management."""

    def __init__(self, host: str = "127.0.0.1", port: int = 7862, session_ids: list[int] = None):
        self.host = host
        self.port = port
        self.session_ids = session_ids or [1]
        self.server: HudServer = None
        self.sessions: list[TestSession] = []

    async def __aenter__(self):
        # Start server
        self.server = HudServer()
        started = self.server.start(host=self.host, port=self.port)
        if not started:
            raise RuntimeError("Failed to start HUD server")

        # Create sessions
        base_url = f"http://{self.host}:{self.port}"
        self.sessions = await create_sessions(base_url, self.session_ids)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Cleanup sessions
        await cleanup_sessions(self.sessions)

        # Stop server
        if self.server:
            await self.server.stop()


def run_interactive_test(test_func: Callable, session_ids: list[int] = None):
    """Run a test interactively with automatic server management."""
    async def _run():
        async with TestContext(session_ids=session_ids or [1]) as ctx:
            for session in ctx.sessions:
                await test_func(session)

    asyncio.run(_run())

