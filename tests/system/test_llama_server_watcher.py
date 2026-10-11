"""A llama-server must not outlive a Core that was killed instead of shut down."""

import os
import platform
import signal
import subprocess
import sys
import time

import pytest

from tests.support import REPO_ROOT

pytestmark = pytest.mark.skipif(
    platform.system() == "Windows", reason="Windows uses a Job Object instead"
)

# Stands in for Core: starts a long sleep as its "llama-server", watches it,
# prints the sleep's PID and waits to be killed.
FAKE_CORE = """
import subprocess, sys, time
from providers.llama_cpp_provider import _watch_parent
server = subprocess.Popen(["sleep", "60"])
_watch_parent(server)
print(server.pid, flush=True)
time.sleep(60)
"""


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_server_ends_when_core_is_killed():
    core = subprocess.Popen(
        [sys.executable, "-c", FAKE_CORE],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        text=True,
    )
    server_pid = int(core.stdout.readline())
    try:
        assert _alive(server_pid)
        core.send_signal(signal.SIGKILL)
        core.wait(timeout=5)

        deadline = time.monotonic() + 10
        while _alive(server_pid) and time.monotonic() < deadline:
            time.sleep(0.2)
        assert not _alive(server_pid)
    finally:
        if _alive(server_pid):
            os.kill(server_pid, signal.SIGKILL)
