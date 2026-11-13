"""Capture and position overlays in physical Windows desktop pixels."""
import ctypes as c
from ctypes import wintypes as w

from PyQt5.QtCore import QPoint, QRect
from PyQt5.QtGui import QImage

from .windows import user32

gdi = c.WinDLL("gdi32", use_last_error=True)
HDC = w.HDC
HANDLE = w.HANDLE
UINT = w.UINT


def api(library, name, result, *args):
    function = getattr(library, name)
    function.restype = result
    function.argtypes = args
    return function


class BitmapInfo(c.Structure):
    _fields_ = [
        ("size", w.DWORD), ("width", w.LONG), ("height", w.LONG),
        ("planes", w.WORD), ("bit_count", w.WORD), ("compression", w.DWORD),
        ("image_size", w.DWORD), ("x_density", w.LONG), ("y_density", w.LONG),
        ("colors_used", w.DWORD), ("colors_important", w.DWORD), ("colors", w.DWORD),
    ]


MonitorCallback = c.WINFUNCTYPE(w.BOOL, HANDLE, HDC, c.POINTER(w.RECT), w.LPARAM)
enum_monitors = api(user32, "EnumDisplayMonitors", w.BOOL, HDC, c.POINTER(w.RECT), MonitorCallback, w.LPARAM)
get_dc = api(user32, "GetDC", HDC, w.HWND)
release_dc = api(user32, "ReleaseDC", c.c_int, w.HWND, HDC)
create_dc = api(gdi, "CreateCompatibleDC", HDC, HDC)
delete_dc = api(gdi, "DeleteDC", w.BOOL, HDC)
create_dib = api(gdi, "CreateDIBSection", HANDLE, HDC, c.POINTER(BitmapInfo), UINT,
                 c.POINTER(c.c_void_p), HANDLE, w.DWORD)
select_object = api(gdi, "SelectObject", HANDLE, HDC, HANDLE)
delete_object = api(gdi, "DeleteObject", w.BOOL, HANDLE)
bit_blt = api(gdi, "BitBlt", w.BOOL, HDC, c.c_int, c.c_int, c.c_int, c.c_int,
              HDC, c.c_int, c.c_int, w.DWORD)
get_cursor = api(user32, "GetCursorPos", w.BOOL, c.POINTER(w.POINT))
set_position = api(user32, "SetWindowPos", w.BOOL, w.HWND, w.HWND, c.c_int, c.c_int,
                   c.c_int, c.c_int, UINT)
get_foreground = api(user32, "GetForegroundWindow", w.HWND)
set_foreground = api(user32, "SetForegroundWindow", w.BOOL, w.HWND)


def enable_physical_dpi():
    if hasattr(user32, "SetProcessDpiAwarenessContext"):
        api(user32, "SetProcessDpiAwarenessContext", w.BOOL, HANDLE)(HANDLE(-4))


def cursor_position():
    point = w.POINT()
    if not get_cursor(c.byref(point)):
        raise c.WinError(c.get_last_error())
    return QPoint(point.x, point.y)


def place_window(widget, rect):
    if not set_position(int(widget.winId()), w.HWND(-1), rect.x(), rect.y(),
                        rect.width(), rect.height(), 0x0010):
        raise c.WinError(c.get_last_error())


def monitor_rectangles():
    screens = []

    @MonitorCallback
    def visit(_monitor, _dc, bounds, _):
        rect = bounds.contents
        screens.append(QRect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top))
        return True

    if not enum_monitors(None, None, visit, 0) or not screens:
        raise OSError("无法枚举 Windows 显示器。")
    return screens


def grab_monitor(screen_dc, rect):
    width, height = rect.width(), rect.height()
    info = BitmapInfo(size=40, width=width, height=-height, planes=1, bit_count=32)
    memory_dc = create_dc(screen_dc)
    if not memory_dc:
        raise c.WinError(c.get_last_error())
    bits = c.c_void_p()
    bitmap = previous = None
    try:
        bitmap = create_dib(screen_dc, c.byref(info), 0, c.byref(bits), None, 0)
        if not bitmap or not bits.value:
            raise c.WinError(c.get_last_error())
        previous = select_object(memory_dc, bitmap)
        if not previous or previous == c.c_void_p(-1).value:
            previous = None
            raise c.WinError(c.get_last_error())
        if not bit_blt(memory_dc, 0, 0, width, height, screen_dc, rect.x(), rect.y(), 0x40CC0020):
            raise c.WinError(c.get_last_error())
        api(gdi, "GdiFlush", w.BOOL)()
        from PyQt5 import sip
        image = QImage(sip.voidptr(bits.value), width, height, width * 4, QImage.Format_RGB32).copy()
        if image.isNull():
            raise MemoryError("无法分配截图像素缓冲区。")
        return image
    finally:
        if previous:
            select_object(memory_dc, previous)
        if bitmap:
            delete_object(bitmap)
        delete_dc(memory_dc)


def capture_desktop():
    screens = monitor_rectangles()
    dc = get_dc(None)
    if not dc:
        raise c.WinError(c.get_last_error())
    try:
        return [(rect, grab_monitor(dc, rect)) for rect in screens]
    finally:
        release_dc(None, dc)

