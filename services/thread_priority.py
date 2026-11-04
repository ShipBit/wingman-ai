"""Below normal priority for short CPU work that runs while the user plays,
like a screenshot and its JPEG. Windows schedules the game's threads first, so
a busy CPU makes the work a little slower instead of the game stutter.

Only on Windows; elsewhere the work runs as it is. The work runs in a thread
of asyncio's pool, so the thread gets its old priority back afterwards.
"""

import platform
from contextlib import contextmanager

THREAD_PRIORITY_BELOW_NORMAL = -1


@contextmanager
def below_normal_priority():
    if platform.system() != "Windows":
        yield
        return
    import ctypes

    kernel32 = ctypes.windll.kernel32
    thread = kernel32.GetCurrentThread()
    previous = kernel32.GetThreadPriority(thread)
    kernel32.SetThreadPriority(thread, THREAD_PRIORITY_BELOW_NORMAL)
    try:
        yield
    finally:
        kernel32.SetThreadPriority(thread, previous)
