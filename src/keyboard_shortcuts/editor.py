from pathlib import Path

from PyQt5.QtCore import QEvent, QEventLoop, QThread, Qt
from PyQt5.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QListWidget,
    QMessageBox, QPushButton, QSizePolicy,
)

from .rules import KEYS, Rule, canonical, label
from .style import ComboBox, dialog_layout
from .windows import event_key, running_apps


class EngineTransition(QThread):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.error = None

    def run(self):
        try:
            self.operation()
        except (OSError, RuntimeError) as error:
            self.error = error

    def complete(self):
        loop = QEventLoop()
        self.finished.connect(loop.quit, Qt.QueuedConnection)
        self.start()
        loop.exec_(QEventLoop.ExcludeUserInputEvents)
        self.wait()
        if self.error is not None:
            raise self.error


def button(title, action, primary=False):
    result = QPushButton(title)
    result.clicked.connect(action)
    if primary:
        result.setProperty("primary", True)
    return result


def keycaps(keys):
    box = QHBoxLayout()
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(5)
    if len(keys) > 2:
        chord = "  +  ".join(map(label, keys))
        cap = QLabel(chord)
        cap.setObjectName("keycap")
        cap.setWordWrap(True)
        cap.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        cap.setToolTip(chord)
        box.addWidget(cap)
        return box
    for key in keys:
        cap = QLabel(label(key))
        cap.setObjectName("keycap")
        cap.setAlignment(Qt.AlignCenter)
        box.addWidget(cap)
    box.addStretch()
    return box


def buttons(dialog, title="确认"):
    bar = QDialogButtonBox()
    accept = bar.addButton(title, QDialogButtonBox.AcceptRole)
    accept.setProperty("primary", True)
    bar.addButton("取消", QDialogButtonBox.RejectRole)
    bar.rejected.connect(dialog.reject)
    bar.accepted.connect(dialog.accept)
    return bar


class Recorder(QDialog):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(405)
        self.keys = ()
        self.pressed = set()
        self.layout = dialog_layout(self)
        heading = QLabel(title)
        heading.setObjectName("section")
        self.layout.addWidget(heading)
        self.layout.addWidget(QLabel("按下要使用的单键或组合键。"))
        self.preview = QLabel()
        self.preview.setObjectName("capture")
        self.preview.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.preview)
        row = buttons(self)
        row.addButton(button("重新录制", self.clear), QDialogButtonBox.ResetRole)
        self.layout.addWidget(row)
        for control in row.buttons():
            control.setAutoDefault(False)
            control.setFocusPolicy(Qt.NoFocus)
        self.setFocusPolicy(Qt.StrongFocus)
        self.clear()

    def clear(self):
        self.keys = ()
        self.pressed.clear()
        self.preview.setText("等待输入…")
        self.setFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        key = event_key(event)
        if key in KEYS and not event.isAutoRepeat() and key not in self.pressed:
            if not self.pressed:
                self.keys = ()
            self.pressed.add(key)
            if key not in self.keys and len(self.keys) < 8:
                self.keys = canonical(self.keys + (key,))
                self.preview.setText("  +  ".join(map(label, self.keys)))
        event.accept()

    def keyReleaseEvent(self, event):
        if not event.isAutoRepeat():
            self.pressed.discard(event_key(event))
        event.accept()

    def changeEvent(self, event):
        if event.type() == QEvent.ActivationChange and not self.isActiveWindow():
            self.pressed.clear()
        super().changeEvent(event)

    def accept(self):
        if self.keys:
            super().accept()


class KeyPicker(QDialog):
    def __init__(self, parent, keys):
        super().__init__(parent)
        self.setWindowTitle("从列表选择按键")
        self.keys = keys
        self.resize(420, 450)
        layout = dialog_layout(self)
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.MultiSelection)
        for key in KEYS:
            self.list.addItem(label(key))
            self.list.item(self.list.count() - 1).setSelected(key in keys)
        layout.addWidget(self.list)
        layout.addWidget(buttons(self))

    def accept(self):
        try:
            self.keys = canonical(tuple(KEYS[self.list.row(item)] for item in self.list.selectedItems()))
        except ValueError as error:
            QMessageBox.warning(self, "选择按键", str(error))
            return
        super().accept()


class ApplicationPicker(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("选择应用")
        self.setMinimumWidth(440)
        self.path = None
        self.apps = running_apps()
        self.resize(500, 390)
        layout = dialog_layout(self)
        layout.addWidget(QLabel("从正在运行的应用中选择，或浏览程序文件。"))
        self.list = QListWidget()
        for name, path in self.apps:
            self.list.addItem(f"{name}  ·  {Path(path).name}")
            self.list.item(self.list.count() - 1).setToolTip(path)
        self.list.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.list)
        row = buttons(self)
        row.addButton(button("浏览程序", self.browse), QDialogButtonBox.ActionRole)
        layout.addWidget(row)

    def accept(self):
        if self.list.currentRow() >= 0:
            self.path = self.apps[self.list.currentRow()][1]
            super().accept()

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择程序", "", "程序 (*.exe)")
        if path:
            self.path = path
            super().accept()


class RuleEditor(QDialog):
    def __init__(self, parent, engine, rule=None):
        super().__init__(parent)
        self.setWindowTitle("编辑映射" if rule else "添加映射")
        self.setMinimumWidth(510)
        self.engine = engine
        self.rule = rule
        self.source = rule.source if rule else ()
        self.target = rule.target if rule else ()
        self.path = rule.app_path if rule else None
        self.views = {}
        layout = dialog_layout(self)
        heading = QLabel(self.windowTitle())
        heading.setObjectName("section")
        layout.addWidget(heading)
        for side, title in (("source", "原始按键"), ("target", "映射为")):
            layout.addWidget(QLabel(title))
            row = QHBoxLayout()
            self.views[side] = QLabel()
            self.views[side].setObjectName("capture")
            row.addWidget(self.views[side], 1)
            row.addWidget(button("录制", lambda _, side=side: self.pick(side, True)))
            row.addWidget(button("列表", lambda _, side=side: self.pick(side, False)))
            layout.addLayout(row)
            self.refresh(side)
        layout.addWidget(QLabel("生效范围"))
        row = QHBoxLayout()
        self.scope = ComboBox()
        self.scope.setAccessibleName("生效范围")
        self.scope.addItems(["所有应用", "指定程序"])
        self.scope.setCurrentIndex(bool(self.path))
        row.addWidget(self.scope, 1)
        self.choose = button("选择应用", self.select_application)
        row.addWidget(self.choose)
        self.choose.setEnabled(bool(self.path))
        self.scope.currentIndexChanged.connect(lambda index: self.choose.setEnabled(bool(index)))
        layout.addLayout(row)
        self.app = QLabel(self.path or "")
        self.app.setObjectName("muted")
        self.app.setTextFormat(Qt.PlainText)
        self.app.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.app.setWordWrap(True)
        layout.addWidget(self.app)
        layout.addWidget(buttons(self, "保存"))

    def refresh(self, side):
        view = self.views[side]
        view.setWordWrap(True)
        view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        view.setText("  +  ".join(map(label, getattr(self, side))) or "未设置")

    def pick(self, side, record):
        if record:
            dialog = Recorder(self, "录制原始输入" if side == "source" else "录制映射输出")
            try:
                with self.parentWidget().suspend_recording_input():
                    accepted = dialog.exec_()
            except (OSError, RuntimeError) as error:
                QMessageBox.warning(self, "无法录制", str(error))
                return
        else:
            dialog = KeyPicker(self, getattr(self, side))
            accepted = dialog.exec_()
        if accepted:
            setattr(self, side, dialog.keys)
            self.refresh(side)

    def select_application(self):
        dialog = ApplicationPicker(self)
        if dialog.exec_():
            self.path = dialog.path
            self.app.setText(self.path)

    def accept(self):
        try:
            if self.scope.currentIndex() and not self.path:
                raise ValueError("请选择应用。")
            self.rule = Rule(self.source, self.target, self.path if self.scope.currentIndex() else None,
                             self.rule.enabled if self.rule else True)
        except ValueError as error:
            QMessageBox.warning(self, "检查映射", str(error))
            return
        super().accept()

