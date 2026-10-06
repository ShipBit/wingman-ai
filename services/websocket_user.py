import asyncio
from typing import Optional

from services.connection_manager import ConnectionManager


class WebSocketUser:
    _connection_manager: ConnectionManager = None
    _main_loop: Optional[asyncio.AbstractEventLoop] = None

    @classmethod
    def set_connection_manager(cls, connection_manager: ConnectionManager):
        if cls._connection_manager is None:
            cls._connection_manager = connection_manager
        else:
            raise ValueError(
                "connection_manager can only be set once during the singleton lifetime of Printr."
            )

    @classmethod
    def set_main_loop(cls, loop: asyncio.AbstractEventLoop) -> None:
        cls._main_loop = loop

    @classmethod
    def ensure_async(cls, coro):
        """Run a coroutine, no matter which thread the caller lives on.

        WebSockets belong to the main loop. Writing to them from a worker thread
        (hotkey, audio, FastAPI threadpool) corrupts asyncio's shared transport
        buffer - with a large payload in flight it raises
        "BufferError: Existing exports of data: object cannot be re-sized".
        So anything from a foreign thread is handed back to the main loop."""
        main_loop = cls._main_loop

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is not None and (main_loop is None or running_loop is main_loop):
            return running_loop.create_task(coro)

        if main_loop is not None and main_loop.is_running():
            return asyncio.run_coroutine_threadsafe(coro, main_loop)

        if running_loop is not None:
            return running_loop.create_task(coro)

        # Pre-startup only; no clients are connected yet.
        return asyncio.run(coro)
