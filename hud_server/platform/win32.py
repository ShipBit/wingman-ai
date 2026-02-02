import ctypes
from ctypes import wintypes

# Windows API Constants
GWL_EXSTYLE = -20
WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x80000
WS_EX_TRANSPARENT = 0x20
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
LWA_ALPHA = 0x00000002
LWA_COLORKEY = 0x00000001
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_SHOWWINDOW = 0x0040
SWP_NOACTIVATE = 0x0010
SWP_ASYNCWINDOWPOS = 0x4000
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0

# Function pointers
# Use fresh WinDLL instances to isolate argtypes from other modules sharing windll
user32 = ctypes.WinDLL("user32.dll", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32.dll", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)

SW_SHOWNOACTIVATE = 4
HWND_TOPMOST = wintypes.HWND(-1)

# Use platform-appropriate types for WPARAM and LPARAM (64-bit on x64)
if ctypes.sizeof(ctypes.c_void_p) == 8:
    WPARAM = ctypes.c_uint64
    LPARAM = ctypes.c_int64
    LRESULT = ctypes.c_int64
else:
    WPARAM = ctypes.c_uint
    LPARAM = ctypes.c_long
    LRESULT = ctypes.c_long

WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint, WPARAM, LPARAM)

class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint), ("style", ctypes.c_uint), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON), ("hCursor", wintypes.HICON), ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON),
    ]

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ('biSize', wintypes.DWORD), ('biWidth', wintypes.LONG), ('biHeight', wintypes.LONG),
        ('biPlanes', wintypes.WORD), ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD),
        ('biSizeImage', wintypes.DWORD), ('biXPelsPerMeter', wintypes.LONG), ('biYPelsPerMeter', wintypes.LONG),
        ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD),
    ]

class RGBQUAD(ctypes.Structure):
    _fields_ = [
        ('rgbBlue', ctypes.c_byte),
        ('rgbGreen', ctypes.c_byte),
        ('rgbRed', ctypes.c_byte),
        ('rgbReserved', ctypes.c_byte)
    ]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [('bmiHeader', BITMAPINFOHEADER), ('bmiColors', wintypes.DWORD * 3)]

# Setup Function Prototypes
user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
    ctypes.POINTER(wintypes.SIZE), wintypes.HDC, ctypes.POINTER(wintypes.POINT),
    wintypes.COLORREF, ctypes.POINTER(RGBQUAD), wintypes.DWORD
]

# Basic Win32 message structures for a non-blocking pump
class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND), ("message", ctypes.c_uint), ("wParam", WPARAM), ("lParam", LPARAM),
        ("time", wintypes.DWORD), ("pt", POINT)
    ]

# WinAPI signatures we need for message pumping
# Use c_void_p for MSG pointers to avoid strict type checking issues with byref()
user32.PeekMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.c_void_p]
user32.TranslateMessage.restype = wintypes.BOOL
user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
user32.DispatchMessageW.restype = LRESULT

PM_REMOVE = 0x0001

def _wnd_proc(hwnd, msg, wparam, lparam):
    """Window procedure callback - must handle all message types safely."""
    try:
        return user32.DefWindowProcW(hwnd, msg, WPARAM(wparam), LPARAM(lparam))
    except:
        return 0

_wnd_proc_callback = WNDPROC(_wnd_proc)
_class_registered = False
_class_name = "WingmanHeadsUpOverlay"

def _ensure_window_class():
    global _class_registered
    if _class_registered:
        return True
    hInstance = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = _wnd_proc_callback
    wc.hInstance = hInstance
    wc.lpszClassName = _class_name
    if user32.RegisterClassExW(ctypes.byref(wc)):
        _class_registered = True
        return True
    return False

# Common helpers
def force_on_top(hwnd):
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                       SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
