"""Key presses and mouse actions for a window that runs as administrator.

Windows drops simulated input from a normal program when the window in front
belongs to an elevated one (UIPI). Star Citizen is often started that way by
its launcher, and then no command of a Wingman reaches the game.

Windows has a right made for this, UIAccess: a signed program installed under
Program Files may send input to every window, without admin rights and without
asking the user. Core does not take it for itself, because everything Core
starts would inherit it. A small program next to Core has it instead,
WingmanAiInput.exe (input_helper.py, built by WingmanAiCore.spec). Core starts
it once at startup and hands it the input for elevated windows. Everything
else keeps the direct way.

The same wall stands in the other direction: while an elevated window is in
front, Core's keyboard and mouse hooks see nothing, so push-to-talk and every
other key binding are dead. For that time the helper listens in Core's place
and passes the keys and mouse buttons on.

Nothing here may get in the way of the game: no prompt, no window, no input
that waits for the helper, and no hook that waits for Core.
"""

import ctypes
import json
import os
import platform
import queue
import secrets
import sys
import threading
import time
from contextlib import suppress
from ctypes import wintypes
from multiprocessing.connection import Client, Listener
from os import path

from keyboard.keyboard._keyboard_event import KEY_DOWN, KEY_UP, KeyboardEvent
from mouse.mouse._mouse_event import ButtonEvent

HELPER_NAME = "WingmanAiInput.exe"
CORE_NAME = "WingmanAiCore.exe"
PIPE_PREFIX = "\\\\.\\pipe\\WingmanAiInput-"

# What the helper does for Core: the module, its function and the arguments
# the function takes. The helper runs nothing else.
ACTIONS = {
    "key": ("keyboard", "_send_event", (int, int)),
    "text": ("keyboard", "type_unicode", (str,)),
    "mouse_down": ("mouse", "press", (str,)),
    "mouse_up": ("mouse", "release", (str,)),
    "wheel": ("mouse", "wheel", ((int, float),)),
    "move_to": ("mouse", "move_to", ((int, float), (int, float))),
    "move_by": ("mouse", "move_relative", ((int, float), (int, float))),
}

# Core tells the helper when to listen: which of the two hooks it needs now.
LISTEN = "listen"

CONNECT_SECONDS = 30
# How often Core looks at the window in front to switch the listening, and
# how often it repeats "listen" so that a hook that ended on its own comes back.
WATCH_SECONDS = 0.1
REPEAT_SECONDS = 2
MAX_MESSAGE_BYTES = 4096
# A helper that keeps dying is not started again and again.
MAX_STARTS = 3

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_ELEVATION = 20
INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
SW_HIDE = 0
WM_APP = 0x8000


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("mi", _MOUSEINPUT)]


class _Windows:
    """The Windows calls used here, with their handle types declared: a handle
    is 64 bits wide and ctypes would cut it to 32 otherwise."""

    def __init__(self):
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self.shell32 = ctypes.WinDLL("shell32", use_last_error=True)

        k, u, a = self.kernel32, self.user32, self.advapi32
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        k.GetNamedPipeServerProcessId.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.ULONG),
        ]
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
        u.SendInput.restype = wintypes.UINT
        u.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        a.OpenProcessToken.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        a.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]


_windows_calls = None


def _windows() -> _Windows:
    global _windows_calls
    if _windows_calls is None:
        _windows_calls = _Windows()
    return _windows_calls


def _log(text: str, warn_user: bool = False) -> None:
    # Imported here: the helper never logs and must start fast.
    from services.printr import Printr

    printr = Printr()
    if warn_user:
        printr.toast_warning(text)
    else:
        printr.print(text, server_only=True)


# ─────────────────────────────── Windows facts ───────────────────────────────


def _process_path(pid: int) -> str | None:
    kernel32 = _windows().kernel32
    process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return None
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
            return None
        return path.normcase(buffer.value)
    finally:
        kernel32.CloseHandle(process)


def _runs_elevated(pid: int) -> bool:
    """True only when Windows says so. A process that cannot be asked counts
    as not elevated: the probe in _out_of_reach decides for it."""
    win = _windows()
    process = win.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return False
    try:
        token = wintypes.HANDLE()
        if not win.advapi32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
            return False
        try:
            elevated = wintypes.DWORD(0)
            size = wintypes.DWORD(0)
            known = win.advapi32.GetTokenInformation(
                token, TOKEN_ELEVATION, ctypes.byref(elevated), ctypes.sizeof(elevated), ctypes.byref(size)
            )
            return bool(known and elevated.value)
        finally:
            win.kernel32.CloseHandle(token)
    finally:
        win.kernel32.CloseHandle(process)


def _input_is_refused() -> bool:
    """Sends a mouse move of zero pixels. Windows accepts it for a normal
    window and refuses it for an elevated one."""
    probe = _INPUT(type=INPUT_MOUSE, mi=_MOUSEINPUT(dwFlags=MOUSEEVENTF_MOVE))
    return _windows().user32.SendInput(1, ctypes.byref(probe), ctypes.sizeof(probe)) == 0


_reach_by_pid: dict[int, bool] = {}


def _out_of_reach() -> bool:
    """Whether the window in front belongs to a program Core cannot send to.
    Asked once per program: a running program does not change its rights."""
    user32 = _windows().user32
    window = user32.GetForegroundWindow()
    if not window:
        return False
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
    if not pid.value or pid.value == os.getpid():
        return False
    blocked = _reach_by_pid.get(pid.value)
    if blocked is None:
        if len(_reach_by_pid) > 256:
            _reach_by_pid.clear()
        blocked = _runs_elevated(pid.value) or _input_is_refused()
        _reach_by_pid[pid.value] = blocked
    return blocked


# ──────────────────────────────── Core side ──────────────────────────────────


def _helper_path() -> str | None:
    """The helper is built and signed with Core and installed next to it.
    Core run from source has none."""
    if not getattr(sys, "frozen", False):
        return None
    helper = path.join(path.dirname(sys.executable), HELPER_NAME)
    return helper if path.isfile(helper) else None


def _accept(listener: Listener, address: str, timeout: float):
    """listener.accept() with a time limit, which a pipe does not have."""
    accepted = []

    def wait():
        with suppress(OSError, EOFError):
            accepted.append(listener.accept())

    waiting = threading.Thread(target=wait, daemon=True)
    waiting.start()
    waiting.join(timeout)
    if not waiting.is_alive():
        return accepted[0] if accepted else None
    # Nobody came. Connect ourselves so the waiting thread ends.
    with suppress(OSError):
        Client(address, family="AF_PIPE").close()
    waiting.join(2)
    for connection in accepted:
        connection.close()
    return None


class ElevatedInput:
    """Core's end of the helper. Input never waits for it: while the helper is
    not there, send() says no and the input goes the direct way."""

    def __init__(self):
        self._connection = None
        self._starting: threading.Thread | None = None
        self._starts = 0
        self._warned = False
        self._lock = threading.Lock()

    def start(self) -> None:
        """Brings the helper up in the background."""
        with self._lock:
            if self._connection is not None or self._starts >= MAX_STARTS:
                return
            if self._starting is not None and self._starting.is_alive():
                return
            self._starts += 1
            self._starting = threading.Thread(target=self._bring_up, daemon=True)
            self._starting.start()

    def send(self, action: str, arguments: tuple) -> bool:
        """True when the helper took the input."""
        connection = self._connection
        if connection is None:
            self.start()
            self._warn_once()
            return False
        return self._write(connection, action, arguments)

    def _write(self, connection, action: str, arguments: tuple) -> bool:
        try:
            with self._lock:
                connection.send_bytes(json.dumps([action, *arguments]).encode())
            return True
        except (OSError, ValueError, TypeError):
            self._lost(connection)
            return False

    def _lost(self, connection) -> None:
        """The helper is gone. A new one comes up in the background."""
        if self._connection is connection:
            self._connection = None
        with suppress(OSError):
            connection.close()
        self.start()

    def _read(self, connection) -> None:
        """What the helper hears while an elevated window is in front goes to
        the listeners of the keyboard and mouse libraries, as if Core's own
        hooks had heard it."""
        import keyboard.keyboard as keyboard
        import mouse.mouse as mouse

        while True:
            try:
                message = connection.recv_bytes(MAX_MESSAGE_BYTES)
            except (OSError, EOFError):
                self._lost(connection)
                return
            receive(message, keyboard._listener.direct_callback, mouse._listener.queue.put)

    def _watch(self, connection) -> None:
        """Keeps the helper listening exactly while an elevated window is in
        front. The mouse hook only when Core has one itself."""
        import mouse.mouse as mouse

        told, told_at = (False, False), 0.0
        while self._connection is connection:
            blocked = _out_of_reach()
            wanted = (blocked, blocked and bool(mouse._listener.handlers))
            now = time.monotonic()
            if wanted != told or (any(wanted) and now - told_at > REPEAT_SECONDS):
                if not self._write(connection, LISTEN, wanted):
                    return
                told, told_at = wanted, now
            time.sleep(WATCH_SECONDS)

    def _warn_once(self) -> None:
        starting = self._starting is not None and self._starting.is_alive()
        if self._warned or starting:
            return
        self._warned = True
        _log(
            "The program in front runs as administrator, so Windows blocks Wingman's key presses and "
            "commands do not reach it. Push-to-talk keys do not work in it either. Install Wingman into its default folder under Program Files, "
            "or start the game without administrator rights.",
            warn_user=True,
        )

    def _bring_up(self) -> None:
        helper = _helper_path()
        if helper is None:
            self._starts = MAX_STARTS
            return
        address = PIPE_PREFIX + secrets.token_hex(16)
        try:
            listener = Listener(address, family="AF_PIPE")
        except OSError as error:
            _log(f"Input helper: no pipe ({error}).")
            return
        try:
            try:
                # Through the shell: Windows grants UIAccess only on that way.
                os.startfile(helper, arguments=address, show_cmd=SW_HIDE)
            except OSError as error:
                # Not signed, or not installed under Program Files.
                self._starts = MAX_STARTS
                _log(f"Input helper: Windows did not start {helper} ({error}).")
                return
            connection = _accept(listener, address, CONNECT_SECONDS)
        finally:
            listener.close()
        try:
            if connection is None or not connection.poll(CONNECT_SECONDS):
                raise EOFError
            if connection.recv_bytes(MAX_MESSAGE_BYTES) != b"ready":
                raise EOFError
        except (OSError, EOFError):
            if connection is not None:
                connection.close()
            _log("Input helper: started, but did not report ready.")
            return
        self._connection = connection
        threading.Thread(target=self._read, args=(connection,), daemon=True).start()
        threading.Thread(target=self._watch, args=(connection,), daemon=True).start()
        _log("Input helper is ready: commands and key bindings also work in programs that run as administrator.")


_elevated_input = ElevatedInput()


def routed(action: str, direct):
    """`direct`, unless the window in front needs the helper and it took over."""

    def send(*arguments):
        if _out_of_reach() and _elevated_input.send(action, arguments):
            return None
        return direct(*arguments)

    return send


def _os_modules() -> dict:
    from keyboard.keyboard import _winkeyboard
    from mouse.mouse import _winmouse

    return {"keyboard": _winkeyboard, "mouse": _winmouse}


def install() -> None:
    """Called once when Core starts. An elevated Core reaches every window."""
    if platform.system() != "Windows":
        return
    try:
        if _windows().shell32.IsUserAnAdmin():
            return
        modules = _os_modules()
        wrapped = {
            action: routed(action, getattr(modules[module], function))
            for action, (module, function, _signature) in ACTIONS.items()
        }
    except Exception as error:
        # Core must start without it: input then goes the direct way only.
        _log(f"Input for elevated windows is off: {error}")
        return
    for action, (module, function, _signature) in ACTIONS.items():
        setattr(modules[module], function, wrapped[action])
    # Now, not at the first command: the game must not wait for the helper.
    _elevated_input.start()


# ─────────────────────────────── helper side ─────────────────────────────────


def key_message(event: KeyboardEvent) -> bytes:
    return json.dumps(
        ["key", event.event_type, event.scan_code, event.name, event.is_keypad, event.is_extended]
    ).encode()


def button_message(event: ButtonEvent) -> bytes:
    return json.dumps(["button", event.event_type, event.button]).encode()


def receive(message: bytes, on_key, on_button) -> bool:
    """Core's side: turns one message of the listening helper back into the
    event it was."""
    try:
        kind, *fields = json.loads(message)
        if kind == "key":
            event_type, scan_code, name, is_keypad, is_extended = fields
            if event_type not in (KEY_DOWN, KEY_UP) or not isinstance(scan_code, int):
                return False
            if not isinstance(name, (str, type(None))):
                return False
            on_key(KeyboardEvent(event_type, scan_code, name=name, is_keypad=is_keypad, is_extended=is_extended))
        elif kind == "button":
            event_type, button = fields
            if not isinstance(event_type, str) or not isinstance(button, str):
                return False
            on_button(ButtonEvent(event_type, button, time.time()))
        else:
            return False
    except (ValueError, TypeError):
        return False
    return True


class _Listening:
    """The helper's hooks, one thread each, on only while Core asks for them.

    A hook must return at once or every key in the game lags, so it only puts
    the event into a queue. Another thread writes the queue to Core."""

    def __init__(self, modules: dict, connection):
        self._connection = connection
        self._outbox = queue.SimpleQueue()
        self._threads: dict[str, threading.Thread] = {}
        self._hooks = {
            "keyboard": lambda: modules["keyboard"].listen(self._on_key),
            # The mouse hook fills a queue: put() below.
            "mouse": lambda: modules["mouse"].listen(self),
        }
        threading.Thread(target=self._write, daemon=True).start()

    def set(self, keyboard: bool, mouse: bool) -> None:
        for device, wanted in (("keyboard", keyboard), ("mouse", mouse)):
            thread = self._threads.get(device)
            running = thread is not None and thread.is_alive()
            if wanted and not running:
                self._threads[device] = threading.Thread(target=self._hooks[device], daemon=True)
                self._threads[device].start()
            elif running and not wanted:
                self._stop(thread)

    def _stop(self, thread: threading.Thread) -> None:
        """The hook loop of both libraries ends with the first message its
        thread gets, and Windows removes a hook with its thread."""
        post = _windows().user32.PostThreadMessageW
        for _attempt in range(100):
            if not thread.is_alive():
                return
            # Fails until the thread has its message queue, hence the loop.
            post(thread.native_id, WM_APP, 0, 0)
            thread.join(0.02)

    def _on_key(self, event: KeyboardEvent) -> bool:
        self._outbox.put(key_message(event))
        return True

    def put(self, event) -> None:
        if isinstance(event, ButtonEvent):
            self._outbox.put(button_message(event))

    def _write(self) -> None:
        while True:
            try:
                self._connection.send_bytes(self._outbox.get())
            except (OSError, ValueError):
                return


def _fits(argument, kind) -> bool:
    if isinstance(argument, bool):
        return kind is bool
    return isinstance(argument, kind)


def perform(message: bytes, functions: dict) -> bool:
    """Runs one message from Core. Anything that is not exactly a known action
    with the arguments it takes is dropped."""
    try:
        action, *arguments = json.loads(message)
        signature = (bool, bool) if action == LISTEN else ACTIONS[action][2]
    except (ValueError, TypeError, KeyError):
        return False
    if len(arguments) != len(signature):
        return False
    if not all(_fits(argument, kind) for argument, kind in zip(arguments, signature)):
        return False
    try:
        functions[action](*arguments)
    except Exception:
        return False
    return True


def _serves_core(connection) -> bool:
    """Whether the other end of the pipe is the Core installed next to the
    helper. Any program can start the helper, only that Core may use it."""
    server = wintypes.ULONG(0)
    if not _windows().kernel32.GetNamedPipeServerProcessId(connection.fileno(), ctypes.byref(server)):
        return False
    own = _process_path(os.getpid())
    if own is None:
        return False
    return _process_path(server.value) == path.join(path.dirname(own), path.normcase(CORE_NAME))


def run_helper(arguments: list[str]) -> int:
    """WingmanAiInput.exe, started with the pipe of its Core. Ends when Core does."""
    if platform.system() != "Windows" or len(arguments) != 1 or not arguments[0].startswith(PIPE_PREFIX):
        return 1
    try:
        connection = Client(arguments[0], family="AF_PIPE")
    except OSError:
        return 1
    if not _serves_core(connection):
        return 1
    try:
        connection.send_bytes(b"ready")
    except OSError:
        return 1

    modules = _os_modules()
    modules["keyboard"].init()
    functions = {
        action: getattr(modules[module], function) for action, (module, function, _signature) in ACTIONS.items()
    }
    functions[LISTEN] = _Listening(modules, connection).set
    while True:
        try:
            message = connection.recv_bytes(MAX_MESSAGE_BYTES)
        except (OSError, EOFError):
            return 0
        perform(message, functions)
