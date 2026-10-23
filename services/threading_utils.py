"""Threading helpers used across wingmen and skills."""

import asyncio
import threading
import traceback

from api.enums import LogType
from services.printr import Printr

printr = Printr()


def threaded_execution(function, *args) -> threading.Thread | None:
    """Run ``function`` in a fresh daemon thread.

    If ``function`` is a coroutine function, a new event loop is created
    inside the thread to run it. Otherwise it is called directly.

    Returns the started thread, or ``None`` on failure.
    """
    try:

        def start_thread(function, *args):
            if asyncio.iscoroutinefunction(function):
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                new_loop.run_until_complete(function(*args))
                new_loop.close()
            else:
                function(*args)

        thread = threading.Thread(target=start_thread, args=(function, *args))
        thread.name = function.__name__
        thread.daemon = True
        thread.start()
        return thread
    except Exception as e:
        printr.print(
            f"Error starting threaded execution: {str(e)}", color=LogType.ERROR
        )
        printr.print(traceback.format_exc(), color=LogType.ERROR, server_only=True)
        return None
