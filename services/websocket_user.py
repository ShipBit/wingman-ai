import asyncio
from services.connection_manager import ConnectionManager


class WebSocketUser:
    _connection_manager: ConnectionManager = None

    @classmethod
    def set_connection_manager(cls, connection_manager: ConnectionManager):
        if cls._connection_manager is None:
            cls._connection_manager = connection_manager
        else:
            raise ValueError(
                "connection_manager can only be set once during the singleton lifetime of Printr."
            )

    @classmethod
    def ensure_async(cls, coro):
        try:
            loop = asyncio.get_running_loop()
            # If we're in a running loop, just create a task
            return loop.create_task(coro)
        except RuntimeError:
            # No running loop, so we need to run one
            return asyncio.run(coro)
