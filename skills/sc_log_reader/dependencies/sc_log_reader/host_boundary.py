"""Windows process exclusion fences and process-lifetime runtime ownership.

No host imports, clocks, executable-name guesses, or host-session JSON authority.
The stable registry intentionally outlives adapter unload and module execution.
"""

from __future__ import annotations

import os
import sys
import threading
import types
from pathlib import Path

MAX_PIDS = 2048
_KEY = "_sc_log_reader_host_registry_v1"
_new = types.ModuleType(_KEY)
_new.lock = threading.RLock()
_new.runtimes = {}
# The pre-release name can still be loaded by an older saved configuration.
# Share its process-lifetime fence so the rename cannot create a second owner.
_registry = sys.modules.setdefault(
    _KEY, sys.modules.get("_sc_log_reader_2_host_registry_v1", _new)
)
sys.modules.setdefault("_sc_log_reader_2_host_registry_v1", _registry)


class WindowsBoundary:
    def identity(self):
        if os.name != "nt":
            return None
        import ctypes
        from ctypes import wintypes

        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.GetCurrentProcess.restype = wintypes.HANDLE
        api.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
            ctypes.POINTER(wintypes.FILETIME)
        ] * 4
        times = [wintypes.FILETIME() for _ in range(4)]
        if not api.GetProcessTimes(
            api.GetCurrentProcess(), *(ctypes.byref(t) for t in times)
        ):
            return None
        return os.getpid(), (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime

    def snapshot(self):
        if os.name != "nt":
            return None
        import ctypes
        from ctypes import wintypes

        class Entry(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        for name in ("Process32FirstW", "Process32NextW"):
            getattr(api, name).argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
        handle = api.CreateToolhelp32Snapshot(2, 0)
        if handle == ctypes.c_void_p(-1).value:
            return None
        try:
            entry = Entry()
            entry.dwSize = ctypes.sizeof(Entry)
            if not api.Process32FirstW(handle, ctypes.byref(entry)):
                return None
            pids = []
            while True:
                pids.append(int(entry.th32ProcessID))
                if len(pids) > MAX_PIDS:
                    return None
                if not api.Process32NextW(handle, ctypes.byref(entry)):
                    return pids if ctypes.get_last_error() == 18 else None
        finally:
            api.CloseHandle(handle)


def validate_boundary(value):
    if (
        not isinstance(value, dict)
        or type(value.get("version")) is not int
        or value.get("version") != 1
    ):
        raise ValueError("Invalid activation boundary")
    if value.get("kind") == "unresolved":
        return value
    pids = value.get("pids")
    if (
        value.get("kind") != "windows_pid_exclusion"
        or not isinstance(pids, list)
        or not 1 <= len(pids) <= MAX_PIDS
        or any(type(pid) is not int or not 0 <= pid <= 0xFFFFFFFF for pid in pids)
        or len(set(pids)) != len(pids)
    ):
        raise ValueError("Invalid activation boundary")
    return value


def capture_boundary(provider):
    try:
        value = {
            "version": 1,
            "kind": "windows_pid_exclusion",
            "pids": provider.snapshot(),
        }
        return validate_boundary(value)
    except (ValueError, OSError, TypeError):
        return {"version": 1, "kind": "unresolved"}


def _open_lease(root):
    root.mkdir(parents=True, exist_ok=True)
    stream = (root / "host-process.lock").open("a+b")
    try:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return stream
    except OSError as exc:
        stream.close()
        raise RuntimeError(
            "Runtime is owned by another monitor or Wingman process; close it or choose another runtime"
        ) from exc


class RuntimeOwner:
    def __init__(self, state):
        self.state = state
        self.released = False

    def pin(self, choose):
        with self.state["decision_lock"]:
            if self.state["decision"] is None:
                self.state["decision"] = choose()
            return self.state["decision"]

    def release(self):
        with _registry.lock:
            if not self.released:
                self.state["active"] = False
                self.released = True


def claim_runtime(runtime):
    root = Path(runtime).resolve()
    key = os.path.normcase(str(root))
    with _registry.lock:
        state = _registry.runtimes.get(key)
        if state is None:
            state = {
                "stream": _open_lease(root),
                "decision": None,
                "active": False,
                "decision_lock": threading.RLock(),
            }
            _registry.runtimes[key] = state
        if state["active"]:
            raise RuntimeError(
                "This runtime already has an active monitor; wait for cleanup"
            )
        state["active"] = True
        return RuntimeOwner(state)


class StandaloneOwner:
    """Monitor-lifetime lease; never a host process decision or registry entry."""

    def __init__(self, root, stream):
        self.root = root
        self.stream = stream

    def assert_held(self, runtime):
        if self.stream.closed or Path(runtime).resolve() != self.root:
            raise RuntimeError("Standalone startup requires its retained runtime lease")

    def release(self):
        self.stream.close()


def claim_standalone(runtime):
    root = Path(runtime).resolve()
    with _registry.lock:
        if os.path.normcase(str(root)) in _registry.runtimes:
            raise RuntimeError(
                "Runtime belongs to this Wingman process; standalone startup refused"
            )
        return StandaloneOwner(root, _open_lease(root))


def assert_standalone_available(runtime):
    owner = claim_standalone(runtime)
    owner.release()
