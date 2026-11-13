from dataclasses import dataclass, replace
from math import hypot

from PyQt5.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPainterPathStroker


def clamp(value, low, high):
    return min(max(value, low), max(low, high))


def handles(region):
    left, top = region.x(), region.y()
    right, bottom = left + region.width(), top + region.height()
    x, y = (left + right) // 2, (top + bottom) // 2
    return dict(zip(("nw", "n", "ne", "e", "se", "s", "sw", "w"), (
        QPoint(left, top), QPoint(x, top), QPoint(right, top), QPoint(right, y),
        QPoint(right, bottom), QPoint(x, bottom), QPoint(left, bottom), QPoint(left, y),
    )))


def resize_region(region, handle, delta, bounds):
    left, top = region.x(), region.y()
    right, bottom = left + region.width(), top + region.height()
    if "w" in handle:
        left = clamp(left + delta.x(), bounds.left(), right - 1)
    if "e" in handle:
        right = clamp(right + delta.x(), left + 1, bounds.right() + 1)
    if "n" in handle:
        top = clamp(top + delta.y(), bounds.top(), bottom - 1)
    if "s" in handle:
        bottom = clamp(bottom + delta.y(), top + 1, bounds.bottom() + 1)
    return QRect(left, top, right - left, bottom - top)


def toolbar_origin(region, screen, width, height, gap):
    inset = min(gap, max(0, (screen.width() - width) // 2))
    x = clamp(region.x() + (region.width() - width) // 2, screen.left() + inset,
              screen.right() - width + 1 - inset)
    below = region.y() + region.height() + gap
    above = region.y() - height - gap
    if below + height <= screen.bottom() + 1:
        y = below
    elif above >= screen.top():
        y = above
    else:
        y = clamp(region.y() + region.height() - height - gap,
                  screen.top() + gap, screen.bottom() - height + 1 - gap)
    return QPoint(x, y)


@dataclass(frozen=True)
class Mark:
    kind: str
    points: tuple[QPoint, ...]
    color: str
    width: int
    text: str = ""
    font_size: int = 24
    erased: QPainterPath | None = None

    def shifted(self, delta):
        erased = self.erased.translated(QPointF(delta)) if self.erased is not None else None
        return replace(self, points=tuple(p + delta for p in self.points), erased=erased)

    def path(self):
        start, end = QPointF(self.points[0]), QPointF(self.points[-1])
        path = QPainterPath()
        if self.kind == "rectangle":
            path.addRect(QRectF(start, end).normalized())
        elif self.kind == "ellipse":
            path.addEllipse(QRectF(start, end).normalized())
        elif self.kind == "text":
            font = QFont("Microsoft YaHei UI")
            font.setPixelSize(self.font_size)
            for line, value in enumerate(self.text.splitlines(), 1):
                path.addText(start + QPointF(0, self.font_size * 1.3 * line), font, value)
        else:
            path.moveTo(start)
            for point in self.points[1:]:
                path.lineTo(QPointF(point))
            if self.kind == "arrow":
                vector = end - start
                length = hypot(vector.x(), vector.y())
                if length:
                    unit = vector / length
                    head = min(length * .5, max(12, self.width * 4))
                    base = end - unit * head
                    normal = QPointF(-unit.y(), unit.x()) * (head * .48)
                    path.moveTo(base + normal)
                    path.lineTo(end)
                    path.lineTo(base - normal)
        return path

    def contains(self, point, tolerance=8):
        if self.erased is not None and self.erased.contains(QPointF(point)):
            return False
        path = self.path()
        if self.kind == "text":
            return path.boundingRect().adjusted(-tolerance, -tolerance, tolerance, tolerance).contains(QPointF(point))
        stroker = QPainterPathStroker()
        stroker.setWidth(max(self.width, tolerance * 2))
        return stroker.createStroke(path).contains(QPointF(point))

    def outline(self):
        if self.kind == "text":
            return self.path()
        stroke = QPainterPathStroker()
        stroke.setWidth(self.width)
        stroke.setCapStyle(Qt.RoundCap)
        stroke.setJoinStyle(Qt.RoundJoin)
        return stroke.createStroke(self.path())

    def paint(self, painter):
        outline = self.outline()
        if self.erased is not None:
            outline = outline.subtracted(self.erased)
        painter.fillPath(outline, QColor(self.color))


@dataclass(frozen=True)
class TranslatedSelection:
    origin: QPoint
    image: QImage

    def shifted(self, delta):
        return replace(self, origin=self.origin + delta)

    def paint(self, painter):
        painter.drawImage(self.origin, self.image)


class CaptureDocument:
    def __init__(self, screens):
        self.screens = screens
        self.bounds = QRect()
        for rect, _ in screens:
            self.bounds = self.bounds.united(rect)
        self.region = QRect()
        self.marks = ()
        self.previous = []
        self.following = []

    def state(self):
        return QRect(self.region), self.marks

    def record(self, before):
        if before != self.state():
            self.previous.append(before)
            self.following.clear()

    def undo(self):
        if self.previous:
            self.following.append(self.state())
            self.region, self.marks = self.previous.pop()

    def redo(self):
        if self.following:
            self.previous.append(self.state())
            self.region, self.marks = self.following.pop()

    def add(self, mark):
        before = self.state()
        self.marks += (mark,)
        self.record(before)

    def apply_translation(self, image):
        before = self.state()
        self.marks = (TranslatedSelection(self.region.topLeft(), image),) + tuple(
            mark for mark in self.marks if isinstance(mark, Mark))
        self.record(before)

    def replace(self, index, mark):
        self.marks = self.marks[:index] + (mark,) + self.marks[index + 1:]

    def erase(self, index):
        before = self.state()
        self.marks = self.marks[:index] + self.marks[index + 1:]
        self.record(before)

    def erase_segment(self, start, end, radius):
        path = QPainterPath(QPointF(start))
        if start == end:
            path.addEllipse(QPointF(start), radius, radius)
        else:
            path.lineTo(QPointF(end))
            stroke = QPainterPathStroker()
            stroke.setWidth(radius * 2)
            stroke.setCapStyle(Qt.RoundCap)
            path = stroke.createStroke(path)
        region = QPainterPath()
        region.addRect(QRectF(self.region))
        path = path.intersected(region)
        updated = []
        for mark in self.marks:
            if isinstance(mark, Mark) and mark.outline().intersects(path):
                erased = path if mark.erased is None else mark.erased.united(path)
                mark = replace(mark, erased=erased)
            updated.append(mark)
        self.marks = tuple(updated)

    def hit(self, point, tolerance):
        return next((i for i in reversed(range(len(self.marks)))
                     if isinstance(self.marks[i], Mark) and self.marks[i].contains(point, tolerance)), None)

    def move_region(self, region):
        delta = region.topLeft() - self.region.topLeft()
        self.marks = tuple(mark.shifted(delta) for mark in self.marks)
        self.region = region

    def background(self, painter, area):
        for rect, image in self.screens:
            overlap = rect.intersected(area)
            if not overlap.isEmpty():
                painter.drawImage(overlap, image, overlap.translated(-rect.topLeft()))

    def paint_marks(self, painter, pending=None):
        painter.save()
        painter.setClipRect(self.region, Qt.IntersectClip)
        painter.setRenderHint(QPainter.Antialiasing)
        for mark in self.marks:
            mark.paint(painter)
        if pending is not None:
            pending.paint(painter)
        painter.restore()

    def render(self, marks=True):
        if self.region.isEmpty():
            raise ValueError("请先框选截图区域。")
        image = QImage(self.region.size(), QImage.Format_RGB32)
        if image.isNull():
            raise MemoryError("选区过大，无法创建截图。")
        image.fill(Qt.black)
        painter = QPainter(image)
        painter.translate(-self.region.topLeft())
        self.background(painter, self.region)
        if marks:
            self.paint_marks(painter)
        painter.end()
        return image

