import ctypes as c
from ctypes import wintypes as w
import os
from pathlib import Path
import subprocess
import sys
import winreg

from .rules import KEYS

user32 = c.WinDLL("user32", use_last_error=True)
kernel32 = c.WinDLL("kernel32", use_last_error=True)
shell32 = c.WinDLL("shell32", use_last_error=True)

SCAN_KEYS = dict(zip(range(2, 12), "1234567890"))
SCAN_KEYS.update(zip(range(16, 26), "QWERTYUIOP"))
SCAN_KEYS.update(zip(range(30, 39), "ASDFGHJKL"))
SCAN_KEYS.update(zip(range(44, 51), "ZXCVBNM"))
SCAN_KEYS.update(zip(range(59, 69), (f"F{i}" for i in range(1, 11))))
SCAN_KEYS.update({
    1: "Escape", 12: "Minus", 13: "Equal", 14: "Backspace", 15: "Tab",
    26: "BracketLeft", 27: "BracketRight", 28: "Enter", 29: "ControlLeft",
    39: "Semicolon", 40: "Quote", 41: "Backquote", 42: "ShiftLeft", 43: "Backslash",
    51: "Comma", 52: "Period", 53: "Slash", 54: "ShiftRight", 55: "NumpadMultiply",
    56: "AltLeft", 57: "Space", 58: "CapsLock", 69: "NumLock", 70: "ScrollLock",
    71: "Numpad7", 72: "Numpad8", 73: "Numpad9", 74: "NumpadSubtract",
    75: "Numpad4", 76: "Numpad5", 77: "Numpad6", 78: "NumpadAdd",
    79: "Numpad1", 80: "Numpad2", 81: "Numpad3", 82: "Numpad0",
    83: "NumpadDecimal", 86: "IntlBackslash", 87: "F11", 88: "F12",
    0x11C: "NumpadEnter", 0x11D: "ControlRight", 0x135: "NumpadDivide",
    0x137: "PrintScreen", 0x138: "AltRight", 0x147: "Home", 0x148: "ArrowUp",
    0x149: "PageUp", 0x14B: "ArrowLeft", 0x14D: "ArrowRight", 0x14F: "End",
    0x150: "ArrowDown", 0x151: "PageDown", 0x152: "Insert", 0x153: "Delete",
    0x15B: "MetaLeft", 0x15C: "MetaRight", 0x15D: "ContextMenu",
})
SCAN_KEYS.update({0x64 + i: f"F{i + 13}" for i in range(11)})
SCAN_KEYS[0x76] = "F24"

VK_SPECIAL = {0x13: "Pause", 0x2C: "PrintScreen", 0x90: "NumLock", 0x91: "ScrollLock",
              0xA0: "ShiftLeft", 0xA1: "ShiftRight", 0xA2: "ControlLeft",
              0xA3: "ControlRight", 0xA4: "AltLeft", 0xA5: "AltRight"}


def event_key(event) -> str | None:
    scan, vk = event.nativeScanCode(), event.nativeVirtualKey()
    return VK_SPECIAL.get(vk) or SCAN_KEYS.get(scan) or SCAN_KEYS.get(
        (scan & 0xff) | (0x100 if scan & 0xe000 else 0)
    )


class ProcessEntry(c.Structure):
    _fields_ = [
        ("size", w.DWORD), ("usage", w.DWORD), ("pid", w.DWORD),
        ("heap", c.c_size_t), ("module", w.DWORD), ("threads", w.DWORD),
        ("parent", w.DWORD), ("priority", w.LONG), ("flags", w.DWORD),
        ("exe", w.WCHAR * 260),
    ]


kernel32.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = w.HANDLE
kernel32.Process32FirstW.argtypes = kernel32.Process32NextW.argtypes = [
    w.HANDLE, c.POINTER(ProcessEntry)
]
kernel32.CloseHandle.argtypes = [w.HANDLE]
kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
kernel32.OpenProcess.restype = w.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)
]


def engine_present() -> bool:
    snapshot = kernel32.CreateToolhelp32Snapshot(2, 0)
    if snapshot in (None, c.c_void_p(-1).value):
        raise OSError("无法确认是否存在其他 keymapper 进程。")
    try:
        entry = ProcessEntry(size=c.sizeof(ProcessEntry))
        ok = kernel32.Process32FirstW(snapshot, c.byref(entry))
        while ok:
            if entry.exe.casefold() in ("keymapper.exe", "keymapperd.exe"):
                return True
            ok = kernel32.Process32NextW(snapshot, c.byref(entry))
        return False
    finally:
        kernel32.CloseHandle(snapshot)


WindowCallback = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
user32.EnumWindows.argtypes = [WindowCallback, w.LPARAM]
user32.IsWindowVisible.argtypes = [w.HWND]
user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, c.c_int]
user32.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]


def running_apps() -> list[tuple[str, str]]:
    found = {}

    @WindowCallback
    def visit(hwnd, _):
        title = c.create_unicode_buffer(512)
        if not user32.IsWindowVisible(hwnd) or not user32.GetWindowTextW(hwnd, title, len(title)):
            return True
        pid = w.DWORD()
        user32.GetWindowThreadProcessId(hwnd, c.byref(pid))
        if pid.value == os.getpid():
            return True
        handle = kernel32.OpenProcess(0x1000, False, pid.value)
        if handle:
            try:
                path = c.create_unicode_buffer(32768)
                size = w.DWORD(len(path))
                if kernel32.QueryFullProcessImageNameW(handle, 0, path, c.byref(size)):
                    found.setdefault(path.value, title.value)
            finally:
                kernel32.CloseHandle(handle)
        return True

    user32.EnumWindows(visit, 0)
    return sorted((name, path) for path, name in found.items())


def command_args() -> list[str]:
    return [sys.executable] if getattr(sys, "frozen", False) else [
        sys.executable, str(Path(sys.argv[0]).resolve())
    ]


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def login_registered() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            command, _ = winreg.QueryValueEx(key, "Keyboard Manager")
            return command == subprocess.list2cmdline(command_args() + ["--tray"])
    except FileNotFoundError:
        return False


def set_login(enabled: bool) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            command = subprocess.list2cmdline(command_args() + ["--tray"])
            winreg.SetValueEx(key, "Keyboard Manager", 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, "Keyboard Manager")
            except FileNotFoundError:
                pass


def is_elevated() -> bool:
    return bool(shell32.IsUserAnAdmin())


user32.RegisterHotKey.argtypes = [w.HWND, c.c_int, w.UINT, w.UINT]
user32.UnregisterHotKey.argtypes = [w.HWND, c.c_int]


def hotkey_codes(sequence: int) -> tuple[int, int]:
    from PyQt5.QtCore import Qt

    modifiers = sum(flag for mask, flag in ((Qt.AltModifier, 1), (Qt.ControlModifier, 2),
                    (Qt.ShiftModifier, 4), (Qt.MetaModifier, 8)) if sequence & int(mask))
    key = sequence & 0x01ffffff
    if Qt.Key_F1 <= key <= Qt.Key_F24:
        vk = 0x70 + key - Qt.Key_F1
    elif Qt.Key_A <= key <= Qt.Key_Z or Qt.Key_0 <= key <= Qt.Key_9:
        vk = key
    else:
        vk = 0
    if not (modifiers and vk):
        raise ValueError("请选择带修饰键的字母、数字或 F1–F24。")
    return modifiers | 0x4000, vk

