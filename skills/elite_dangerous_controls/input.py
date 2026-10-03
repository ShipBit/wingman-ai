"""Checked Windows physical-key input. Importable without Windows dependencies."""

import asyncio
import ctypes
import os
from pathlib import Path
import platform
import threading
import time


# Elite Key_* identifiers describe physical positions. Never translate through
# Wingman's current text layout or collapse E0 keys into keypad keys.
SCAN = {}
for names, start in (("1 2 3 4 5 6 7 8 9 0", 2), ("Q W E R T Y U I O P", 16),
                     ("A S D F G H J K L", 30), ("Z X C V B N M", 44)):
    SCAN.update({"Key_" + key: (start + i, False) for i, key in enumerate(names.split())})
SCAN.update({"Key_F" + str(i): (58 + i, False) for i in range(1, 11)})
SCAN.update({"Key_" + key: (code, False) for key, code in {
    "Escape": 1, "Minus": 12, "Equals": 13, "Backspace": 14, "Tab": 15,
    "LeftBracket": 26, "RightBracket": 27, "Return": 28, "LeftControl": 29,
    "Semicolon": 39, "Apostrophe": 40, "Grave": 41, "LeftShift": 42,
    "BackSlash": 43, "Comma": 51, "Period": 52, "Slash": 53,
    "RightShift": 54, "Numpad_Multiply": 55, "LeftAlt": 56, "Space": 57,
    "CapsLock": 58, "NumLock": 69, "ScrollLock": 70, "Numpad_7": 71,
    "Numpad_8": 72, "Numpad_9": 73, "Numpad_Subtract": 74, "Numpad_4": 75,
    "Numpad_5": 76, "Numpad_6": 77, "Numpad_Add": 78, "Numpad_1": 79,
    "Numpad_2": 80, "Numpad_3": 81, "Numpad_0": 82, "Numpad_Decimal": 83,
    "F11": 87, "F12": 88, "OEM_102": 86,
}.items()})
SCAN.update({"Key_" + key: (code, True) for key, code in {
    "Numpad_Enter": 28, "RightControl": 29, "Numpad_Divide": 53, "RightAlt": 56,
    "Home": 71, "UpArrow": 72, "PageUp": 73, "LeftArrow": 75,
    "RightArrow": 77, "End": 79, "DownArrow": 80, "PageDown": 81,
    "Insert": 82, "Delete": 83,
}.items()})
MODIFIERS = {"Key_LeftControl", "Key_RightControl", "Key_LeftShift", "Key_RightShift",
             "Key_LeftAlt", "Key_RightAlt"}
MOUSE = {"Mouse_1": (2, 4, 1), "Mouse_2": (8, 16, 2), "Mouse_3": (32, 64, 4),
         "Mouse_4": (128, 256, 5), "Mouse_5": (128, 256, 6)}
INPUT_LOCK = threading.Lock()


class InputBlocked(ValueError):
    def __init__(self, message, stage=None):
        super().__init__(message)
        self.stage = stage


def key_event(key, release=False):
    code, extended = SCAN[key]
    return {"scan": code, "flags": 8 | int(extended) | (2 if release else 0)}


class WindowsInput:
    def __init__(self):
        if platform.system() != "Windows":
            raise InputBlocked("Elite controls require Windows.")
        from ctypes import wintypes as w
        self.w = w
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        class Keyboard(ctypes.Structure):
            _fields_ = [("vk", w.WORD), ("scan", w.WORD), ("flags", w.DWORD),
                        ("time", w.DWORD), ("extra", ctypes.c_size_t)]
        class Mouse(ctypes.Structure):
            _fields_ = [("x", w.LONG), ("y", w.LONG), ("data", w.DWORD),
                        ("flags", w.DWORD), ("time", w.DWORD), ("extra", ctypes.c_size_t)]
        class Union(ctypes.Union):
            _fields_ = [("keyboard", Keyboard), ("mouse", Mouse)]
        class Input(ctypes.Structure):
            _anonymous_ = ("value",)
            _fields_ = [("type", w.DWORD), ("value", Union)]
        self.Input, self.Keyboard, self.Mouse = Input, Keyboard, Mouse
        self.user.SendInput.argtypes = [w.UINT, ctypes.POINTER(Input), ctypes.c_int]
        self.user.SendInput.restype = w.UINT
        self.user.GetForegroundWindow.restype = w.HWND
        self.user.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        self.user.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user.GetAsyncKeyState.restype = ctypes.c_short
        self.user.MapVirtualKeyW.argtypes = [w.UINT, w.UINT]
        self.kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.kernel.OpenProcess.restype = w.HANDLE
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
        self.kernel.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
        self.advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
        self.advapi.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
        self.advapi.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
        self.advapi.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
        self.advapi.GetSidSubAuthority.argtypes = [ctypes.c_void_p, w.DWORD]
        self.advapi.GetSidSubAuthority.restype = ctypes.POINTER(w.DWORD)
        self.sent = []

    def _integrity(self, process):
        token, needed = self.w.HANDLE(), self.w.DWORD()
        if not self.advapi.OpenProcessToken(process, 8, ctypes.byref(token)):
            raise InputBlocked("Cannot inspect process permissions.")
        try:
            self.advapi.GetTokenInformation(token, 25, None, 0, ctypes.byref(needed))
            buffer = ctypes.create_string_buffer(needed.value)
            if not self.advapi.GetTokenInformation(token, 25, buffer, needed, ctypes.byref(needed)):
                raise InputBlocked("Cannot inspect process permissions.")
            sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
            count = self.advapi.GetSidSubAuthorityCount(sid)[0]
            return self.advapi.GetSidSubAuthority(sid, count - 1)[0]
        finally:
            self.kernel.CloseHandle(token)

    def context(self):
        pid = self.w.DWORD()
        self.user.GetWindowThreadProcessId(self.user.GetForegroundWindow(), ctypes.byref(pid))
        process = self.kernel.OpenProcess(0x1000, False, pid.value)
        if not process:
            raise InputBlocked("Focus Elite Dangerous and repeat the request.")
        own = None
        try:
            size, name = self.w.DWORD(32768), ctypes.create_unicode_buffer(32768)
            if not self.kernel.QueryFullProcessImageNameW(process, 0, name, ctypes.byref(size)):
                raise InputBlocked("Cannot identify the foreground game.")
            if Path(name.value).name.casefold() != "elitedangerous64.exe":
                raise InputBlocked("Focus Elite Dangerous and repeat the request.")
            own = self.kernel.OpenProcess(0x1000, False, os.getpid())
            if not own or self._integrity(process) > self._integrity(own):
                raise InputBlocked("Elite runs with higher permissions. Run Elite and Wingman at the same permission level.")
            times = [self.w.FILETIME() for _ in range(4)]
            if not self.kernel.GetProcessTimes(process, *(ctypes.byref(t) for t in times)):
                raise InputBlocked("Cannot identify the game session.")
            ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            return {"pid": pid.value, "started": ticks / 10_000_000 - 11644473600,
                    "presets": str(Path(name.value).parent / "ControlSchemes")}
        finally:
            if own:
                self.kernel.CloseHandle(own)
            self.kernel.CloseHandle(process)

    def held(self, key):
        if key in MOUSE:
            vk = MOUSE[key][2]
        else:
            code, extended = SCAN[key]
            vk = self.user.MapVirtualKeyW(code | (0xE000 if extended else 0), 3)
        return bool(self.user.GetAsyncKeyState(vk) & 0x8000)

    def _send(self, key, release=False):
        packet = self.Input()
        if key in MOUSE:
            down, up, _ = MOUSE[key]
            packet.type = 0
            packet.mouse = self.Mouse(0, 0, {"Mouse_4": 1, "Mouse_5": 2}.get(key, 0), up if release else down, 0, 0)
            event = {"mouse": key, "release": release}
        else:
            event = key_event(key, release)
            packet.type = 1
            packet.keyboard = self.Keyboard(0, event["scan"], event["flags"], 0, 0)
        ctypes.set_last_error(0)
        inserted = self.user.SendInput(1, ctypes.byref(packet), ctypes.sizeof(packet))
        error = ctypes.get_last_error()
        self.sent.append({**event, "key": key, "release": release, "inserted": inserted,
                          "requested": 1, "packet_size": ctypes.sizeof(packet),
                          "windows_error": error, "monotonic": time.monotonic()})
        if inserted != 1:
            raise OSError(f"Input injection failed (Windows error {error}).")

    async def send(self, chord, check):
        """Release only owned keys, including after cancellation or lost focus."""
        self.sent = []
        if any(self.held(key) for key in set(chord) | MODIFIERS):
            raise InputBlocked("Release held keys or modifiers, then repeat the request.")
        pressed = []
        try:
            for key in chord:
                await check()
                self._send(key)
                pressed.append(key)
            await asyncio.sleep(0.12)
        finally:
            errors = []
            for key in reversed(pressed):
                try:
                    self._send(key, True)
                except OSError as exc:
                    # Retrying a release cannot repeat the action.
                    try:
                        self._send(key, True)
                    except OSError:
                        errors.append(str(exc))
            if errors:
                raise OSError("Key release failed; release the keys manually. " + errors[0])
