from dataclasses import replace
import os
from pathlib import Path

from PyQt5.QtCore import (
    QObject, QPoint, QRect, QRectF, QRunnable, QSaveFile, QThreadPool, QTimer,
    Qt, pyqtSignal, pyqtSlot,
)
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QImageWriter, QPainter, QPen
from PyQt5.QtWidgets import (
    QApplication, QColorDialog, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
    QInputDialog, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QWidget,
)

from .capture_document import CaptureDocument, Mark, clamp, handles, resize_region, toolbar_origin
from .capture_toolbar import ANNOTATIONS, CURSOR_HOTSPOTS, CaptureToolbar, tool_icon
from .capture_windows import capture_desktop, cursor_position, get_foreground, place_window, set_foreground
from .style import dialog_layout, stylesheet

BLUE = QColor("#0874ff")
CURSORS = {
    "nw": Qt.SizeFDiagCursor, "se": Qt.SizeFDiagCursor, "ne": Qt.SizeBDiagCursor,
    "sw": Qt.SizeBDiagCursor, "e": Qt.SizeHorCursor, "w": Qt.SizeHorCursor,
    "n": Qt.SizeVerCursor, "s": Qt.SizeVerCursor,
}
DIALOG_STYLE = stylesheet(dark=False)


class Overlay(QWidget):
    def __init__(self, session, rect):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.session = session
        self.screen_rect = QRect(rect)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setAccessibleName("截图选区")
        self.toolbar = CaptureToolbar(self, session.action, session.edit_style)
        self.toolbar.hide()
        self.notice = QLabel(self)
        self.notice.setStyleSheet("background: #ffffff; color: #151515; border-radius: 6px; padding: 7px 13px;")
        self.notice.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.notice.hide()

    @property
    def scale_x(self):
        return self.screen_rect.width() / max(1, self.width())

    @property
    def scale_y(self):
        return self.screen_rect.height() / max(1, self.height())

    def local_point(self, point):
        origin = self.screen_rect.topLeft()
        return QPoint(round((point.x() - origin.x()) / self.scale_x),
                      round((point.y() - origin.y()) / self.scale_y))

    def resizeEvent(self, event):
        if self.session.ready:
            self.session.refresh()

    def paintEvent(self, event):
        doc = self.session.document
        painter = QPainter(self)
        painter.scale(1 / self.scale_x, 1 / self.scale_y)
        painter.translate(-self.screen_rect.topLeft())
        painter.fillRect(self.screen_rect, Qt.black)
        doc.background(painter, self.screen_rect)
        painter.fillRect(self.screen_rect, QColor(0, 0, 0, 165))
        if doc.region.isEmpty():
            painter.end()
            return
        painter.save()
        painter.setClipRect(doc.region)
        doc.background(painter, self.screen_rect.intersected(doc.region))
        doc.paint_marks(painter, self.session.pending)
        painter.restore()
        point = self.session.eraser_point
        if self.session.tool == "erase" and point is not None and doc.region.contains(point):
            painter.setPen(QPen(Qt.white, self.scale_x * 2))
            painter.setBrush(Qt.NoBrush)
            radius = self.session.eraser_radius
            circle = QRectF(point.x() - radius, point.y() - radius, radius * 2, radius * 2)
            painter.drawEllipse(circle)
            painter.setPen(QPen(Qt.black, self.scale_x, Qt.DashLine))
            painter.drawEllipse(circle)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(BLUE, self.scale_x * 1.5))
        painter.drawRect(QRectF(doc.region))
        if self.session.selected is not None and self.session.selected < len(doc.marks):
            mark = doc.marks[self.session.selected]
            painter.save()
            painter.setClipRect(doc.region)
            painter.setPen(QPen(BLUE, self.scale_x, Qt.DashLine))
            painter.drawRect(mark.path().boundingRect().adjusted(-5, -5, 5, 5))
            painter.restore()
        if self.session.operation != "select_region":
            painter.setBrush(Qt.white)
            radius = 5.5 * self.scale_x
            for point in handles(doc.region).values():
                if self.screen_rect.adjusted(0, 0, 1, 1).contains(point):
                    x = clamp(point.x(), self.screen_rect.left() + radius, self.screen_rect.right() - radius)
                    y = clamp(point.y(), self.screen_rect.top() + radius, self.screen_rect.bottom() - radius)
                    painter.drawRect(QRectF(x - radius, y - radius, 2 * radius, 2 * radius))
        painter.end()
        if self.session.label_screen() is self:
            self.paint_dimensions(doc.region)

    def paint_dimensions(self, region):
        origin = self.local_point(region.topLeft())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(16)
        painter.setFont(font)
        value = f"{region.width()} × {region.height()}"
        width = QFontMetrics(font).horizontalAdvance(value) + 20
        label = QRect(clamp(origin.x(), 1, self.width() - width - 1),
                      origin.y() - 35 if origin.y() >= 36 else min(self.height() - 31, origin.y() + 10),
                      width, 30)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#0064ef"))
        painter.drawRoundedRect(label, 5, 5)
        painter.setPen(Qt.white)
        painter.drawText(label, Qt.AlignCenter, value)

    def mousePressEvent(self, event):
        if event.button() in (Qt.LeftButton, Qt.RightButton):
            self.session.press(cursor_position(), reselect=event.button() == Qt.RightButton)
            event.accept()

    def mouseMoveEvent(self, event):
        point = cursor_position()
        self.session.move(point)
        self.setCursor(self.session.cursor(point, self.scale_x))

    def leaveEvent(self, event):
        if self.session.operation != "erase":
            self.session.eraser_point = None
            self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() in (Qt.LeftButton, Qt.RightButton):
            self.session.release(cursor_position(), self)
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.session.edit_selected(cursor_position(), self)

    def keyPressEvent(self, event):
        control = bool(event.modifiers() & Qt.ControlModifier)
        key = event.key()
        if control and key in (Qt.Key_Z, Qt.Key_Y, Qt.Key_C, Qt.Key_S):
            self.session.action({Qt.Key_Z: "undo", Qt.Key_Y: "redo", Qt.Key_C: "copy", Qt.Key_S: "save"}[key])
        elif key == Qt.Key_Escape:
            self.session.escape()
        elif key == Qt.Key_Delete and self.session.selected is not None:
            self.session.action("delete")
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if self.session.ready:
            event.ignore()
            QTimer.singleShot(0, self.session.close)
        else:
            event.accept()


class TextSignals(QObject):
    finished = pyqtSignal(object, object)


class ReadText(QRunnable):
    def __init__(self, image, translate=False, python=None):
        super().__init__()
        self.image = image
        self.translate = translate
        self.python = python
        self.signals = TextSignals()

    def run(self):
        try:
            if self.translate:
                from .capture_translation import translate_selection
                result = translate_selection(self.image, self.python)
            else:
                from .capture_text import extract_text
                result = extract_text(self.image)
        except Exception as error:
            self.signals.finished.emit(None, str(error))
            return
        self.signals.finished.emit(result, None)


class CaptureSession(QObject):
    closed = pyqtSignal()

    def __init__(self, parent, screens=None):
        super().__init__(parent)
        self.foreground = get_foreground()
        self.document = CaptureDocument(screens if screens is not None else capture_desktop())
        self.ready = False
        self.windows = [Overlay(self, rect) for rect, _ in self.document.screens]
        self.tool = "select"
        self.tool_cursors = {tool: tool_icon(tool, for_cursor=True) for tool in CURSOR_HOTSPOTS}
        self.operation = None
        self.eraser_radius = 12
        self.eraser_point = None
        self.translation_state = None
        self.translation_python = os.environ.get("KM_MANGA_TRANSLATOR_PYTHON")
        root = os.environ.get("KM_MANGA_TRANSLATOR_ROOT")
        if root and not self.translation_python:
            candidates = (Path(root) / env / "Scripts" / "python.exe" for env in (".venv", "venv"))
            self.translation_python = next((str(path) for path in candidates if path.is_file()), None)
        self.selected = None
        self.pending = None
        self.styles = {tool: ("#e62324", 3, 24) for tool in ANNOTATIONS}
        self.host = None
        self.busy = False
        self.dialog = None
        self.toast_generation = 0
        self.done = False

    def show(self):
        target = next((window for window in self.windows if window.screen_rect.contains(cursor_position())),
                      self.windows[0])
        for window in self.windows:
            place_window(window, window.screen_rect)
            window.show()
            place_window(window, window.screen_rect)
        self.ready = True
        self.refresh()
        target.activateWindow()
        target.setFocus()
        set_foreground(int(target.winId()))

    def close(self, restore=True):
        if self.done:
            return
        self.done = True
        self.ready = False
        if self.dialog is not None:
            self.dialog.reject()
        for window in self.windows:
            window.close()
        self.windows.clear()
        if restore and self.foreground:
            set_foreground(self.foreground)
        self.closed.emit()
        self.deleteLater()

    def label_screen(self):
        return next((window for window in self.windows
                     if window.screen_rect.contains(self.document.region.topLeft())), self.host)

    def refresh(self):
        if not self.ready:
            return
        region = self.document.region
        if region.isEmpty():
            self.host = None
        else:
            def overlap(window):
                area = window.screen_rect.intersected(region)
                return area.width() * area.height()
            candidate = max(self.windows, key=overlap)
            # Keep the current monitor around equal coverage to avoid seam flicker.
            if self.host is None or overlap(self.host) < overlap(candidate) * .90:
                self.host = candidate
        for window in self.windows:
            visible = window is self.host and self.operation != "select_region"
            if visible:
                toolbar = window.toolbar
                toolbar.fit(max(80, window.width() - 24))
                width = round(toolbar.width() * window.scale_x)
                height = round(toolbar.height() * window.scale_y)
                rect = region.intersected(window.screen_rect)
                point = toolbar_origin(rect, window.screen_rect, width, height, round(14 * window.scale_y))
                toolbar.move(window.local_point(point))
                toolbar.update_state(self.tool, bool(self.document.previous), bool(self.document.following),
                                     self.busy, self.tool_cursors.get(self.tool))
                toolbar.show()
                toolbar.raise_()
                if window.notice.isVisible():
                    window.notice.move(clamp(toolbar.x(), 4, window.width() - window.notice.width() - 4),
                                       max(4, toolbar.y() - window.notice.height() - 5))
                    window.notice.raise_()
            else:
                window.toolbar.hide()
                window.notice.hide()
            window.update()

    def handle_at(self, point):
        window = next((w for w in self.windows if w.screen_rect.contains(point)), None)
        distance = round(9 * window.scale_x) if window else 9
        for name, handle in handles(self.document.region).items():
            if max(abs(point.x() - handle.x()), abs(point.y() - handle.y())) <= distance:
                return name
        return None

    def cursor(self, point, scale):
        if self.document.region.contains(point) and self.tool in self.tool_cursors:
            return self.tool_cursors[self.tool]
        if self.tool == "select" and not self.document.region.isEmpty():
            handle = self.handle_at(point)
            if handle:
                return CURSORS[handle]
            if self.document.region.contains(point):
                return Qt.SizeAllCursor
        return Qt.IBeamCursor if self.tool == "text" else Qt.CrossCursor

    def press(self, point, *, reselect=False):
        doc = self.document
        self.before = doc.state()
        self.anchor = point
        self.selected = None
        handle = self.handle_at(point) if self.tool == "select" and not doc.region.isEmpty() else None
        if reselect:
            self.operation = "select_region"
            self.tool = "select"
        elif handle:
            self.operation = "resize"
            self.handle = handle
        elif doc.region.isEmpty() or not doc.region.contains(point):
            self.operation = "select_region"
            self.tool = "select"
        elif self.tool == "select":
            self.selected = doc.hit(point, 8)
            self.operation = "move_region" if self.selected is None else "move_mark"
        elif self.tool == "erase":
            self.operation = "erase"
            self.eraser_point = point
            doc.erase_segment(point, point, self.eraser_radius)
        elif self.tool == "text":
            self.operation = "text"
        else:
            self.operation = "draw"
            color, width, size = self.styles[self.tool]
            self.pending = Mark(self.tool, (point, point), color, width, font_size=size)
        self.refresh()

    def move(self, point):
        if self.tool == "erase":
            if self.operation == "erase" and point != self.eraser_point:
                self.document.erase_segment(self.eraser_point, point, self.eraser_radius)
            self.eraser_point = point
            for window in self.windows:
                window.update()
            return
        if self.operation is None:
            return
        doc = self.document
        region, marks = self.before
        delta = point - self.anchor
        if self.operation == "select_region":
            if delta.manhattanLength() < 2:
                return
            doc.region = QRect(self.anchor, point).normalized().intersected(doc.bounds)
            doc.marks = ()
        elif self.operation == "resize":
            doc.region = resize_region(region, self.handle, delta, doc.bounds)
        elif self.operation == "move_region":
            x = clamp(region.x() + delta.x(), doc.bounds.left(), doc.bounds.right() - region.width() + 1)
            y = clamp(region.y() + delta.y(), doc.bounds.top(), doc.bounds.bottom() - region.height() + 1)
            doc.move_region(QRect(x, y, region.width(), region.height()))
        elif self.operation == "move_mark":
            doc.replace(self.selected, marks[self.selected].shifted(delta))
        elif self.operation == "draw":
            point = QPoint(clamp(point.x(), region.left(), region.right()),
                           clamp(point.y(), region.top(), region.bottom()))
            points = self.pending.points
            if self.tool == "line":
                if points[-1] == point:
                    return
                points += (point,)
            else:
                points = (self.anchor, point)
            self.pending = replace(self.pending, points=points)
        self.refresh()

    def release(self, point, owner):
        operation = self.operation
        if operation is None:
            return
        self.move(point)
        self.operation = None
        doc = self.document
        if operation == "draw":
            if len(set((p.x(), p.y()) for p in self.pending.points)) > 1:
                doc.add(self.pending)
            self.pending = None
        elif operation == "text":
            color, width, size = self.styles["text"]
            mark = self.text_dialog(owner, Mark("text", (self.anchor,), color, width, font_size=size))
            if mark is not None and not self.done:
                doc.add(mark)
        elif operation == "select_region" and self.before[0].isEmpty():
            doc.previous.clear()
            doc.following.clear()
        else:
            doc.record(self.before)
        self.refresh()

    def escape(self):
        if self.operation is not None:
            self.document.region, self.document.marks = self.before
            self.pending = self.operation = None
        elif self.tool != "select" or self.selected is not None:
            self.tool, self.selected = "select", None
        else:
            self.close()
        self.refresh()

    def action(self, key):
        if self.done or self.dialog is not None:
            return
        doc = self.document
        if key == "cancel":
            self.close()
            return
        if doc.region.isEmpty() or self.operation is not None:
            return
        if key in ("select", *ANNOTATIONS, "erase"):
            if key == self.tool and key in ANNOTATIONS:
                self.edit_style(key, None)
            else:
                self.tool, self.selected = key, None
                point = cursor_position()
                for window in self.windows:
                    window.setCursor(self.cursor(point, window.scale_x))
        elif key == "undo":
            doc.undo()
            self.selected = None
        elif key == "redo":
            doc.redo()
            self.selected = None
        elif key == "delete" and self.selected is not None:
            doc.erase(self.selected)
            self.selected = None
        elif key == "translate" and not self.busy:
            self.translate_region()
        elif key in ("copy", "finish", "save", "ocr"):
            try:
                image = doc.render()
                if key == "save":
                    self.save_image(image)
                elif key == "ocr" and not self.busy:
                    self.read_text(image)
                elif key in ("copy", "finish"):
                    QApplication.clipboard().setImage(image)
                    if key == "finish":
                        self.close()
                    else:
                        self.notify("已复制")
            except (OSError, RuntimeError, ValueError, MemoryError) as error:
                QMessageBox.warning(self.host, "截图操作失败", str(error))
        self.refresh()

    def notify(self, value):
        if self.host is None:
            return
        notice = self.host.notice
        notice.setText(value)
        notice.adjustSize()
        notice.show()
        self.toast_generation += 1
        generation = self.toast_generation
        def hide():
            if not self.done and self.toast_generation == generation:
                notice.hide()
        QTimer.singleShot(1600, hide)

    def save_image(self, image):
        dialog = QFileDialog(self.host, "另存为")
        dialog.setAcceptMode(QFileDialog.AcceptSave)
        dialog.setNameFilters(["PNG 图片 (*.png)", "JPEG 图片 (*.jpg *.jpeg)"])
        dialog.selectFile("截图")
        self.dialog = dialog
        try:
            if not dialog.exec_():
                return
            name = Path(dialog.selectedFiles()[0])
            suffix = name.suffix.lower()
            if not suffix:
                name = name.with_suffix(".jpg" if dialog.selectedNameFilter().startswith("JPEG") else ".png")
                suffix = name.suffix
            if suffix not in (".png", ".jpg", ".jpeg"):
                raise ValueError("请选择 PNG 或 JPG 图片格式。")
            file = QSaveFile(str(name))
            if not file.open(QSaveFile.WriteOnly):
                raise OSError(file.errorString())
            writer = QImageWriter(file, b"png" if suffix == ".png" else b"jpeg")
            writer.setQuality(95)
            if not writer.write(image):
                file.cancelWriting()
                raise OSError(writer.errorString())
            if not file.commit():
                raise OSError(file.errorString())
            self.notify("已另存为")
        finally:
            self.dialog = None
            dialog.deleteLater()

    def translate_region(self):
        try:
            image = self.document.render(marks=False)
        except (ValueError, MemoryError) as error:
            QMessageBox.warning(self.host, "原位翻译", str(error))
            return
        self.translation_state = self.document.state()
        self.read_text(image, translate=True)

    def read_text(self, image, translate=False):
        self.busy = True
        self.notify("正在识别并原位翻译…" if translate else "正在离线识别…")
        worker = ReadText(image, translate, self.translation_python)
        self.worker = worker
        worker.signals.finished.connect(self.text_ready, Qt.QueuedConnection)
        QThreadPool.globalInstance().start(worker)

    @pyqtSlot(object, object)
    def text_ready(self, result, error):
        if self.done:
            return
        if self.dialog is not None or self.operation is not None:
            QTimer.singleShot(150, lambda: self.text_ready(result, error))
            return
        self.worker = None
        self.busy = False
        before, self.translation_state = self.translation_state, None
        self.refresh()
        if result is None:
            QMessageBox.warning(self.host, "原位翻译" if before is not None else "提取文字", error)
            return
        title = "提取文字"
        if before is not None:
            if self.document.state() != before:
                self.notify("选区或标注已修改，请重新翻译")
                return
            if result.changed:
                self.document.apply_translation(result.image)
                self.selected = None
                self.notify("已替换选区文字")
                self.refresh()
            title = "简体中文译文"
            result = result.text
        dialog = QDialog(self.host)
        dialog.setWindowTitle(title)
        dialog.setStyleSheet(DIALOG_STYLE)
        dialog.resize(560, 340)
        layout = dialog_layout(dialog)
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(result)
        layout.addWidget(editor)
        copy = QPushButton("复制所选或全部")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(
            editor.textCursor().selectedText().replace("\u2029", "\n") or editor.toPlainText()))
        layout.addWidget(copy, alignment=Qt.AlignRight)
        if before is not None:
            host = self.host
            selection = self.document.region.intersected(host.screen_rect)
            region = QRect(host.mapToGlobal(host.local_point(selection.topLeft())),
                           host.mapToGlobal(host.local_point(selection.bottomRight())))
            screen = host.screen().availableGeometry().adjusted(12, 12, -12, -12)
            dialog.resize(dialog.size().boundedTo(screen.size()))
            width, height = dialog.width(), dialog.height()
            origins = (
                QPoint(region.right() + 12, region.top()),
                QPoint(region.left() - width - 12, region.top()),
                QPoint(region.left(), region.bottom() + 12),
                QPoint(region.left(), region.top() - height - 12),
            )
            positions = [
                QPoint(clamp(point.x(), screen.left(), screen.right() - width + 1),
                       clamp(point.y(), screen.top(), screen.bottom() - height + 1))
                for point in origins
            ]

            def overlap(point):
                area = QRect(point, dialog.size()).intersected(region)
                return area.width() * area.height()

            dialog.move(min(positions, key=overlap))
        self.dialog = dialog
        dialog.exec_()
        self.dialog = None
        dialog.deleteLater()

    def edit_selected(self, point, owner):
        if self.tool != "select" or not self.document.region.contains(point):
            return
        index = self.document.hit(point, 8)
        if index is None:
            return
        mark = self.document.marks[index]
        if mark.kind == "text":
            result = self.text_dialog(owner, mark)
        else:
            style = self.style_dialog(owner, mark.color, mark.width, mark.font_size, False)
            result = replace(mark, color=style[0], width=style[1]) if style else None
        if result is not None and not self.done:
            before = self.document.state()
            self.document.replace(index, result)
            self.document.record(before)
            self.selected = index
            self.refresh()

    def edit_style(self, key, position):
        if self.host is None:
            return
        if key == "erase":
            dialog = QInputDialog(self.host)
            dialog.setWindowTitle("橡皮擦大小")
            dialog.setLabelText("擦除半径（像素）")
            dialog.setInputMode(QInputDialog.IntInput)
            dialog.setIntRange(2, 80)
            dialog.setIntValue(self.eraser_radius)
            self.dialog = dialog
            try:
                if dialog.exec_():
                    self.eraser_radius = dialog.intValue()
            finally:
                self.dialog = None
                self.refresh()
            return
        result = self.style_dialog(self.host, *self.styles[key], key == "text", position=position)
        if result:
            self.styles[key] = result

    def style_dialog(self, owner, color, width, size, text, position=None):
        dialog = QDialog(owner)
        dialog.setWindowTitle("标注样式")
        dialog.setStyleSheet(DIALOG_STYLE)
        layout = QFormLayout(dialog)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        tint = self.color_field(dialog, color)
        layout.addRow("颜色", tint)
        spin = QSpinBox()
        spin.setRange(8, 160) if text else spin.setRange(1, 40)
        spin.setValue(size if text else width)
        layout.addRow("字号" if text else "粗细", spin)
        layout.addRow(self.accept_buttons(dialog))
        if position is not None:
            dialog.adjustSize()
            screen = QApplication.screenAt(position)
            if screen:
                area = screen.availableGeometry()
                position = QPoint(clamp(position.x(), area.left(), area.right() - dialog.width()),
                                  clamp(position.y(), area.top(), area.bottom() - dialog.height()))
            dialog.move(position)
        self.dialog = dialog
        result = (tint.property("color"), width if text else spin.value(), spin.value() if text else size) if dialog.exec_() else None
        self.dialog = None
        dialog.deleteLater()
        return result

    def text_dialog(self, owner, mark):
        dialog = QDialog(owner)
        dialog.setWindowTitle("文字标注")
        dialog.setStyleSheet(DIALOG_STYLE)
        dialog.setMinimumWidth(330)
        layout = QFormLayout(dialog)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        field = QPlainTextEdit(mark.text)
        field.setPlaceholderText("输入标注文字")
        field.setFixedHeight(82)
        layout.addRow("内容", field)
        size = QSpinBox()
        size.setRange(8, 160)
        size.setValue(mark.font_size)
        layout.addRow("字号", size)
        color = self.color_field(dialog, mark.color)
        layout.addRow("颜色", color)
        layout.addRow(self.accept_buttons(dialog))
        self.dialog = dialog
        field.setFocus()
        accepted = dialog.exec_()
        self.dialog = None
        value = field.toPlainText()
        result = replace(mark, text=value, color=color.property("color"), font_size=size.value()) if accepted and value.strip() else None
        dialog.deleteLater()
        return result

    @staticmethod
    def color_field(owner, color):
        button = QPushButton()
        def update(value):
            button.setProperty("color", value)
            button.setText(value)
            button.setStyleSheet(f"border-left: 14px solid {value}; padding: 5px 8px;")
        def select():
            tint = QColorDialog.getColor(QColor(button.property("color")), owner, "选择标注颜色")
            if tint.isValid():
                update(tint.name())
        update(color)
        button.clicked.connect(select)
        return button

    @staticmethod
    def accept_buttons(dialog):
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch()
        for name, action in (("取消", dialog.reject), ("确定", dialog.accept)):
            button = QPushButton(name)
            button.setProperty("primary", name == "确定")
            button.clicked.connect(action)
            row.addWidget(button)
        return widget

