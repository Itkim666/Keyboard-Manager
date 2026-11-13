import ctypes
from ctypes import wintypes
from threading import Event, Thread

from PyQt5.QtGui import QKeySequence

from .rules import MODIFIERS
from .windows import hotkey_codes, kernel32, user32

NAMES = {"pause": "暂停快捷键", "capture": "截图快捷键"}
LEFT_CAPTURE = "capture_left"
LEFT_SHIFT_CAPTURE_HOTKEY = "Shift+S"
FAMILY_FLAGS = {"Alt": 1, "Control": 2, "Shift": 4, "Meta": 8}
CAPTURE_MESSAGE = 0x8001
MODIFIER_KEYS = {0xA4: 1, 0xA5: 1, 0xA2: 2, 0xA3: 2, 0xA0: 4, 0xA1: 4, 0x5B: 8, 0x5C: 8}
HookProc = ctypes.WINFUNCTYPE(wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class KeyboardEvent(ctypes.Structure):
    _fields_ = [(field, wintypes.DWORD) for field in ("vk", "scan", "flags", "time")] + [
        ("extra", wintypes.WPARAM)]


user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HookProc, wintypes.HMODULE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HANDLE
user32.CallNextHookEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = wintypes.LPARAM
user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                               wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                              wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def codes(value):
    sequence = QKeySequence.fromString(value, QKeySequence.PortableText)
    if sequence.count() != 1:
        raise ValueError("全局快捷键只支持一组组合键。")
    return hotkey_codes(sequence[0])


def capture_label(value):
    return "左 Shift + S" if value == LEFT_SHIFT_CAPTURE_HOTKEY else value


def shortcut_plan(settings, rules):
    desired = {}
    for action, value in (("pause", settings.pause_hotkey), ("capture", settings.capture_hotkey)):
        if value:
            chord = codes(value)
            if chord in desired:
                raise ValueError("截图和暂停映射不能使用同一个快捷键。")
            desired[chord] = LEFT_CAPTURE if action == "capture" and value == LEFT_SHIFT_CAPTURE_HOTKEY else action
    for rule in rules:
        if not rule.enabled:
            continue
        for keys, output in ((rule.source, False), (rule.target, True)):
            ordinary = [key for key in keys if key not in MODIFIERS]
            if len(ordinary) != 1:
                continue
            key = ordinary[0]
            flags = 0x4000
            for modifier in keys:
                if modifier in MODIFIERS:
                    flags |= FAMILY_FLAGS[modifier.removesuffix("Left").removesuffix("Right")]
            vk = ord(key) if len(key) == 1 and key.isalnum() else (
                0x6f + int(key[1:]) if key.startswith("F") and key[1:].isdigit() else None
            )
            action = desired.get((flags, vk))
            if action == "capture" or (action == LEFT_CAPTURE and "ShiftLeft" in keys):
                field = "输出" if output else "输入"
                raise ValueError(f"截图快捷键与已启用的键盘映射{field}冲突。")
    return desired


class Hotkeys:
    def __init__(self):
        self.entries = {}
        self.next_id = 10
        self.hook = None
        self.physical_keys = set()
        self.thread = None
        self.thread_id = None

    def observe_capture(self, hwnd):
        if self.hook:
            return
        ready = Event()
        stop = Event()
        errors = []

        def listen():
            consumed = set()

            @HookProc
            def observe(code, message, data):
                if code == 0 and not stop.is_set():
                    event = KeyboardEvent.from_address(data)
                    binding = self.physical_capture(event.vk, event.flags)
                    if not event.flags & 0x10 and event.vk in consumed:
                        if event.flags & 0x80:
                            consumed.discard(event.vk)
                        return 1
                    if binding is not None:
                        identifier, chord = binding
                        entry = self.entries.get((0x4000 | (chord & 0xffff), event.vk))
                        if entry and entry[0] == identifier:
                            if user32.PostMessageW(hwnd, CAPTURE_MESSAGE, identifier, chord) and entry[1] == LEFT_CAPTURE:
                                consumed.add(event.vk)
                                return 1
                return user32.CallNextHookEx(None, code, message, data)

            message = wintypes.MSG()
            user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
            self.thread_id = kernel32.GetCurrentThreadId()
            self.hook = user32.SetWindowsHookExW(13, observe, kernel32.GetModuleHandleW(None), 0)
            if not self.hook:
                errors.append(ctypes.get_last_error())
            ready.set()
            if self.hook:
                try:
                    while not stop.is_set() and user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                        pass
                finally:
                    user32.UnhookWindowsHookEx(self.hook)
                    self.hook = None
            self.physical_keys.clear()

        self.stop_event = stop
        self.thread = Thread(target=listen, name="Keyboard Manager capture input", daemon=True)
        self.thread.start()
        if not ready.wait(1):
            self.stop_observing()
            raise OSError("截图按键监听初始化超时。")
        if errors:
            raise OSError(f"无法监听实体截图按键（Windows 错误 {errors[0]}）。")

    def stop_observing(self):
        if self.thread is not None and self.thread.is_alive():
            self.stop_event.set()
            if self.thread_id is not None:
                user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
            self.thread.join(timeout=1)

    def physical_capture(self, vk, flags):
        if flags & 0x10:  # LLKHF_INJECTED
            return None
        if flags & 0x80:  # LLKHF_UP
            self.physical_keys.discard(vk)
            return None
        bindings = self.entries
        if vk not in MODIFIER_KEYS and not any(
                key == vk and action in ("capture", LEFT_CAPTURE)
                for (_, key), (_, action) in bindings.items()):
            return None
        if vk in self.physical_keys:
            return None
        self.physical_keys.add(vk)
        if vk in MODIFIER_KEYS:
            return None
        modifiers = physical = 0
        held = set()
        for key, flag in MODIFIER_KEYS.items():
            if user32.GetAsyncKeyState(key) & 0x8000:
                held.add(key)
                modifiers |= flag
                if key in self.physical_keys:
                    physical |= flag
            else:
                self.physical_keys.discard(key)
        if modifiers != physical:
            return None
        entry = bindings.get((0x4000 | modifiers, vk))
        if entry is not None and (entry[1] == "capture" or
                                  (entry[1] == LEFT_CAPTURE and held & {0xA0, 0xA1} == {0xA0})):
            return entry[0], (vk << 16) | modifiers

    def replace(self, hwnd, desired):
        acquired = {}
        try:
            for chord, action in desired.items():
                existing = self.entries.get(chord)
                if existing and (existing[1] == LEFT_CAPTURE) == (action == LEFT_CAPTURE):
                    continue
                identifier = self.next_id
                self.next_id += 1
                # Windows reserves both sides of Shift. The hook handles the sided binding.
                if action != LEFT_CAPTURE and not user32.RegisterHotKey(hwnd, identifier, *chord):
                    error = ctypes.get_last_error()
                    detail = "已被占用或被 Windows 保留。请更换组合键。" if error == 1409 else (
                        f"无法在当前 Windows 会话注册（错误 {error}）。"
                    )
                    raise OSError(f"{NAMES[action]}{detail}")
                acquired[chord] = (identifier, action)
        except OSError:
            for identifier, action in acquired.values():
                if action != LEFT_CAPTURE:
                    user32.UnregisterHotKey(hwnd, identifier)
            raise
        for chord, (identifier, action) in self.entries.items():
            if action != LEFT_CAPTURE and (chord not in desired or desired[chord] == LEFT_CAPTURE):
                user32.UnregisterHotKey(hwnd, identifier)
        current = {**self.entries, **acquired}
        updated = {chord: (current[chord][0], action) for chord, action in desired.items()}
        if updated != self.entries:
            self.entries = updated
            self.physical_keys.clear()

    def action(self, identifier, message_chord):
        chord = ((message_chord & 0xffff) | 0x4000, (message_chord >> 16) & 0xffff)
        entry = self.entries.get(chord)
        if entry is not None and entry[0] == identifier:
            return "capture" if entry[1] == LEFT_CAPTURE else entry[1]

    def has(self, action):
        return any(value == action or (action == "capture" and value == LEFT_CAPTURE)
                   for _, value in self.entries.values())

