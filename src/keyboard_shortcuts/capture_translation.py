"""Produce both the in-place translation image and its readable transcript."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter

from .capture_manga import fit_part, line_parts
from .capture_text import format_lines, image_pixels, models_dir, recognize_regions, translate_text


@dataclass(frozen=True)
class Translation:
    image: QImage
    text: str
    changed: bool


def translate_selection(image, python=None):
    pixels = image_pixels(image)
    if (models_dir() / "nllb" / "model.bin").is_file():
        from .capture_languages import recognize_multilingual, translate_recognized_lines

        regions = translate_recognized_lines(
            (corners, source) for corners, source, _ in recognize_multilingual(pixels))
    elif python:
        regions = recognize_and_translate_with_manga(image, python)
    else:
        regions = [
            (corners, source.strip(), translate_english_parts(source.strip()))
            for corners, source, _ in recognize_regions(pixels) if source.strip()
        ]
    transcript = format_lines((corners, translated, 1.0) for corners, _, translated in regions)
    if not transcript:
        raise ValueError("当前选区未检测到可识别文字。")
    changed = [(corners, translated) for corners, source, translated in regions if source != translated]
    return Translation(render_regions(image, pixels, changed) if changed else image, transcript, bool(changed))


def translate_english_parts(source):
    return "".join(
        fit_part(part, translate_text(part.strip(), "en_zh")[1]) if translatable else part
        for part, translatable in line_parts(source, preserve_han=True)
    )


def render_regions(image, pixels, regions):
    import cv2
    import numpy as np

    mask = np.zeros(pixels.shape[:2], dtype=np.uint8)
    patches = []
    for corners, translated in regions:
        polygon = np.rint(corners).astype(np.int32)
        x, y, width, height = cv2.boundingRect(polygon)
        rect = QRectF(x, y, width, height).intersected(QRectF(0, 0, image.width(), image.height()))
        if not rect.isEmpty():
            cv2.fillConvexPoly(mask, polygon, 255)
            patches.append((rect, translated))
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8))
    restored = cv2.inpaint(pixels, mask, 3, cv2.INPAINT_TELEA)
    height, width, _ = restored.shape
    output = QImage(restored.data, width, height, restored.strides[0], QImage.Format_RGB888).copy()
    painter = QPainter(output)
    painter.setRenderHint(QPainter.TextAntialiasing)
    try:
        for rect, translated in patches:
            font = QFont("Microsoft YaHei UI")
            font.setPixelSize(max(1, round(rect.height())))
            metrics = QFontMetricsF(font)
            font.setPixelSize(max(1, int(font.pixelSize() * min(
                1, rect.width() / max(1, metrics.horizontalAdvance(translated)),
                rect.height() / max(1, metrics.height())))))
            painter.setFont(font)
            bounds = rect.toAlignedRect()
            area = np.s_[bounds.top():bounds.bottom() + 1, bounds.left():bounds.right() + 1]
            original = pixels[area]
            differences = np.abs(original.astype(np.int16) - restored[area]).sum(axis=2)
            strokes = original[differences >= max(24, np.percentile(differences, 90))]
            if strokes.size:
                color = QColor(*np.median(strokes, axis=0).astype(int).tolist())
            else:
                center = bounds.center()
                background = QColor(*restored[center.y(), center.x()].tolist())
                color = QColor("white" if background.lightness() < 128 else "black")
            painter.setPen(color)
            painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextSingleLine, translated)
    finally:
        painter.end()
    return output


def recognize_and_translate_with_manga(image, python):
    executable = Path(python).resolve(strict=True)
    root = os.environ.get("KM_MANGA_TRANSLATOR_ROOT")
    if not root:
        root = next((parent for parent in executable.parents
                     if (parent / "manga_translator" / "__main__.py").is_file()), None)
    with TemporaryDirectory(prefix="km-image-translation-") as folder:
        source, output = (Path(folder) / name for name in ("input.png", "translation.json"))
        if not image.save(str(source)):
            raise OSError("无法保存临时截图。")
        env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONIOENCODING": "utf-8"}
        if root:
            env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(root), env.get("PYTHONPATH"))))
        worker = Path(__file__).with_name("capture_manga.py")
        process = subprocess.run(
            [str(executable), str(worker), str(source), str(output)],
            cwd=root or None, env=env, capture_output=True, timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if process.returncode or not output.is_file():
            detail = process.stderr.decode("utf-8", errors="replace").strip().splitlines()
            raise RuntimeError("多语言引擎运行失败。请检查 Python 环境及离线模型。"
                               + (" " + detail[-1] if detail else ""))
        return json.loads(output.read_text(encoding="utf-8"))
