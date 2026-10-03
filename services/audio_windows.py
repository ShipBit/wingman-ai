"""Device/resume notifications; periodic reconciliation remains the fallback."""
import threading


def watch_devices(changed):
    stop = threading.Event()

    def watch():
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        class WindowClass(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("proc", callback_type), ("cls_extra", ctypes.c_int),
                        ("wnd_extra", ctypes.c_int), ("instance", wintypes.HINSTANCE), ("icon", wintypes.HICON),
                        ("cursor", wintypes.HANDLE), ("background", wintypes.HBRUSH),
                        ("menu", wintypes.LPCWSTR), ("name", wintypes.LPCWSTR)]

        class DeviceFilter(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("kind", wintypes.DWORD), ("reserved", wintypes.DWORD),
                        ("guid", ctypes.c_byte * 16), ("name", wintypes.WCHAR)]

        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.RegisterDeviceNotificationW.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD]
        user32.RegisterDeviceNotificationW.restype = wintypes.HANDLE
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.UnregisterDeviceNotification.argtypes = [wintypes.HANDLE]
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.restype = ctypes.c_ssize_t
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        @callback_type
        def procedure(hwnd, message, wparam, lparam):
            if message in (0x0219, 0x0218):
                changed()
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        instance = kernel32.GetModuleHandleW(None)
        name = "WingmanAudioDevices"
        cls = WindowClass(0, procedure, 0, 0, instance, None, None, None, None, name)
        if not user32.RegisterClassW(ctypes.byref(cls)):
            return
        window = user32.CreateWindowExW(0, name, name, 0, 0, 0, 0, 0, None, None, instance, None)
        notification = None
        try:
            if not window:
                return
            device_filter = DeviceFilter()
            device_filter.size, device_filter.kind = ctypes.sizeof(DeviceFilter), 5
            notification = user32.RegisterDeviceNotificationW(window, ctypes.byref(device_filter), 4)
            message = wintypes.MSG()
            while not stop.wait(0.2):
                while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                    user32.TranslateMessage(ctypes.byref(message))
                    user32.DispatchMessageW(ctypes.byref(message))
        finally:
            if notification:
                user32.UnregisterDeviceNotification(notification)
            if window:
                user32.DestroyWindow(window)
            user32.UnregisterClassW(name, instance)

    def guarded_watch():
        try:
            watch()
        except Exception as exc:
            from services.printr import Printr
            Printr().print(f"Audio notifications unavailable ({exc}); periodic recovery remains active.", server_only=True)

    threading.Thread(target=guarded_watch, name="audio-device-events", daemon=True).start()
    return stop.set
