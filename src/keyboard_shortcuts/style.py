import winreg

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt5.QtWidgets import (
    QComboBox, QDialog, QGraphicsDropShadowEffect, QListView, QStyle,
    QStyledItemDelegate, QStyleOptionComboBox, QStylePainter, QVBoxLayout,
)


class ComboItemDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setWidth(0)  # Use the popup viewport width so long names elide within the row.
        return size


class ComboBox(QComboBox):
    """Styled Qt combo box with its standard model, popup, and keyboard handling."""

    def __init__(self):
        super().__init__()
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(1)
        self.setMaxVisibleItems(8)
        self.setFixedHeight(40)
        self.setCursor(Qt.PointingHandCursor)
        view = QListView()
        view.setMouseTracking(True)
        view.setTextElideMode(Qt.ElideRight)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setView(view)
        view.setItemDelegate(ComboItemDelegate(view))
        popup = view.window()
        popup.setObjectName("comboPopup")
        popup.setAttribute(Qt.WA_TranslucentBackground)
        popup.setWindowFlag(Qt.FramelessWindowHint)
        popup.setWindowFlag(Qt.NoDropShadowWindowHint)
        # Qt includes the popup frame's margins in its available-screen size calculation.
        popup.setContentsMargins(7, 5, 7, 10)
        shadow = QGraphicsDropShadowEffect(view)
        shadow.setBlurRadius(13)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 54))
        view.setGraphicsEffect(shadow)

    def showPopup(self):
        view = self.view()
        popup = view.window()
        margins = popup.contentsMargins()
        popup.setMinimumWidth(self.width())
        view.setMinimumWidth(self.width() - margins.left() - margins.right())
        super().showPopup()
        self.update()

    def hidePopup(self):
        super().hidePopup()
        self.update()

    def paintEvent(self, event):
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        style = self.style()
        field = style.subControlRect(QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxEditField, self)
        option.currentText = option.fontMetrics.elidedText(option.currentText, Qt.ElideRight, field.width())
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.CC_ComboBox, option)
        painter.drawControl(QStyle.CE_ComboBoxLabel, option)
        painter.setRenderHint(QPainter.Antialiasing)
        color = self.palette().buttonText().color()
        color.setAlpha(188 if self.isEnabled() else 85)
        painter.setPen(QPen(color, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        x, y = self.width() - 18, self.height() / 2
        slope = -1 if self.view().isVisible() else 1
        painter.drawPolyline(QPolygonF([
            QPointF(x - 4, y - 2 * slope), QPointF(x, y + 2 * slope), QPointF(x + 4, y - 2 * slope),
        ]))


def navigation_icon(index, color, scale=1.0):
    size = round(20 * scale)
    image = QPixmap(size, size)
    image.setDevicePixelRatio(scale)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor(color), 1.45, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    if index == 0:
        painter.drawRoundedRect(2, 5, 16, 11, 2, 2)
        for x in (5, 8, 11, 14):
            painter.drawPoint(x, 8)
            painter.drawPoint(x, 10)
        painter.drawLine(7, 13, 13, 13)
    elif index == 1:
        for y, x in ((5, 7), (10, 13), (15, 8)):
            painter.drawLine(2, y, x - 2, y)
            painter.drawLine(x + 2, y, 18, y)
            painter.drawEllipse(x - 2, y - 2, 4, 4)
    else:
        path = QPainterPath(QPointF(4, 7))
        path.arcTo(3, 3, 14, 14, 156, -302)
        painter.drawPath(path)
        painter.drawPolyline(QPolygonF([QPointF(3, 3), QPointF(3, 8), QPointF(8, 8)]))
        painter.drawPolyline(QPolygonF([QPointF(10, 6), QPointF(10, 10), QPointF(13, 12)]))
    painter.end()
    return QIcon(image)


def dialog_layout(dialog: QDialog):
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(24, 20, 24, 20)
    layout.setSpacing(12)
    return layout


def system_dark():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def stylesheet(dark):
    if dark:
        bg, side, panel, text, muted, line, hover, cap = (
            "#1c1d20", "#222326", "#27282c", "#f2f2f4", "#b7bbc3", "#3d4047", "#343840", "#303239")
        badge, badge_text, selected = "#20374c", "#90caff", "#303c4b"
        error, error_text = "#472727", "#ffb4ab"
        control_hover, pressed, focus = "#30333a", "#373e48", "#78b9ff"
        disabled, disabled_text, danger_hover = "#292a2e", "#8e939d", "#3b292d"
    else:
        bg, side, panel, text, muted, line, hover, cap = (
            "#f8f8f9", "#f0f0f2", "#ffffff", "#171a20", "#535b66", "#dcdde1", "#e8edf4", "#f3f4f6")
        badge, badge_text, selected = "#e1effb", "#005eb2", "#e0e7ef"
        error, error_text = "#fff0ef", "#9b1919"
        control_hover, pressed, focus = "#f4f7fb", "#e9f1fa", "#327fca"
        disabled, disabled_text, danger_hover = "#f1f2f4", "#737986", "#fdf1f1"
    return f"""
    QWidget {{ color: {text}; background: {bg}; font-size: 14px; }}
    QLabel, QCheckBox, QRadioButton, QWidget#cardActions {{ background: transparent; }}
    QDialog {{ background: {bg}; }}
    QFrame#sidebar {{ background: {side}; border-right: 1px solid {line}; }}
    QLabel#brand {{ font-size: 15px; font-weight: 650; }}
    QLabel#headline {{ font-size: 34px; font-weight: 750; }}
    QLabel#subtitle {{ color: {muted}; font-size: 15px; }}
    QLabel#section {{ font-size: 21px; font-weight: 700; }}
    QLabel#cardTitle {{ font-size: 16px; font-weight: 650; }}
    QLabel#muted, QLabel#tableHead {{ color: {muted}; }}
    QLabel#tableHead {{ font-size: 13px; font-weight: 600; padding: 5px 0; }}
    QLabel#badge {{ background: {badge}; color: {badge_text}; border-radius: 8px; font-size: 21px; }}
    QFrame#card {{ background: {panel}; border: 1px solid {line}; border-radius: 9px; }}
    QFrame#error {{ background: {error}; border: 1px solid {line}; border-radius: 8px; }}
    QFrame#error QLabel {{ color: {error_text}; font-weight: bold; }}
    QPushButton, QComboBox, QLineEdit, QListWidget, QKeySequenceEdit, QPlainTextEdit, QSpinBox, QLabel#capture {{
        background: {panel}; border: 1px solid {line}; border-radius: 7px; padding: 7px 12px;
        min-height: 24px;
    }}
    QPushButton {{ min-height: 22px; }}
    QComboBox {{ padding-right: 0; combobox-popup: 0; }}
    QComboBox::drop-down {{
        subcontrol-origin: border; subcontrol-position: right center; width: 34px;
        background: transparent; border: none;
    }}
    QComboBox::down-arrow {{ image: none; width: 0px; height: 0px; }}
    QFrame#comboPopup {{ background: transparent; border: none; }}
    QComboBox QListView {{
        color: {text}; background: {panel}; border: 1px solid {line}; border-radius: 8px;
        padding: 4px; outline: none; selection-background-color: {selected}; selection-color: {text};
    }}
    QComboBox QListView::item, QListWidget::item {{
        min-height: 32px; padding: 1px 9px; border: 1px solid transparent; border-radius: 5px;
    }}
    QComboBox QListView::item:hover, QListWidget::item:hover {{ background: {control_hover}; }}
    QComboBox QListView::item:selected, QListWidget::item:selected {{ color: {text}; background: {selected}; }}
    QPushButton:hover, QLineEdit:hover, QComboBox:hover, QKeySequenceEdit:hover {{
        background: {control_hover}; border-color: {muted};
    }}
    QPushButton:pressed, QComboBox:on {{ background: {pressed}; }}
    QPushButton:focus, QLineEdit:focus, QComboBox:focus, QComboBox:on, QListWidget:focus,
    QPlainTextEdit:focus, QSpinBox:focus, QKeySequenceEdit:focus {{ border-color: {focus}; }}
    QKeySequenceEdit QLineEdit {{ background: transparent; border: 0; padding: 0; min-height: 0; }}
    QSpinBox {{ padding-right: 30px; }}
    QSpinBox::up-button, QSpinBox::down-button {{
        subcontrol-origin: padding; width: 25px; border: 0; border-radius: 5px; background: transparent;
    }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {control_hover}; }}
    QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {{ background: {pressed}; }}
    QPushButton[primary="true"] {{ background: #0067c0; color: white; border-color: #0067c0; font-weight: 650; }}
    QPushButton[primary="true"]:hover {{ background: #075ca4; }}
    QPushButton[primary="true"]:pressed {{ background: #004f94; }}
    QPushButton[primary="true"]:focus {{ border-color: #78b9ff; }}
    QPushButton[danger="true"] {{ color: {error_text}; }}
    QPushButton[danger="true"]:hover, QPushButton[danger="true"]:pressed {{ background: {danger_hover}; }}
    QPushButton:disabled, QPushButton[primary="true"]:disabled, QPushButton[danger="true"]:disabled,
    QComboBox:disabled, QLineEdit:disabled {{ color: {disabled_text}; background: {disabled}; border-color: {line}; }}
    QPushButton#navigation {{ text-align: left; border: 1px solid transparent; border-left: 3px solid transparent;
       background: transparent; padding: 8px 11px; }}
    QPushButton#navigation:hover {{ background: {hover}; }}
    QPushButton#navigation:checked {{ background: {selected}; border-left-color: #0067c0; font-weight: 650; }}
    QPushButton#navigation:focus {{ border-top-color: {focus}; border-right-color: {focus}; border-bottom-color: {focus}; }}
    QLabel#keycap {{ background: {cap}; border: 1px solid {line}; border-radius: 5px;
       padding: 4px 9px; font-weight: 650; }}
    QLabel#scope {{ background: {cap}; border-radius: 8px; padding: 3px 8px; color: {muted}; }}
    QFrame#divider {{ background: {line}; border: none; }}
    QCheckBox, QRadioButton {{ spacing: 8px; min-height: 28px; }}
    QScrollBar:vertical {{ width: 12px; background: transparent; margin: 0; }}
    QScrollBar:horizontal {{ height: 12px; background: transparent; margin: 0; }}
    QScrollBar::handle {{ background: {line}; border: 3px solid transparent; border-radius: 5px; }}
    QScrollBar::handle:vertical {{ min-height: 28px; }}
    QScrollBar::handle:horizontal {{ min-width: 28px; }}
    QScrollBar::handle:hover {{ background: {muted}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QMenu {{ background: {panel}; border: 1px solid {line}; padding: 4px; }}
    QMenu::item {{ padding: 6px 22px 6px 9px; }}
    QMenu::item:selected {{ background: {hover}; }}
    """

