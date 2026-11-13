import asyncio

from PyQt5.QtCore import QPoint, QRect
from PyQt5.QtGui import QColor, QImage

from keyboard_shortcuts.capture_document import (
    CaptureDocument, Mark, handles, resize_region, toolbar_origin,
)
from keyboard_shortcuts.capture_manga import translate_lines


def test_mixed_desktop_crop_has_only_pixels_and_marks():
    left = QImage(100, 60, QImage.Format_RGB32)
    left.fill(QColor("white"))
    right = QImage(200, 100, QImage.Format_RGB32)
    right.fill(QColor("lightgray"))
    doc = CaptureDocument([(QRect(-100, 0, 100, 60), left), (QRect(0, -20, 200, 100), right)])
    doc.region = QRect(-20, 5, 50, 30)
    doc.add(Mark("line", (QPoint(-15, 10), QPoint(20, 10)), "#ff0000", 4))
    output = doc.render()
    assert (output.width(), output.height()) == (50, 30)
    assert output.pixelColor(3, 12) == QColor("white")
    assert output.pixelColor(40, 12) == QColor("lightgray")
    assert output.pixelColor(10, 5) == QColor("red")
    doc.undo()
    assert doc.render().pixelColor(10, 5) == QColor("white")
    doc.redo()
    assert doc.render().pixelColor(10, 5) == QColor("red")
    doc.move_region(QRect(-15, 10, 50, 30))
    assert doc.render().pixelColor(10, 5) == QColor("red")
    doc.erase(0)
    assert doc.render().pixelColor(10, 5) == QColor("white")


def test_all_handles_change_only_corresponding_edges():
    box = QRect(20, 30, 100, 60)
    bounds = QRect(0, 0, 300, 300)
    expected = {
        "nw": QRect(25, 37, 95, 53), "n": QRect(20, 37, 100, 53),
        "ne": QRect(20, 37, 105, 53), "e": QRect(20, 30, 105, 60),
        "se": QRect(20, 30, 105, 67), "s": QRect(20, 30, 100, 67),
        "sw": QRect(25, 30, 95, 67), "w": QRect(25, 30, 95, 60),
    }
    assert set(handles(box)) == set(expected)
    for handle, rect in expected.items():
        assert resize_region(box, handle, QPoint(5, 7), bounds) == rect


def test_toolbar_stays_on_negative_origin_screen():
    screen = QRect(-1000, 20, 1000, 800)
    pos = toolbar_origin(QRect(-200, 740, 190, 70), screen, 750, 65, 12)
    assert pos == QPoint(-762, 663)


def test_full_screen_toolbar_is_inside_with_handle_clearance():
    screen = QRect(300, -120, 800, 600)
    assert toolbar_origin(screen, screen, 740, 65, 14) == QPoint(330, 401)


def test_multilingual_worker_groups_lines_and_preserves_chinese_names_and_numbers():
    calls = []

    class Translator:
        async def load(self, source, target, device):
            assert (source, target, device) == ("auto", "CHS", "cpu")

        async def translate(self, source, target, parts):
            calls.append((source, target, parts))
            return [{"Microsoft": "微软", "Bonjour": "你好", "世界へようこそ": "欢迎来到世界"}[part]
                    for part in parts]

    regions = [
        ([], "Microsoft PowerToys · 140.9k 星 ·"),
        ([], "FancyZones 文档"),
        ([], "Bonjour"),
        ([], "世界へようこそ"),
    ]
    languages = {
        regions[0][1]: "zh", "Microsoft": "en",
        regions[1][1]: "zh", regions[2][1]: "fr", regions[3][1]: "ja",
    }
    result = asyncio.run(translate_lines(
        regions, languages.__getitem__, Translator(), {"en": "ENG", "fr": "FRA", "ja": "JPN"}))
    assert [row[2] for row in result] == ["微软 PowerToys · 140.9k 星 ·", "FancyZones 文档", "你好", "欢迎来到世界"]
    assert calls == [("ENG", "CHS", ["Microsoft"]), ("FRA", "CHS", ["Bonjour"]),
                     ("JPN", "CHS", ["世界へようこそ"])]

