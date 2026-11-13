from PyQt5.QtCore import QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QCursor, QFont, QIcon, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QFrame, QGridLayout, QToolButton

TOOLS = (
    ("select", "选择"), ("arrow", "箭头"), ("rectangle", "矩形"), ("ellipse", "圆形"),
    ("line", "画笔"), ("text", "文字"), ("erase", "橡皮擦"), None,
    ("undo", "撤销"), ("redo", "重做"), None, ("ocr", "提取文字"), ("translate", "翻译"),
    None, ("copy", "复制"), ("save", "另存为"), None, ("cancel", "取消"), None, ("finish", "完成"),
)
ANNOTATIONS = ("arrow", "rectangle", "ellipse", "line", "text")
CURSOR_HOTSPOTS = {"arrow": (23, 5), "line": (5, 24), "text": (14, 24), "erase": (10, 24)}


def tool_icon(name, *, for_cursor=False):
    def render(color):
        pixmap = QPixmap(56, 56)
        pixmap.setDevicePixelRatio(2)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(28 / 32, 28 / 32)
        painter.setPen(QPen(QColor(color), 1.9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        outline = QPen(Qt.white, 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)

        def line(*points):
            for a, b in zip(points, points[1:]):
                if for_cursor:
                    painter.save()
                    painter.setPen(outline)
                    painter.drawLine(QPointF(*a), QPointF(*b))
                    painter.restore()
            for a, b in zip(points, points[1:]):
                painter.drawLine(QPointF(*a), QPointF(*b))

        def rect(x, y, width, height, radius=0):
            painter.drawRoundedRect(QRectF(x, y, width, height), radius, radius)

        if name == "select":
            line((8, 4), (8, 25), (13, 20), (17, 28), (21, 26), (17, 18), (25, 18), (8, 4))
        elif name == "arrow":
            line((5, 27), (27, 5), (14, 5))
            line((27, 5), (27, 18))
        elif name == "rectangle":
            rect(4, 5, 24, 23)
        elif name == "ellipse":
            painter.drawEllipse(QRectF(4, 4, 24, 24))
        elif name == "line":
            line((6, 23), (23, 6), (26, 5), (28, 8), (27, 10), (10, 27), (5, 28), (6, 23))
        elif name == "text":
            line((6, 10), (6, 5), (26, 5), (26, 10))
            line((16, 5), (16, 28))
            line((11, 28), (21, 28))
        elif name == "erase":
            line((4, 20), (19, 5), (28, 14), (14, 28), (11, 28), (4, 20))
            line((10, 14), (20, 24))
            line((14, 28), (29, 28))
        elif name in ("undo", "redo"):
            if name == "redo":
                painter.translate(32, 0)
                painter.scale(-1, 1)
            line((12, 5), (5, 11), (12, 17))
            line((5, 11), (18, 11))
            painter.drawArc(QRectF(9, 11, 18, 16), -90 * 16, 180 * 16)
            line((18, 27), (7, 27))
        elif name == "ocr":
            for x, y, dx, dy in ((4, 5, 1, 1), (28, 5, -1, 1), (4, 27, 1, -1), (28, 27, -1, -1)):
                line((x + dx * 5, y), (x, y), (x, y + dy * 5))
            line((11, 12), (11, 10), (21, 10), (21, 12))
            line((16, 10), (16, 22))
            line((13, 22), (19, 22))
        elif name == "translate":
            line((4, 8), (20, 8))
            line((12, 4), (12, 8))
            line((17, 8), (14, 14), (10, 18), (5, 21))
            line((8, 11), (11, 16), (16, 20))
            line((16, 28), (22, 14), (28, 28))
            line((18, 23), (26, 23))
        elif name == "copy":
            rect(5, 11, 17, 17, 3)
            line((10, 7), (12, 4), (25, 4), (28, 7), (28, 20), (25, 22))
        elif name == "save":
            rect(4, 4, 24, 24, 3)
            line((9, 4), (9, 12), (22, 12), (22, 4))
            line((9, 27), (9, 19), (23, 19), (23, 27))
            line((18, 20), (18, 24))
        elif name == "cancel":
            line((5, 5), (27, 27))
            line((27, 5), (5, 27))
        elif name == "finish":
            line((3, 16), (12, 25), (29, 7))
        painter.end()
        return pixmap

    color = {"cancel": "#e60012", "finish": "#08a120"}.get(name, "#121212")
    if for_cursor:
        pixmap = render(color)
        # Qt's cursor hotspot is expressed in logical pixels.
        return QCursor(pixmap, *CURSOR_HOTSPOTS[name])
    icon = QIcon()
    icon.addPixmap(render(color))
    icon.addPixmap(render("#838383"), QIcon.Disabled)
    return icon


class CaptureToolbar(QFrame):
    def __init__(self, overlay, dispatch, palette):
        super().__init__(overlay)
        self.setObjectName("captureToolbar")
        self.setStyleSheet("""
            QFrame#captureToolbar { background: #f7f7f7; border: 1px solid #dcdcdc; border-radius: 9px; }
            QFrame#separator { background: #b4b4b4; border: none; }
            QToolButton { background: transparent; border: none; color: #111111; border-radius: 7px; padding: 0; }
            QToolButton:hover { background: #e7edf4; }
            QToolButton:checked { background: #bfdbf5; }
            QToolButton:disabled { color: #707070; }
        """)
        self.row = QGridLayout(self)
        self.row.setContentsMargins(6, 5, 6, 5)
        self.row.setSpacing(1)
        self.buttons = {}
        self.entries = []
        for entry in TOOLS:
            if entry is None:
                separator = QFrame()
                separator.setObjectName("separator")
                separator.setFixedSize(1, 40)
                self.entries.append(separator)
                continue
            key, title = entry
            button = QToolButton()
            button.setFocusPolicy(Qt.NoFocus)
            button.setText(title)
            button.setAccessibleName(title)
            button.setToolTip("橡皮擦 · 拖动擦除，右键调整大小" if key == "erase" else
                              title + (" · 右键设置样式" if key in ANNOTATIONS else ""))
            if key == "select":
                button.setToolTip("选择 · 拖动选区或控制点，右键拖动可重新框选")
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setIcon(tool_icon(key))
            if key == "select":
                button.setCursor(Qt.ArrowCursor)
            button.setCheckable(key in ("select", *ANNOTATIONS, "erase"))
            button.clicked.connect(lambda _, key=key: dispatch(key))
            if key in (*ANNOTATIONS, "erase"):
                button.setContextMenuPolicy(Qt.CustomContextMenu)
                button.customContextMenuRequested.connect(lambda p, b=button, k=key: palette(k, b.mapToGlobal(p)))
            self.entries.append(button)
            self.buttons[key] = button

    def fit(self, available):
        if getattr(self, "available", None) == available:
            return
        self.available = available
        compact = available < 720
        columns = max(1, (available - 16) // 57) if compact else len(self.entries)
        width = max(1, min(72, (available - 44) // len(self.buttons))) if not compact else 56
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(min(15, max(8, width // 3)))
        for key, button in self.buttons.items():
            w = width + 9 if not compact and width >= 53 and key == "ocr" else width
            button.setFixedSize(w, 61 if width >= 45 else 49)
            button.setFont(font)
            size = min(26, max(14, width - 7))
            button.setIconSize(QSize(size, size))
        position = 0
        for entry in self.entries:
            self.row.removeWidget(entry)
            is_separator = isinstance(entry, QFrame)
            entry.setVisible(not compact or not is_separator)
            if not compact or not is_separator:
                self.row.addWidget(entry, position // columns, position % columns, Qt.AlignCenter)
                position += 1
        self.adjustSize()

    def update_state(self, tool, previous, following, busy, tool_cursor):
        if tool_cursor:
            self.setCursor(Qt.IBeamCursor if tool == "text" else Qt.CrossCursor)
        else:
            self.unsetCursor()
        for key, button in self.buttons.items():
            if button.isCheckable():
                button.setChecked(key == tool)
            if key in CURSOR_HOTSPOTS:
                if key == tool:
                    button.setCursor(tool_cursor)
                else:
                    button.unsetCursor()
        self.buttons["undo"].setEnabled(previous)
        self.buttons["redo"].setEnabled(following)
        self.buttons["ocr"].setEnabled(not busy)
        self.buttons["translate"].setEnabled(not busy)

