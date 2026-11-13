from dataclasses import replace
from types import SimpleNamespace
import pytest

from keyboard_shortcuts.hotkeys import LEFT_CAPTURE, Hotkeys, shortcut_plan, user32
from keyboard_shortcuts.rules import Rule, default_rules
from keyboard_shortcuts.store import Settings
from keyboard_shortcuts.window import QApplication, MainWindow


def test_default_capture_does_not_overlap_existing_direction_mappings():
    assert shortcut_plan(Settings(), default_rules()) == {(0x4002, ord("S")): "capture"}


def test_default_capture_conflicts_with_pause_and_either_control_key():
    with pytest.raises(ValueError):
        shortcut_plan(replace(Settings(), pause_hotkey="Ctrl+S"), [])
    with pytest.raises(ValueError):
        shortcut_plan(Settings(), [Rule(("ControlLeft", "S"), ("F2",))])
    with pytest.raises(ValueError):
        shortcut_plan(Settings(), [Rule(("F2",), ("ControlRight", "S"))])


def test_global_ctrl_s_captures_or_saves_in_focused_editor(monkeypatch):
    editor = object()
    actions = []
    hotkeys = Hotkeys()
    hotkeys.entries = {(0x4002, ord("S")): (10, "capture")}
    window = SimpleNamespace(exiting=False, recording_hotkey=False, hotkeys=hotkeys,
                             capture_session=None, start_capture=lambda: actions.append("capture"))
    monkeypatch.setattr(QApplication, "activeModalWidget", lambda: None)
    chord = ord("S") << 16 | 2
    MainWindow.dispatch_hotkey(window, 10, chord)
    window.capture_session = SimpleNamespace(windows=[editor], action=actions.append)
    monkeypatch.setattr(QApplication, "activeWindow", lambda: editor)
    MainWindow.dispatch_hotkey(window, 10, chord)
    monkeypatch.setattr(QApplication, "activeWindow", lambda: None)
    MainWindow.dispatch_hotkey(window, 10, chord)
    assert actions == ["capture", "save"]


@pytest.mark.parametrize("action", [LEFT_CAPTURE, "capture"])
def test_physical_capture_rejects_injected_extra_modifiers_and_repeats(monkeypatch, action):
    hotkeys = Hotkeys()
    hotkeys.entries = {(0x4004, ord("S")): (10, action)}
    down = set()
    monkeypatch.setattr(user32, "GetAsyncKeyState", lambda vk: 0x8000 if vk in down else 0)

    def press(vk):
        result = hotkeys.physical_capture(vk, 0)
        down.add(vk)
        return result

    def release(vk):
        hotkeys.physical_capture(vk, 0x80)
        down.discard(vk)

    key = ord("S")
    assert press(key) is None
    assert press(0xA0) is None
    assert press(key) is None
    release(key)
    assert hotkeys.physical_capture(key, 0x10) is None
    assert press(0xA2) is None
    assert press(key) is None
    release(key)
    release(0xA2)
    assert press(key) == (10, key << 16 | 4)
    assert press(key) is None
    release(key)
    release(0xA0)
    assert press(key) is None
    release(key)
    assert press(0xA1) is None
    assert press(key) == (None if action == LEFT_CAPTURE else (10, key << 16 | 4))
    release(key)
    assert press(0xA0) is None
    assert press(key) == (None if action == LEFT_CAPTURE else (10, key << 16 | 4))
    assert hotkeys.action(10, key << 16 | 6) is None
    assert hotkeys.action(11, key << 16 | 4) is None


def test_sided_capture_leaves_windows_shift_reservation_available(monkeypatch):
    registered = set()

    def register(hwnd, identifier, *_):
        registered.add(identifier)
        return True

    monkeypatch.setattr(user32, "RegisterHotKey", register)
    monkeypatch.setattr(user32, "UnregisterHotKey", lambda hwnd, identifier: registered.remove(identifier))
    hotkeys = Hotkeys()
    desired = shortcut_plan(Settings(capture_hotkey="Shift+S"), [])
    assert desired == {(0x4004, ord("S")): LEFT_CAPTURE}
    hotkeys.replace(1, desired)
    assert hotkeys.has("capture") and not registered
    hotkeys.replace(1, {next(iter(desired)): "capture"})
    assert len(registered) == 1
    hotkeys.replace(1, desired)
    assert hotkeys.has("capture") and not registered

