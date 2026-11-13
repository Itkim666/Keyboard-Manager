from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import sys

from PyQt5.QtCore import QSize, Qt, QTimer
from PyQt5.QtGui import QColor, QIcon, QKeySequence, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QRadioButton, QScrollArea,
    QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget, QKeySequenceEdit,
)

from . import NAME, VERSION
from .editor import EngineTransition, RuleEditor, button, buttons, keycaps
from .engine import EngineError
from .rules import default_rules, find_conflict, label
from .store import DEFAULT_CAPTURE_HOTKEY, Config, Settings, load_config, merge_config, save_config
from .hotkeys import CAPTURE_MESSAGE, LEFT_CAPTURE, Hotkeys, capture_label, shortcut_plan
from .style import ComboBox, dialog_layout, navigation_icon
from .windows import login_registered, set_login


class HotkeyEdit(QKeySequenceEdit):
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.window().reject()
            return
        super().keyPressEvent(event)


def icon():
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.transparent)
    paint = QPainter(pixmap)
    paint.setRenderHint(QPainter.Antialiasing)
    paint.setPen(Qt.NoPen)
    paint.setBrush(QColor("#0067c0"))
    paint.drawRoundedRect(0, 0, 48, 48, 11, 11)
    paint.setBrush(QColor("white"))
    paint.drawRoundedRect(9, 14, 30, 20, 4, 4)
    paint.setBrush(QColor("#0067c0"))
    for y in (18, 23):
        for x in range(13, 35, 5):
            paint.drawRoundedRect(x, y, 3, 3, 1, 1)
    paint.drawRoundedRect(16, 28, 16, 3, 1, 1)
    paint.end()
    return QIcon(pixmap)


def text(value, role=""):
    result = QLabel(value)
    result.setObjectName(role)
    return result


def card():
    widget = QFrame()
    widget.setObjectName("card")
    return widget


class Switch(QCheckBox):
    def __init__(self, checked, accessible_name):
        super().__init__()
        self.setChecked(checked)
        self.setAccessibleName(accessible_name)
        self.setToolTip(accessible_name)
        self.setFixedSize(50, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)

    def hitButton(self, position):
        return self.rect().contains(position)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        if self.isDown():
            track = "#004f94" if self.isChecked() else "#515863"
        elif self.underMouse():
            track = "#075ca4" if self.isChecked() else "#646c77"
        else:
            track = "#0067c0" if self.isChecked() else "#777e87"
        p.setBrush(QColor(track))
        p.setOpacity(1 if self.isEnabled() else .48)
        p.drawRoundedRect(2, 6, 46, 22, 11, 11)
        p.setBrush(QColor("white"))
        p.drawEllipse(28 if self.isChecked() else 6, 9, 16, 16)
        if self.hasFocus():
            p.setBrush(Qt.NoBrush)
            p.setPen(QColor("#1a8de5"))
            p.drawRoundedRect(0, 4, 49, 26, 12, 12)


class MainWindow(QWidget):
    def __init__(self, engine, path, config, *, smoke=False):
        super().__init__()
        self.engine = engine
        self.path = path
        self.config = config
        self.smoke = smoke
        self.hotkeys = Hotkeys()
        self.recording_hotkey = False
        self.capture_session = None
        self.capture_warning = ""
        self.tray = None
        self.exiting = False
        self.setWindowTitle(NAME)
        self.setWindowIcon(icon())
        self.resize(1160, 780)
        self.setMinimumSize(850, 560)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(212)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(12, 22, 12, 18)
        nav.setSpacing(6)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(self.windowIcon().pixmap(33, 33))
        brand.addWidget(logo)
        brand.addWidget(text(NAME, "brand"))
        brand.addStretch()
        nav.addLayout(brand)
        nav.addSpacing(16)
        self.pages = QStackedWidget()
        self.navigation = []
        for index, title in enumerate(("映射规则", "常规设置", "备份与恢复")):
            control = button(title, lambda _, index=index: self.go(index))
            control.setObjectName("navigation")
            control.setCheckable(True)
            control.setIconSize(QSize(20, 20))
            nav.addWidget(control)
            self.navigation.append(control)
        nav.addStretch()
        self.footer = text("", "muted")
        nav.addWidget(self.footer)
        root.addWidget(sidebar)
        root.addWidget(self.pages, 1)
        self.mapping = self.page("键盘映射", "将单键或组合键映射为其他按键，适用于所有应用或指定程序。")
        self.general = self.page("常规设置", "配置 Keyboard Manager 的基本选项。")
        self.backup = self.page("备份与恢复", "备份当前的键盘映射和设置，或从备份文件恢复。")
        self.create_mapping()
        self.create_settings()
        self.create_backup()
        if not smoke:
            self.create_tray()
            try:
                fallback = replace(config.settings, capture_hotkey="")
                self.hotkeys.replace(int(self.winId()), shortcut_plan(fallback, config.rules))
            except (ValueError, OSError) as error:
                QTimer.singleShot(100, lambda msg=str(error): self.warning("暂停快捷键", msg))
                fallback = replace(fallback, pause_hotkey="")
            try:
                self.hotkeys.observe_capture(int(self.winId()))
                self.hotkeys.replace(int(self.winId()), shortcut_plan(
                    replace(fallback, capture_hotkey=config.settings.capture_hotkey), config.rules))
            except (ValueError, OSError) as error:
                self.capture_warning = str(error)
        self.go(0)
        self.refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(1200)

    def page(self, title, description):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("content")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(30, 28, 30, 30)
        layout.setSpacing(12)
        layout.addWidget(text(title, "headline"))
        subtitle = text(description, "subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        layout.addSpacing(6)
        scroll.setWidget(body)
        self.pages.addWidget(scroll)
        return layout

    def go(self, index):
        self.pages.setCurrentIndex(index)
        for i, control in enumerate(self.navigation):
            control.setChecked(i == index)

    def row(self, layout, glyph, title, description, control):
        frame = card()
        row = QHBoxLayout(frame)
        row.setContentsMargins(14, 11, 14, 11)
        row.setSpacing(12)
        badge = text(glyph, "badge")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(40, 40)
        row.addWidget(badge)
        column = QVBoxLayout()
        column.setSpacing(2)
        name, detail = text(title, "cardTitle"), text(description, "muted")
        detail.setWordWrap(True)
        column.addWidget(name)
        column.addWidget(detail)
        row.addLayout(column, 1)
        row.addWidget(control)
        layout.addWidget(frame)
        return name, detail

    def create_mapping(self):
        self.error_box = card()
        self.error_box.setObjectName("error")
        bar = QHBoxLayout(self.error_box)
        self.error_text = text("")
        self.error_text.setWordWrap(True)
        bar.addWidget(self.error_text, 1)
        bar.addWidget(button("重试", self.retry))
        self.mapping.addWidget(self.error_box)
        self.master = Switch(True, "启用键盘映射")
        self.master.clicked.connect(self.toggle)
        self.status, self.detail = self.row(
            self.mapping, "⌨", "键盘映射", "", self.master
        )
        self.mapping.addSpacing(4)
        title = QHBoxLayout()
        column = QVBoxLayout()
        column.addWidget(text("映射列表", "section"))
        self.count = text("", "muted")
        column.addWidget(self.count)
        title.addLayout(column, 1)
        title.addWidget(button("＋ 添加映射", lambda: self.edit_rule(), True))
        self.mapping.addLayout(title)
        filters = QHBoxLayout()
        filters.setSpacing(10)
        self.search = QLineEdit()
        self.search.setMinimumWidth(160)
        self.search.setPlaceholderText("搜索按键、映射或应用")
        self.search.setAccessibleName("搜索映射")
        self.search.textChanged.connect(self.render_rules)
        filters.addWidget(self.search, 1)
        self.app_filter = ComboBox()
        self.app_filter.setMinimumWidth(182)
        self.app_filter.setMaximumWidth(260)
        self.app_filter.setAccessibleName("应用范围筛选")
        self.app_filter.currentIndexChanged.connect(self.render_rules)
        filters.addWidget(self.app_filter)
        self.status_filter = ComboBox()
        self.status_filter.setMinimumWidth(132)
        self.status_filter.setAccessibleName("规则状态筛选")
        self.status_filter.addItems(["全部状态", "已启用", "已停用"])
        self.status_filter.currentIndexChanged.connect(self.render_rules)
        filters.addWidget(self.status_filter)
        self.mapping.addLayout(filters)
        self.rule_host = QVBoxLayout()
        self.mapping.addLayout(self.rule_host)
        hint = text("ⓘ  完全匹配时触发。方向映射点按移动一次，按住持续移动。", "muted")
        hint.setWordWrap(True)
        self.mapping.addWidget(hint)
        self.mapping.addStretch()

    def create_settings(self):
        self.theme = ComboBox()
        self.theme.setMinimumWidth(152)
        self.theme.setAccessibleName("应用主题")
        for title, value in (("跟随系统", "system"), ("浅色", "light"), ("深色", "dark")):
            self.theme.addItem(title, value)
        self.theme.currentIndexChanged.connect(lambda: self.settings(theme=self.theme.currentData()))
        self.row(self.general, "◐", "主题", "选择应用的显示主题。", self.theme)
        self.login = Switch(False, "登录 Windows 后自动运行")
        self.login.clicked.connect(self.login_changed)
        _, self.login_detail = self.row(self.general, "⏻", "启动时运行", "", self.login)
        self.close_tray = Switch(True, "关闭窗口时收起到托盘")
        self.close_tray.clicked.connect(lambda enabled: self.settings(close_to_tray=enabled))
        self.row(self.general, "↓", "关闭窗口时收起到托盘", "保持映射在后台运行。", self.close_tray)
        self.hotkey_button = button("未设置", lambda: self.edit_hotkey("pause_hotkey"))
        self.row(self.general, "⌨", "暂停快捷键", "快速暂停或恢复全部键盘映射。", self.hotkey_button)
        capture_controls = QWidget()
        capture_controls.setObjectName("cardActions")
        capture_actions = QHBoxLayout(capture_controls)
        capture_actions.setContentsMargins(0, 0, 0, 0)
        self.capture_button = button(capture_label(Settings().capture_hotkey),
                                     lambda: self.edit_hotkey("capture_hotkey"))
        capture_actions.addWidget(self.capture_button)
        capture_actions.addWidget(button("开始截图", self.start_capture))
        _, self.capture_detail = self.row(self.general, "▣", "截图快捷键", "", capture_controls)
        self.row(self.general, "⬡", "运行权限", "映射适用于普通权限的桌面应用。",
                 text("普通权限", "scope"))
        self.general.addStretch()

    def create_backup(self):
        self.row(self.backup, "▤", "导出配置", "将键盘映射和设置保存为 JSON 文件。",
                 button("导出配置", self.export_config))
        self.row(self.backup, "↥", "导入配置", "从 JSON 文件合并或替换规则。",
                 button("导入配置", self.import_config))
        self.row(self.backup, "↶", "恢复默认设置", "恢复软件设置，可选择重建默认映射。",
                 button("恢复默认", self.reset_config))
        self.backup.addSpacing(8)
        self.backup.addWidget(text("当前配置", "section"))
        self.backup_rules = QVBoxLayout()
        self.backup.addLayout(self.backup_rules)
        self.backup.addStretch()

    def create_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu(self)
        menu.addAction("打开", lambda: self.open())
        menu.addAction("开始截图", self.start_capture)
        self.tray_toggle = menu.addAction("暂停映射", self.toggle)
        menu.addAction("常规设置", lambda: self.open(1))
        menu.addSeparator()
        menu.addAction("退出", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.open() if reason == QSystemTrayIcon.DoubleClick else None)
        self.tray.show()

    def open(self, page=0):
        self.go(page)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def warning(self, title, message):
        QMessageBox.warning(self, title, message)

    def commit(self, config):
        old = self.config
        previous_bindings = {chord: action for chord, (_, action) in self.hotkeys.entries.items()}
        rules_applied = False
        try:
            settings = config.settings
            if (self.capture_warning and settings.capture_hotkey == old.settings.capture_hotkey
                    and config.rules == old.rules):
                settings = replace(settings, capture_hotkey="")
            desired = shortcut_plan(settings, config.rules)
            if not self.smoke:
                if any(action in ("capture", LEFT_CAPTURE) for action in desired.values()):
                    self.hotkeys.observe_capture(int(self.winId()))
                self.hotkeys.replace(int(self.winId()), desired)
            if config.rules != old.rules:
                self.engine.apply(config.rules)
                rules_applied = True
            save_config(self.path, config)
        except (OSError, ValueError, EngineError) as error:
            try:
                if not self.smoke:
                    self.hotkeys.replace(int(self.winId()), previous_bindings)
                if rules_applied:
                    self.engine.apply(old.rules)
            except (OSError, ValueError, EngineError) as rollback:
                self.engine.error = f"恢复上次配置失败。{rollback}"
            self.warning("无法保存", str(error))
            self.refresh()
            return False
        self.config = config
        if self.hotkeys.has("capture") or not config.settings.capture_hotkey:
            self.capture_warning = ""
        self.refresh()
        return True

    def settings(self, **changes):
        return self.commit(replace(self.config, settings=replace(self.config.settings, **changes)))

    def edit_rule(self, index=None):
        if self.capture_session is not None or QApplication.activeModalWidget() is not None:
            return
        rules = self.config.rules.copy()
        dialog = RuleEditor(self, self.engine, None if index is None else rules[index])
        while True:
            # Release the Windows binding before showing the dialog, including
            # the time before the user clicks Record.
            with self.suspend_recording_input(pause_engine=False):
                accepted = dialog.exec_()
            if not accepted:
                break
            candidate = dialog.rule
            conflict = find_conflict(candidate, rules)
            if conflict is not None and conflict != index:
                alert = QMessageBox(QMessageBox.Warning, "规则冲突",
                                    "同一范围已有相同的原始按键。", parent=self)
                alert.setInformativeText("现有规则   " + self.rule_text(rules[conflict]) +
                                         "\n拟保存规则   " + self.rule_text(candidate))
                alert.addButton("返回编辑", QMessageBox.RejectRole)
                replace_button = alert.addButton("替换规则", QMessageBox.AcceptRole)
                alert.exec_()
                if alert.clickedButton() != replace_button:
                    continue
                rules[conflict] = candidate
                if index is not None:
                    del rules[index]
            elif index is None:
                rules.append(candidate)
            else:
                rules[index] = candidate
            self.commit(replace(self.config, rules=rules))
            break
        self.refresh_status()

    @staticmethod
    def rule_text(rule):
        return " + ".join(map(label, rule.source)) + " → " + " + ".join(map(label, rule.target))

    def change_rule(self, index, enabled=None):
        rules = self.config.rules.copy()
        if enabled is None:
            if QMessageBox.question(self, "删除映射", "删除这条映射？") != QMessageBox.Yes:
                return
            del rules[index]
        else:
            rules[index] = replace(rules[index], enabled=enabled)
        self.commit(replace(self.config, rules=rules))

    def group(self, parent, entries, title=None, editable=True, show_capture=False):
        panel = card()
        grid = QGridLayout(panel)
        grid.setContentsMargins(14, 10, 14, 12)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 4)
        grid.setColumnStretch(2, 4)
        grid.setColumnStretch(3, 3)
        columns = 7 if editable else 5
        start = 0
        if title:
            heading = text(title, "cardTitle")
            heading.setTextFormat(Qt.PlainText)
            heading.setWordWrap(True)
            grid.addWidget(heading, 0, 0, 1, columns)
            start = 1
        headers = ["原始按键", "", "映射为", "生效范围", "启用"]
        for col, title in enumerate(headers):
            grid.addWidget(text(title, "tableHead"), start, col)
        if editable:
            grid.addWidget(text("操作", "tableHead"), start, 5, 1, 2, Qt.AlignHCenter)
        rows = [*entries, (None, None)] if show_capture else entries
        for offset, (index, rule) in enumerate(rows):
            row = start + offset * 2 + 2
            divider = QFrame()
            divider.setObjectName("divider")
            divider.setFixedHeight(1)
            grid.addWidget(divider, row - 1, 0, 1, columns)
            grid.addWidget(text("→", "muted"), row, 1)
            if rule is None:
                shortcut = self.config.settings.capture_hotkey
                shortcut_text = capture_label(shortcut)
                if shortcut_text == shortcut:
                    shortcut_text = shortcut.replace("+", " + ")
                grid.addWidget(text(shortcut_text or "未设置", "keycap"), row, 0, Qt.AlignLeft)
                grid.addWidget(text("截图"), row, 2)
                grid.addWidget(text("所有应用", "scope"), row, 3, Qt.AlignLeft)
                status = "不可用" if self.capture_warning else ("已启用" if shortcut else "未设置")
                grid.addWidget(text(status, "muted"), row, 4)
                edit = button("编辑", lambda: self.edit_hotkey("capture_hotkey"))
                edit.setAccessibleName("编辑截图快捷键")
                edit.setToolTip(f"修改截图快捷键，可恢复默认 {DEFAULT_CAPTURE_HOTKEY}")
                edit.setMinimumWidth(62)
                grid.addWidget(edit, row, 5)
                continue
            grid.addLayout(keycaps(rule.source), row, 0)
            grid.addLayout(keycaps(rule.target), row, 2)
            scope_name = Path(rule.app_path).stem if rule.app_path else "所有应用"
            scope = text("", "scope")
            scope.setTextFormat(Qt.PlainText)
            scope.setText(scope.fontMetrics().elidedText(scope_name, Qt.ElideRight, 103))
            scope.setToolTip(rule.app_path or "所有应用")
            grid.addWidget(scope, row, 3, Qt.AlignLeft)
            if editable:
                switch = Switch(rule.enabled, "启用此规则")
                switch.clicked.connect(lambda value, idx=index: self.change_rule(idx, value))
                grid.addWidget(switch, row, 4, Qt.AlignCenter)
                edit = button("编辑", lambda _, idx=index: self.edit_rule(idx))
                remove = button("删除", lambda _, idx=index: self.change_rule(idx))
                remove.setProperty("danger", True)
                for col, control in ((5, edit), (6, remove)):
                    control.setMinimumWidth(62)
                    grid.addWidget(control, row, col)
            else:
                grid.addWidget(text("已启用" if rule.enabled else "已停用", "muted"), row, 4)
        parent.addWidget(panel)

    @staticmethod
    def clear_layout(layout):
        while layout.count():
            widget = layout.takeAt(0).widget()
            if widget:
                widget.hide()
                widget.deleteLater()

    def render_rules(self):
        self.clear_layout(self.rule_host)
        query = self.search.text().strip().casefold()
        selected = self.app_filter.currentData()
        state = self.status_filter.currentIndex()
        groups = {}
        for index, rule in enumerate(self.config.rules):
            if selected == "*" and rule.app_path is not None:
                continue
            if selected not in (None, "*") and rule.app_path not in (None, selected):
                continue
            if state and rule.enabled != (state == 1):
                continue
            if query and query not in (self.rule_text(rule) + " " + (rule.app_path or "所有应用")).casefold():
                continue
            groups.setdefault(rule.app_path, []).append((index, rule))
        shortcut = self.config.settings.capture_hotkey
        capture_enabled = bool(shortcut and not self.capture_warning)
        capture_search = f"{shortcut} {shortcut.replace('+', ' + ')} {capture_label(shortcut)} 截图 所有应用".casefold()
        show_capture = (not state or capture_enabled == (state == 1)) and query in capture_search
        if show_capture:
            groups.setdefault(None, [])
        for path in sorted(groups, key=lambda path: (bool(path), path or "")):
            heading = f"{Path(path).stem} 的规则" if path else ("全局规则" if len(groups) > 1 else None)
            self.group(self.rule_host, groups[path], heading, show_capture=show_capture and path is None)
        if not groups:
            self.rule_host.addWidget(text("没有符合条件的映射。", "muted"))
        rules = self.config.rules
        self.count.setText(f"{len(rules)} 条映射  ·  {sum(rule.enabled for rule in rules)} 条已启用")

    def refresh(self):
        self.refresh_status()
        old = self.app_filter.currentData()
        self.app_filter.blockSignals(True)
        self.app_filter.clear()
        self.app_filter.addItem("全部范围", None)
        self.app_filter.addItem("所有应用（全局）", "*")
        for path in sorted({rule.app_path for rule in self.config.rules if rule.app_path}):
            self.app_filter.addItem(Path(path).stem, path)
            self.app_filter.setItemData(self.app_filter.count() - 1, path, Qt.ToolTipRole)
        self.app_filter.setCurrentIndex(max(0, self.app_filter.findData(old)))
        self.app_filter.blockSignals(False)
        self.render_rules()
        self.clear_layout(self.backup_rules)
        if self.config.rules:
            self.group(self.backup_rules, list(enumerate(self.config.rules)), editable=False)
        else:
            self.backup_rules.addWidget(text("暂无映射规则。", "muted"))
        settings = self.config.settings
        self.theme.blockSignals(True)
        self.theme.setCurrentIndex(self.theme.findData(settings.theme))
        self.theme.blockSignals(False)
        self.close_tray.setChecked(settings.close_to_tray)
        try:
            registered = login_registered()
        except OSError:
            registered = False
        self.login.setChecked(registered)
        self.login_detail.setText("登录 Windows 后自动启动 Keyboard Manager。" if registered or not settings.start_on_login
                                  else "默认偏好为开启。请打开开关并确认，为当前版本注册启动项。")
        self.hotkey_button.setText(settings.pause_hotkey or "未设置")
        self.capture_button.setText(capture_label(settings.capture_hotkey) or "未设置")
        self.capture_detail.setText(self.capture_warning or
            "全局快捷键会占用该按键组合。可以更改或清除。")
        self.apply_theme()

    def refresh_status(self):
        failed = bool(self.engine.error)
        running = self.engine.running or self.smoke
        state = "引擎不可用" if failed else ("已启用" if running else "已暂停")
        self.error_box.setVisible(failed)
        self.error_text.setText(self.engine.error)
        self.master.setChecked(running)
        self.status.setText(f"键盘映射{state}" if not failed else state)
        self.detail.setText("规则保存后立即生效。" if running else "映射目前未生效。")
        self.footer.setText(f"●  {state}  ·  版本 {VERSION}")
        if self.tray:
            self.tray_toggle.setText("暂停映射" if running else "恢复映射")
            self.tray.setToolTip(f"{NAME} · {state}")

    def toggle(self):
        try:
            if self.engine.running:
                self.engine.pause()
            else:
                self.retry()
        except EngineError as error:
            self.engine.error = str(error)
        self.refresh_status()

    def retry(self):
        try:
            if self.engine.active is None or self.engine.error:
                self.engine.paused = False
                self.engine.apply(self.config.rules)
            else:
                self.engine.resume()
        except EngineError as error:
            self.engine.error = str(error)
        self.refresh_status()

    def poll(self):
        if self.recording_hotkey:
            return
        if self.engine.children and not self.engine.running:
            self.engine.stop()
            self.engine.error = "映射引擎意外停止。请重试。"
            self.refresh_status()
        if self.config.settings.theme == "system":
            self.apply_theme()

    def login_changed(self, enabled):
        prompt = "将为当前 Windows 用户添加 Keyboard Manager 启动项。" if enabled else "将删除本用户的 Keyboard Manager 启动项。"
        if QMessageBox.question(self, "更改开机启动", prompt) == QMessageBox.Yes:
            try:
                set_login(enabled)
                self.settings(start_on_login=enabled)
            except OSError as error:
                self.warning("无法更改启动项", str(error))
        self.refresh()

    def nativeEvent(self, event_type, message):
        if sys.platform == "win32" and getattr(self, "hotkeys", None) and self.hotkeys.entries:
            from ctypes.wintypes import MSG
            msg = MSG.from_address(int(message))
            if msg.message in (0x312, CAPTURE_MESSAGE):
                action = self.hotkeys.action(msg.wParam, msg.lParam)
                if action is not None:
                    identifier, chord = msg.wParam, msg.lParam
                    if ((action == "capture") == (msg.message == CAPTURE_MESSAGE)
                            and not self.recording_hotkey and QApplication.activeModalWidget() is None):
                        QTimer.singleShot(0, lambda: self.dispatch_hotkey(identifier, chord))
                    return True, 0
        return False, 0

    def dispatch_hotkey(self, identifier, chord):
        if self.exiting or self.recording_hotkey or QApplication.activeModalWidget() is not None:
            return
        action = self.hotkeys.action(identifier, chord)
        if action == "capture":
            session = self.capture_session
            if session is None:
                self.start_capture()
            # The global Ctrl+S registration also receives the editor's Save As shortcut.
            elif chord == (ord("S") << 16 | 2) and QApplication.activeWindow() in session.windows:
                session.action("save")
        elif action == "pause" and self.capture_session is None:
            self.toggle()

    def start_capture(self):
        if (self.capture_session is not None or self.exiting or self.recording_hotkey
                or QApplication.activeModalWidget() is not None):
            return
        from .capture import CaptureSession
        try:
            session = CaptureSession(self)
            self.capture_session = session
            session.closed.connect(lambda: setattr(self, "capture_session", None))
            session.show()
        except (OSError, RuntimeError, MemoryError) as error:
            if self.capture_session is not None:
                self.capture_session.close()
            self.warning("截图启动失败", str(error))

    def release_capture(self):
        if self.capture_session is not None:
            self.capture_session.close(restore=False)
        if self.hotkeys.entries:
            self.hotkeys.replace(int(self.winId()), {})
        self.hotkeys.stop_observing()

    @contextmanager
    def suspend_recording_input(self, *, pause_engine=True):
        previous = {chord: action for chord, (_, action) in self.hotkeys.entries.items()}
        was_recording = self.recording_hotkey
        was_running = pause_engine and self.engine.running
        self.recording_hotkey = True
        try:
            if previous:
                self.hotkeys.replace(int(self.winId()), {})
            if was_running:
                EngineTransition(self.engine.pause).complete()
            yield
        finally:
            if was_running and not self.exiting:
                try:
                    EngineTransition(self.engine.resume).complete()
                except (OSError, RuntimeError) as error:
                    self.warning("引擎未恢复", str(error))
            try:
                if previous and not self.exiting:
                    self.hotkeys.replace(int(self.winId()), previous)
            except OSError as error:
                self.capture_warning = str(error)
                self.refresh()
            finally:
                self.recording_hotkey = was_recording
                self.refresh_status()

    def edit_hotkey(self, field):
        dialog = QDialog(self)
        dialog.setWindowTitle("截图快捷键" if field == "capture_hotkey" else "暂停快捷键")
        layout = dialog_layout(dialog)
        hint = "请按下新的快捷键组合，按 Esc 取消。"
        if field == "capture_hotkey":
            hint += f" 默认快捷键为 {DEFAULT_CAPTURE_HOTKEY}。"
        layout.addWidget(text(hint))
        edit = HotkeyEdit(QKeySequence.fromString(getattr(self.config.settings, field)))
        layout.addWidget(edit)
        edit.setFocus(Qt.OtherFocusReason)
        row = buttons(dialog, "保存")
        row.addButton(button("清除", edit.clear), row.ResetRole)
        if field == "capture_hotkey":
            row.addButton(button("恢复默认", lambda: edit.setKeySequence(
                QKeySequence.fromString(Settings().capture_hotkey))), row.ResetRole)
        layout.addWidget(row)
        try:
            with self.suspend_recording_input():
                accepted = dialog.exec_()
        except (OSError, RuntimeError) as error:
            self.warning("无法录制", str(error))
            return
        if accepted:
            value = edit.keySequence().toString(QKeySequence.PortableText)
            warning = self.capture_warning
            if field == "capture_hotkey":
                self.capture_warning = ""
            if not self.settings(**{field: value}) and field == "capture_hotkey":
                self.capture_warning = warning
                self.refresh()

    def export_config(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出配置", "Keyboard Manager.json", "JSON (*.json)")
        if path:
            try:
                save_config(Path(path), self.config)
            except OSError as error:
                self.warning("导出失败", str(error))

    def import_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入配置", "", "JSON (*.json)")
        if not path:
            return
        try:
            incoming = load_config(Path(path), first_run=False)
        except (OSError, ValueError) as error:
            self.warning("导入失败", str(error))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("导入配置")
        layout = dialog_layout(dialog)
        layout.addWidget(text(f"文件包含 {len(incoming.rules)} 条规则。请选择导入方式。"))
        merge = QRadioButton("合并规则")
        merge.setChecked(True)
        layout.addWidget(merge)
        replace_all = QRadioButton("替换全部规则")
        layout.addWidget(replace_all)
        include = QCheckBox("同时导入软件设置")
        layout.addWidget(include)
        layout.addWidget(buttons(dialog, "导入"))
        if not dialog.exec_():
            return
        conflicts = [rule for rule in incoming.rules if find_conflict(rule, self.config.rules) is not None]
        if merge.isChecked() and conflicts and QMessageBox.question(
            self, "替换冲突规则", f"有 {len(conflicts)} 条冲突。是否用导入的规则替换它们？"
        ) != QMessageBox.Yes:
            return
        self.commit(merge_config(self.config, incoming, replace_all.isChecked(), include.isChecked()))

    def reset_config(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("恢复默认设置")
        layout = dialog_layout(dialog)
        layout.addWidget(text("恢复主题、托盘选项和暂停快捷键。"))
        reset = QCheckBox("清除现有映射并重建四条默认规则")
        layout.addWidget(reset)
        layout.addWidget(buttons(dialog, "恢复"))
        if dialog.exec_():
            self.commit(Config(default_rules() if reset.isChecked() else self.config.rules, Settings()))

    def closeEvent(self, event):
        if not self.exiting and self.tray and self.config.settings.close_to_tray:
            self.hide()
            event.ignore()
        else:
            self.quit()
            event.accept()

    def quit(self):
        from PyQt5.QtWidgets import QApplication
        self.exiting = True
        self.release_capture()
        self.engine.stop()
        if self.tray:
            self.tray.hide()
        QApplication.quit()

    def apply_theme(self):
        from .style import stylesheet, system_dark
        theme = self.config.settings.theme
        dark = theme == "dark" or (theme == "system" and system_dark())
        if getattr(self, "dark", None) != dark:
            self.dark = dark
            self.setStyleSheet(stylesheet(dark))
            for index, control in enumerate(self.navigation):
                color = "#d9e1eb" if dark else "#414d5c"
                control.setIcon(navigation_icon(index, color, self.devicePixelRatioF()))

