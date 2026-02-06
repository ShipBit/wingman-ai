"""
Test Runner - Utilities for running tests with the HUD server.
"""

import asyncio
import httpx
from typing import Callable, Optional

from hud_server import HudServer
from hud_server.tests.test_session import TestSession, SESSION_CONFIGS


async def check_server_running(host: str = "127.0.0.1", port: int = 7862, timeout: float = 2.0) -> bool:
    """
    Check if a HUD server is already running at the specified host/port.

    Args:
        host: Host to check
        port: Port to check
        timeout: Request timeout in seconds

    Returns:
        True if server is running and responding to health checks
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"http://{host}:{port}/health")
            return response.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException, Exception):
        return False


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
        self.server: Optional[HudServer] = None
        self.sessions: list[TestSession] = []
        self.server_was_running = False  # Track if we started the server or it was already running

    async def __aenter__(self):
        # Check if server is already running
        self.server_was_running = await check_server_running(self.host, self.port)

        if not self.server_was_running:
            # Start our own server
            print(f"[TestContext] Starting HUD server at {self.host}:{self.port}")
            self.server = HudServer()
            started = self.server.start(host=self.host, port=self.port)
            if not started:
                raise RuntimeError("Failed to start HUD server")
        else:
            print(f"[TestContext] Using existing HUD server at {self.host}:{self.port}")

        # Create sessions
        base_url = f"http://{self.host}:{self.port}"
        self.sessions = await create_sessions(base_url, self.session_ids)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Cleanup sessions
        await cleanup_sessions(self.sessions)

        # Stop server only if we started it
        if self.server and not self.server_was_running:
            print("[TestContext] Stopping HUD server (we started it)")
            await self.server.stop()
        elif self.server_was_running:
            print("[TestContext] Leaving existing HUD server running")


def run_interactive_test(test_func: Callable, session_ids: list[int] = None,
                        host: str = "127.0.0.1", port: int = 7862):
    """Run a test interactively with automatic server management."""
    async def _run():
        async with TestContext(host=host, port=port, session_ids=session_ids or [1]) as ctx:
            for session in ctx.sessions:
                await test_func(session)

    asyncio.run(_run())


async def run_test_with_existing_server_check(test_func: Callable,
                                            host: str = "127.0.0.1", port: int = 7862,
                                            session_ids: list[int] = None):
    """
    Run a test, checking for an existing server first.

    This is useful for running tests when a HUD server might already be running
    (e.g., during development or when multiple tests are run in sequence).
    """
    async with TestContext(host=host, port=port, session_ids=session_ids or [1]) as ctx:
        print(f"[Test] Running test with {len(ctx.sessions)} session(s)")
        for session in ctx.sessions:
            await test_func(session)


