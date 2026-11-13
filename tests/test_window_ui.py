"""Exercise the actual Qt pages on Windows with an isolated configuration."""
import os
from types import SimpleNamespace

import pytest
from PyQt5.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PyQt5.QtGui import QFont, QKeyEvent, QKeySequence, QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QCheckBox, QFileDialog, QLabel, QMessageBox, QPushButton, QRadioButton

from keyboard_shortcuts.editor import Recorder, RuleEditor
from keyboard_shortcuts.rules import Rule, default_rules
from keyboard_shortcuts.store import Config, Settings, load_config, save_config
from keyboard_shortcuts.style import ComboBox
from keyboard_shortcuts.window import HotkeyEdit, MainWindow, Switch

pytestmark = pytest.mark.skipif(os.environ.get("KM_TEST_NATIVE") != "1", reason="requires a Windows desktop")


@pytest.fixture
def screen(tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setQuitOnLastWindowClosed(False)
    engine = SimpleNamespace(error="", running=True, children=[], apply=lambda rules: None,
                             pause=lambda: None, resume=lambda: None)
    scoped = Rule(("A",), ("B",), r"C:\Test\VeryLongExampleApplicationNameWithoutWordBreaks.exe", False)
    chord = ("ControlLeft", "ShiftLeft", "AltLeft", "MetaLeft", "NumpadMultiply", "ScrollLock", "Backslash", "Enter")
    config = Config(default_rules() + [scoped, Rule(chord, chord)], Settings(theme="light"))
    path = tmp_path / "config.json"
    save_config(path, config)
    window = MainWindow(engine, path, config, smoke=True)
    window.show()
    app.processEvents()
    yield window, app
    window.hide()
    window.deleteLater()
    app.processEvents()


def choose(combo, index):
    QTest.mouseClick(combo, Qt.LeftButton)
    QTest.qWait(QApplication.doubleClickInterval() + 20)
    view = combo.view()
    assert view.isVisible()
    target = combo.model().index(index, 0)
    assert view.visualRect(target).isValid()
    assert view.viewport().rect().contains(view.visualRect(target))
    pos = view.visualRect(target).center()
    assert view.indexAt(pos) == target
    global_pos = QPointF(view.viewport().mapToGlobal(pos))
    for kind, button, pressed in (
        (QEvent.MouseMove, Qt.NoButton, Qt.NoButton),
        (QEvent.MouseButtonPress, Qt.LeftButton, Qt.LeftButton),
        (QEvent.MouseButtonRelease, Qt.LeftButton, Qt.NoButton),
    ):
        QApplication.sendEvent(view.viewport(), QMouseEvent(
            kind, QPointF(pos), global_pos, button, pressed, Qt.NoModifier))
    assert combo.currentIndex() == index


def test_filter_dropdowns_and_keyboard_selection(screen):
    window, app = screen
    combos = window.app_filter, window.status_filter
    assert all(isinstance(control, ComboBox) for control in combos)
    assert window.search.height() == combos[0].height() == combos[1].height() == 40
    choose(combos[0], 2)
    choose(combos[1], 2)
    assert window.rule_host.count() == 1
    assert any(button.text() == "编辑" for button in window.rule_host.itemAt(0).widget().findChildren(QPushButton))
    combos[1].setFocus()
    QTest.keyClick(combos[1], Qt.Key_Up)
    assert combos[1].currentIndex() == 1
    assert window.rule_host.count() == 1
    combos[1].showPopup()
    QTest.qWait(180)
    QTest.keyClick(combos[1].view(), Qt.Key_Escape)
    assert not combos[1].view().isVisible()


def test_pages_fit_small_window_and_theme_persists(screen):
    window, app = screen
    for width, height in ((1160, 780), (850, 560)):
        window.resize(width, height)
        for index in range(3):
            window.go(index)
            app.processEvents()
            scroll = window.pages.currentWidget()
            assert scroll.widget().width() == scroll.viewport().width()
            bounds = scroll.widget().rect()
            for button in scroll.widget().findChildren(QPushButton):
                if button.isVisibleTo(scroll.widget()):
                    assert bounds.contains(button.mapTo(scroll.widget(), button.rect().topRight()))
    window.go(1)
    choose(window.theme, window.theme.findData("dark"))
    assert window.dark
    restored = MainWindow(window.engine, window.path, load_config(window.path), smoke=True)
    try:
        assert restored.dark
        assert restored.config == window.config
    finally:
        restored.deleteLater()


def test_switch_uses_full_track_and_space_key(screen):
    window, app = screen
    window.search.setText("左 Shift + D")
    app.processEvents()
    panel = window.rule_host.itemAt(0).widget()
    switch = panel.findChild(Switch)
    assert switch.isChecked()
    QTest.mouseClick(switch, Qt.LeftButton, pos=QPoint(switch.width() - 5, switch.height() // 2))
    assert not load_config(window.path).rules[0].enabled
    switch = window.rule_host.itemAt(0).widget().findChild(Switch)
    QTest.keyClick(switch, Qt.Key_Space)
    assert load_config(window.path).rules[0].enabled


def test_capture_appears_with_default_rules_and_tracks_settings(screen, monkeypatch):
    window, _ = screen
    rules = window.config.rules.copy()
    panel = window.rule_host.itemAt(0).widget()
    labels = {label.text() for label in panel.findChildren(QLabel)}
    assert {"D", "F", "J", "K", "Ctrl + S", "截图"} <= labels
    window.search.setText("截图")
    panel = window.rule_host.itemAt(0).widget()
    opened = []
    monkeypatch.setattr(window, "edit_hotkey", opened.append)
    panel.findChild(QPushButton).click()
    assert opened == ["capture_hotkey"]
    assert window.settings(capture_hotkey="Ctrl+F9")
    assert any(label.text() == "Ctrl + F9"
               for label in window.rule_host.itemAt(0).widget().findChildren(QLabel))
    assert load_config(window.path).rules == rules


def test_repeated_rule_dialogs_and_recording_do_not_dispatch_capture(screen, monkeypatch):
    window, app = screen
    calls = []
    window.engine.pause = lambda: calls.append("pause")
    window.engine.resume = lambda: calls.append("resume")
    monkeypatch.setattr(window, "start_capture", lambda: calls.append("capture"))
    window.hotkeys.entries = {(0x4002, ord("S")): (10, "capture")}
    monkeypatch.setattr(window.hotkeys, "replace", lambda hwnd, desired: setattr(
        window.hotkeys, "entries", {chord: (10, action) for chord, action in desired.items()}))
    results = []
    recorder_exec = Recorder.exec_

    def run_recorder(recorder):
        QTimer.singleShot(0, record)
        return recorder_exec(recorder)

    monkeypatch.setattr(Recorder, "exec_", run_recorder)

    def record():
        recorder = app.activeModalWidget()
        if not isinstance(recorder, Recorder):
            results.append("recorder missing")
            if recorder:
                recorder.reject()
            return
        window.dispatch_hotkey(10, ord("S") << 16 | 2)
        app.sendEvent(recorder, QKeyEvent(QEvent.KeyPress, Qt.Key_Shift, Qt.ShiftModifier, 42, 0xA0, 0))
        app.sendEvent(recorder, QKeyEvent(QEvent.KeyPress, Qt.Key_S, Qt.ShiftModifier, 31, 0x53, 0))
        results.append(recorder.keys)
        QTest.keyClick(recorder, Qt.Key_Escape)

    def edit(should_record):
        dialog = app.activeModalWidget()
        if not isinstance(dialog, RuleEditor):
            results.append("editor missing")
            if dialog:
                dialog.reject()
            return
        if window.hotkeys.entries:
            results.append("global hotkey still registered while dialog is open")
        window.dispatch_hotkey(10, ord("S") << 16 | 2)
        QTest.keyClick(dialog, Qt.Key_S, Qt.ShiftModifier)
        if should_record:
            dialog.pick("source", True)
        dialog.reject()

    for index, should_record in ((None, False), (0, False), (None, True), (0, True)) * 3:
        QTimer.singleShot(0, lambda active=should_record: edit(active))
        window.edit_rule(index)
    assert results == [("ShiftLeft", "S")] * 6
    assert calls == ["pause", "resume"] * 6
    assert not window.recording_hotkey
    window.dispatch_hotkey(10, ord("S") << 16 | 2)
    assert calls[-1] == "capture"


def test_capture_shortcut_dialog_saves_cancels_and_restores_default(screen):
    window, app = screen
    window.engine.running = False

    def interact(action, value=None):
        dialog = app.activeModalWidget()
        edit = dialog.findChild(HotkeyEdit)
        if value == "Ctrl+Shift+S":
            QTest.keyClick(edit, Qt.Key_S, Qt.ControlModifier | Qt.ShiftModifier)
        elif value:
            edit.setKeySequence(QKeySequence.fromString(value))
        if action == "cancel":
            QTest.keyClick(edit, Qt.Key_Escape)
        else:
            buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
            if action == "default":
                buttons["恢复默认"].click()
            buttons["保存"].click()

    QTimer.singleShot(0, lambda: interact("save", "Ctrl+Shift+S"))
    next(button for button in window.findChildren(QPushButton)
         if button.accessibleName() == "编辑截图快捷键").click()
    assert window.capture_button.text() == "Ctrl+Shift+S"
    assert load_config(window.path).settings.capture_hotkey == "Ctrl+Shift+S"
    QTimer.singleShot(0, lambda: interact("cancel", "Ctrl+F9"))
    window.edit_hotkey("capture_hotkey")
    assert window.capture_button.text() == "Ctrl+Shift+S"
    QTimer.singleShot(0, lambda: interact("default"))
    window.edit_hotkey("capture_hotkey")
    assert window.capture_button.text() == "Ctrl+S"
    assert load_config(window.path).settings.capture_hotkey == "Ctrl+S"


def test_add_edit_delete_and_export_from_visible_pages(screen, monkeypatch, tmp_path):
    window, app = screen
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)

    def save_dialog(source, target, title):
        def interact():
            dialog = app.activeModalWidget()
            assert isinstance(dialog, RuleEditor) and dialog.windowTitle() == title
            assert isinstance(dialog.scope, ComboBox)
            choose(dialog.scope, 1)
            assert dialog.choose.isEnabled()
            dialog.scope.setFocus()
            QTest.keyClick(dialog.scope, Qt.Key_Up)
            assert dialog.scope.currentIndex() == 0
            dialog.source = source
            dialog.target = target
            QTest.mouseClick(next(button for button in dialog.findChildren(QPushButton)
                                  if button.text() == "保存"), Qt.LeftButton)
        QTimer.singleShot(0, interact)

    save_dialog(("P",), ("Q",), "添加映射")
    QTest.mouseClick(next(button for button in window.findChildren(QPushButton)
                          if "添加映射" in button.text()), Qt.LeftButton)
    assert window.config.rules[-1] == Rule(("P",), ("Q",))
    window.search.setText("P → Q")
    panel = window.rule_host.itemAt(0).widget()
    save_dialog(("P",), ("R",), "编辑映射")
    QTest.mouseClick(next(button for button in panel.findChildren(QPushButton) if button.text() == "编辑"), Qt.LeftButton)
    assert load_config(window.path).rules[-1] == Rule(("P",), ("R",))
    window.search.setText("P → R")
    panel = window.rule_host.itemAt(0).widget()
    remove = next(button for button in panel.findChildren(QPushButton) if button.text() == "删除")
    assert remove.width() >= 62
    QTest.mouseClick(remove, Qt.LeftButton)
    assert Rule(("P",), ("R",)) not in load_config(window.path).rules
    exported = tmp_path / "export.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(exported), "JSON (*.json)"))
    window.go(2)
    QTest.mouseClick(next(button for button in window.findChildren(QPushButton)
                          if button.text() == "导出配置"), Qt.LeftButton)
    backup = load_config(exported)
    assert backup == window.config

    assert window.settings(close_to_tray=not backup.settings.close_to_tray)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(exported), "JSON (*.json)"))

    def confirm_import():
        dialog = app.activeModalWidget()
        assert dialog.windowTitle() == "导入配置"
        next(control for control in dialog.findChildren(QRadioButton)
             if control.text() == "替换全部规则").setChecked(True)
        dialog.findChild(QCheckBox).setChecked(True)
        QTest.mouseClick(next(button for button in dialog.findChildren(QPushButton)
                              if button.text() == "导入"), Qt.LeftButton)

    QTimer.singleShot(0, confirm_import)
    QTest.mouseClick(next(button for button in window.findChildren(QPushButton)
                          if button.text() == "导入配置"), Qt.LeftButton)
    assert load_config(window.path) == backup
