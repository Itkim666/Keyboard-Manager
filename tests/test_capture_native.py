"""Windows GUI integration checks. Enable with KM_TEST_NATIVE=1."""
import os

import pytest
from PyQt5.QtCore import QMimeData, QPoint, QRect, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QImage, QPainter
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QFileDialog, QPlainTextEdit, QPushButton, QWidget

from keyboard_shortcuts import capture
from keyboard_shortcuts.capture_text import extract_text, translate_text
from keyboard_shortcuts.capture_windows import capture_desktop, enable_physical_dpi
from keyboard_shortcuts.hotkeys import Hotkeys, codes

pytestmark = pytest.mark.skipif(os.environ.get("KM_TEST_NATIVE") != "1", reason="requires a Windows desktop")


@pytest.fixture(scope="module")
def app():
    enable_physical_dpi()
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    return instance


def test_physical_screen_capture_has_native_dimensions(app):
    screens = capture_desktop()
    assert screens
    for rect, image in screens:
        assert not image.isNull()
        assert image.size() == rect.size()
    session = capture.CaptureSession(None, screens)
    try:
        session.show()
        app.processEvents()
        session.document.region = screens[0][0]
        session.refresh()
        assert session.host.rect().contains(session.host.toolbar.geometry())
    finally:
        session.close(restore=False)


def test_windows_registers_and_releases_capture_hotkey(app):
    window = QWidget()
    bindings = Hotkeys()
    chord = codes("Ctrl+Alt+Shift+F23")
    hwnd = int(window.winId())
    bindings.replace(hwnd, {chord: "capture"})
    try:
        second = Hotkeys()
        with pytest.raises(OSError):
            second.replace(int(QWidget().winId()), {chord: "capture"})
    finally:
        bindings.replace(hwnd, {})
    bindings.replace(hwnd, {chord: "capture"})
    bindings.replace(hwnd, {})


def test_capture_tool_cursors_match_selected_icons(app):
    screen = QRect(0, 0, 1100, 640)
    session = capture.CaptureSession(None, [(screen, make_image(screen.size(), "white"))])
    try:
        window = session.windows[0]
        window.resize(screen.size())
        window.show()
        session.ready = True
        session.document.region = QRect(100, 100, 900, 400)
        session.refresh()
        for key in ("arrow", "line", "text", "erase"):
            QTest.mouseClick(window.toolbar.buttons[key], Qt.LeftButton)
            assert window.toolbar.buttons[key].cursor().shape() == Qt.BitmapCursor
            assert session.cursor(QPoint(500, 300), 1).shape() == Qt.BitmapCursor
            assert window.toolbar.buttons["select"].cursor().shape() == Qt.ArrowCursor
            assert window.toolbar.buttons["rectangle"].cursor().shape() != Qt.BitmapCursor
        QTest.mouseClick(window.toolbar.buttons["select"], Qt.LeftButton)
        assert session.cursor(QPoint(500, 300), 1) == Qt.SizeAllCursor
    finally:
        session.close(restore=False)


def test_translation_shows_and_copies_text_after_applying_image(app, monkeypatch):
    from keyboard_shortcuts.capture_translation import Translation

    screen = QRect(0, 0, 1000, 600)
    session = capture.CaptureSession(None, [(screen, make_image(screen.size(), "white"))])
    try:
        session.document.region = QRect(40, 50, 420, 180)
        session.ready = True
        session.refresh()
        session.translation_state = session.document.state()
        output = make_image(session.document.region.size(), "lightgray")
        result = Translation(output, "微软 PowerToys\nFancyZones 文档", True)
        shown = []
        copied = []

        class Clipboard:
            setText = staticmethod(copied.append)

        monkeypatch.setattr(QApplication, "clipboard", Clipboard)

        def inspect():
            dialog = session.dialog
            if dialog is not None:
                editor = dialog.findChild(QPlainTextEdit)
                shown.append((dialog.windowTitle(), editor.isReadOnly(), editor.toPlainText()))
                copy = dialog.findChild(QPushButton)
                copy.click()
                selection = editor.textCursor()
                selection.setPosition(0)
                selection.setPosition(2, selection.KeepAnchor)
                editor.setTextCursor(selection)
                copy.click()
                dialog.accept()

        QTimer.singleShot(0, inspect)
        session.text_ready(result, None)
        assert shown == [("简体中文译文", True, result.text)]
        assert copied == [result.text, "微软"]
        assert session.document.render().pixelColor(0, 0) == QColor("lightgray")
    finally:
        session.close(restore=False)


def test_injected_hotkey_is_ignored_and_capture_message_opens_overlay(app, tmp_path):
    import ctypes as c
    from ctypes import wintypes as w

    from keyboard_shortcuts.capture_windows import get_foreground, set_foreground
    from keyboard_shortcuts.engine import EngineController
    from keyboard_shortcuts.hotkeys import CAPTURE_MESSAGE
    from keyboard_shortcuts.rules import default_rules
    from keyboard_shortcuts.store import Config, Settings
    from keyboard_shortcuts.window import MainWindow
    from keyboard_shortcuts.windows import engine_present, user32

    engine = EngineController(tmp_path)
    if not engine_present():
        engine.apply(default_rules())
    window = MainWindow(engine, tmp_path / "config.json", Config(
        default_rules(), Settings(capture_hotkey="Shift+F24")))
    try:
        window.show()
        window.activateWindow()
        hwnd = int(window.winId())
        assert window.hotkeys.hook and window.hotkeys.has("capture"), window.capture_warning
        set_foreground(hwnd)
        QTest.qWait(100)
        if get_foreground() != hwnd:
            pytest.skip("Windows did not allow the test window to take the foreground")
        send = user32.keybd_event
        send.argtypes = [w.BYTE, w.BYTE, w.DWORD, c.c_size_t]
        for key, scan, flags in ((0xA0, 0x2a, 0), (0x87, 0x76, 0), (0x87, 0x76, 2), (0xA0, 0x2a, 2)):
            send(key, scan, flags, 0)
        QTest.qWait(150)
        assert window.capture_session is None
        identifier, _ = window.hotkeys.entries[codes("Shift+F24")]
        assert user32.PostMessageW(hwnd, CAPTURE_MESSAGE, identifier, 0x87 << 16 | 4)
        for _ in range(25):
            if window.capture_session is not None:
                break
            QTest.qWait(40)
        assert window.capture_session is not None
        QTest.keyClick(window.capture_session.windows[0], Qt.Key_Escape)
        assert window.capture_session is None
    finally:
        window.release_capture()
        engine.stop()
        if window.tray:
            window.tray.hide()
        window.hide()
        window.deleteLater()


def make_image(size, color):
    image = QImage(size, QImage.Format_RGB32)
    image.fill(QColor(color))
    return image


def test_real_toolbar_and_editor_on_mixed_scale_geometry(app, monkeypatch):
    desktop = QRect(0, 0, 1000, 600)
    second = QRect(-1200, 0, 1200, 900)
    session = capture.CaptureSession(None, [(desktop, make_image(desktop.size(), "white")),
                                             (second, make_image(second.size(), "lightgray"))])
    left, right = session.windows
    left.resize(1000, 600)
    right.resize(600, 450)  # physical scale 2.0 on the secondary monitor
    left.show()
    right.show()
    session.ready = True
    try:
        position = QPoint(150, 100)
        monkeypatch.setattr(capture, "cursor_position", lambda: QPoint(position))
        QTest.mousePress(left, Qt.LeftButton, pos=QPoint(150, 100))
        position = QPoint(850, 420)
        QTest.mouseRelease(left, Qt.LeftButton, pos=QPoint(850, 420))
        assert session.document.region == QRect(150, 100, 701, 321)
        assert left.toolbar.isVisible()
        assert left.toolbar.y() > 420
        QTest.mouseClick(left.toolbar.buttons["rectangle"], Qt.LeftButton)
        session.press(QPoint(250, 220))
        session.release(QPoint(330, 280), left)
        assert session.document.render().pixelColor(100, 150) == QColor("#e62324")
        QTest.mouseClick(left.toolbar.buttons["undo"], Qt.LeftButton)
        assert not session.document.marks
        QTest.mouseClick(left.toolbar.buttons["redo"], Qt.LeftButton)
        assert len(session.document.marks) == 1
        QTest.mouseClick(left.toolbar.buttons["erase"], Qt.LeftButton)
        assert len(session.document.marks) == 1
        session.press(QPoint(235, 250))
        session.release(QPoint(267, 250), left)
        assert session.document.render().pixelColor(100, 150) == QColor("white")
        assert session.document.render().pixelColor(180, 150) == QColor("#e62324")
        session.document.undo()
        assert session.document.render().pixelColor(100, 150) == QColor("#e62324")
        session.document.redo()
        assert session.document.render().pixelColor(100, 150) == QColor("white")
        for region, host in (
            (QRect(700, 440, 300, 160), left),
            (QRect(0, 0, 450, 180), left),
            (desktop, left),
            (second, right),
            (QRect(-700, 100, 1000, 550), right),
        ):
            session.document.region = region
            session.refresh()
            assert session.host is host
            assert host.rect().contains(host.toolbar.geometry())
            assert all(button.isVisible() for button in host.toolbar.buttons.values())
        session.document.region = second
        session.refresh()
        assert right.toolbar.y() + right.toolbar.height() < right.height()
        assert right.toolbar.buttons["finish"].mapTo(right, QPoint()).x() < right.width()
    finally:
        session.close(restore=False)


def test_actual_local_ocr_and_translation(app):
    image = make_image(QRect(0, 0, 680, 165).size(), "white")
    painter = QPainter(image)
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(32)
    painter.setFont(font)
    painter.setPen(Qt.black)
    painter.drawText(28, 58, "Hello world 2026")
    painter.drawText(28, 117, "今天天气很好")
    painter.end()
    text = extract_text(image)
    assert "Hello world 2026" in text
    assert "今天天气很好" in text
    assert "天气" in translate_text("The weather is nice today.")[1]
    assert "capital" in translate_text("北京是中国的首都。")[1].lower()


def test_annotations_and_export_paths(app, monkeypatch, tmp_path):
    bounds = QRect(0, 0, 1000, 600)
    session = capture.CaptureSession(None, [(bounds, make_image(bounds.size(), "white"))])
    window = session.windows[0]
    session.host = window
    session.document.region = QRect(50, 50, 500, 300)
    for index, tool in enumerate(("arrow", "rectangle", "ellipse", "line")):
        session.action(tool)
        session.press(QPoint(70 + index * 85, 90))
        session.move(QPoint(100 + index * 85, 120))
        session.release(QPoint(140 + index * 85, 140), window)
    monkeypatch.setattr(session, "text_dialog", lambda _, mark: capture.replace(mark, text="Text 2026"))
    session.action("text")
    session.press(QPoint(80, 180))
    session.release(QPoint(80, 180), window)
    assert [mark.kind for mark in session.document.marks] == ["arrow", "rectangle", "ellipse", "line", "text"]
    before = session.document.marks[-1].points
    session.action("select")
    session.press(QPoint(105, 198))
    session.release(QPoint(120, 205), window)
    assert session.document.marks[-1].points == (before[0] + QPoint(15, 7),)

    class SelectedPath(QFileDialog):
        def exec_(self):
            assert not self.testOption(QFileDialog.DontUseNativeDialog)
            return self.Accepted

        def selectedFiles(self):
            return [str(destination)]

    monkeypatch.setattr(capture, "QFileDialog", SelectedPath)
    for extension in (".png", ".jpg"):
        destination = tmp_path / ("截图" + extension)
        session.action("save")
        assert QImage(str(destination)).size() == session.document.region.size()
        assert not session.done
    session.close(restore=False)


def test_translation_replaces_text_in_selection_and_can_be_undone(app):
    from keyboard_shortcuts.capture_document import CaptureDocument
    from keyboard_shortcuts.capture_translation import translate_selection

    image = make_image(QRect(0, 0, 460, 125).size(), "white")
    painter = QPainter(image)
    font = QFont("Arial")
    font.setPixelSize(30)
    painter.setFont(font)
    painter.drawText(25, 65, "Hello world")
    painter.end()
    result = translate_selection(image)
    translated = result.image
    assert result.changed and any("\u3400" <= char <= "\u9fff" for char in result.text)
    assert translated.size() == image.size()
    assert translated.pixelColor(430, 110) == image.pixelColor(430, 110)
    assert translated != image
    recognized = extract_text(translated)
    assert any("\u3400" <= char <= "\u9fff" for char in recognized)
    assert "hello" not in recognized.casefold()
    rect = QRect(100, 80, image.width(), image.height())
    doc = CaptureDocument([(rect, image)])
    doc.region = rect
    before = doc.render()
    doc.apply_translation(translated)
    after = doc.render()
    assert after != before
    doc.undo()
    assert doc.render() == before
    doc.redo()
    assert doc.render() == after


def test_translation_uses_bundled_models_for_a_mixed_language_selection(app):
    from keyboard_shortcuts.capture_text import models_dir
    from keyboard_shortcuts.capture_translation import translate_selection

    if not (models_dir() / "nllb" / "model.bin").is_file():
        pytest.skip("bundled multilingual models are unavailable")
    image = make_image(QRect(0, 0, 820, 290).size(), "#181818")
    painter = QPainter(image)
    painter.setPen(QColor("#6aa6fa"))
    rows = (
        ("Microsoft PowerToys · 140.9k 星 ·", "Microsoft YaHei UI"),
        ("FancyZones 文档", "Microsoft YaHei UI"),
        ("Bonjour, comment allez-vous ?", "Segoe UI"),
        ("日本の首都は東京です。", "Yu Gothic UI"),
        ("Москва — столица России.", "Segoe UI"),
    )
    for index, (source, family) in enumerate(rows):
        font = QFont(family)
        font.setPixelSize(28)
        painter.setFont(font)
        painter.drawText(26, 45 + index * 48, source)
    painter.end()
    result = translate_selection(image)
    assert result.changed and result.image.size() == image.size()
    assert result.image != image
    text = result.text.splitlines()
    assert text[:2] == ["微软 PowerToys · 140.9k 星 ·", "FancyZones 文档"]
    assert "你好" in text[2] or "您好" in text[2]
    assert "东京" in text[3]
    assert "莫斯科" in text[4]


@pytest.mark.skipif(os.environ.get("KM_TEST_CLIPBOARD") != "1", reason="explicit system clipboard test")
def test_copy_cancel_and_finish_use_real_clipboard(app):
    clipboard = app.clipboard()
    previous = QMimeData()
    current = clipboard.mimeData()
    if current is not None:
        for name in current.formats():
            previous.setData(name, current.data(name))
    try:
        clipboard.setText("Keyboard Manager clipboard test")
        bounds = QRect(0, 0, 800, 600)
        screens = [(bounds, make_image(bounds.size(), "white"))]
        first = capture.CaptureSession(None, screens)
        first.document.region = QRect(0, 0, 120, 80)
        first.action("cancel")
        assert first.done and clipboard.text() == "Keyboard Manager clipboard test"
        second = capture.CaptureSession(None, screens)
        second.document.region = QRect(20, 20, 100, 70)
        second.action("copy")
        assert not second.done and clipboard.image().size() == second.document.region.size()
        second.action("finish")
        assert second.done and clipboard.image().size() == QRect(0, 0, 100, 70).size()
    finally:
        clipboard.setMimeData(previous)

