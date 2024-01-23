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
    def ensure_async(self, coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Create a new event loop if one isn't running
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            # If the loop is running, create a task
            task = loop.create_task(coro)
        else:
            # If there's no running loop, we need to run the loop until the coro completes
            task = loop.run_until_complete(coro)

        return task
