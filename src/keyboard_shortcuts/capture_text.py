"""Local OCR and translation. All models are loaded from bundled files."""
from functools import lru_cache
from pathlib import Path
import re
import sys
from threading import Lock

from PyQt5.QtGui import QImage

OCR_LOCK = Lock()


def models_dir():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "capture-models"
    return Path(__file__).resolve().parents[2] / ".build-tools" / "capture-models"


@lru_cache(maxsize=1)
def recognizer():
    import rapidocr_onnxruntime as ocr

    folder = Path(ocr.__file__).resolve().parent / "models"
    missing = [name for name in ("ch_PP-OCRv4_det_infer.onnx", "ch_PP-OCRv4_rec_infer.onnx",
                                 "ch_ppocr_mobile_v2.0_cls_infer.onnx") if not (folder / name).is_file()]
    if missing:
        raise FileNotFoundError("缺少随软件提供的 OCR 模型：" + ", ".join(missing))
    return ocr.RapidOCR(
        det_model_path=str(folder / "ch_PP-OCRv4_det_infer.onnx"),
        rec_model_path=str(folder / "ch_PP-OCRv4_rec_infer.onnx"),
        cls_model_path=str(folder / "ch_ppocr_mobile_v2.0_cls_infer.onnx"),
        intra_op_num_threads=2, inter_op_num_threads=1,
    )


def format_lines(results):
    boxes = []
    for corners, text, _score in results:
        x, y = zip(*corners)
        if text.strip():
            boxes.append((min(x), min(y), max(y), text.strip()))
    rows = []
    for x, top, bottom, text in sorted(boxes, key=lambda item: (item[1], item[0])):
        row = next((row for row in reversed(rows)
                    if min(row[1], bottom) - max(row[0], top) >= .5 * min(row[1] - row[0], bottom - top)), None)
        if row is None:
            rows.append((top, bottom, [(x, text)]))
        else:
            row[2].append((x, text))
    lines = []
    previous = None
    for top, bottom, parts in rows:
        if previous is not None and top - previous[1] > .9 * max(bottom - top, previous[1] - previous[0]):
            lines.append("")
        lines.append(" ".join(text for _, text in sorted(parts)))
        previous = top, bottom
    return "\n".join(lines)


def image_pixels(image):
    import numpy as np

    image = image.convertToFormat(QImage.Format_RGB888)
    pointer = image.constBits()
    pointer.setsize(image.sizeInBytes())
    rgb = np.frombuffer(pointer, dtype=np.uint8).reshape(image.height(), image.bytesPerLine())
    return rgb[:, :image.width() * 3].reshape(image.height(), image.width(), 3).copy()


def recognize_regions(rgb):
    with OCR_LOCK:
        result, _ = recognizer()(rgb[:, :, ::-1].copy())
    return result or []


def extract_text(image):
    text = format_lines(recognize_regions(image_pixels(image)))
    if not text:
        raise ValueError("当前选区未检测到可识别文字。")
    return text


def translation_direction(text):
    han = sum("\u3400" <= ch <= "\u9fff" or "\U00020000" <= ch <= "\U000323af" for ch in text)
    latin = len(re.findall("[a-zA-Z]", text))
    if not han and not latin:
        raise ValueError("未检测到可翻译的中文或英文。")
    return "zh_en" if han and han * 3 >= latin else "en_zh"


@lru_cache(maxsize=2)
def translation_model(pair):
    from ctranslate2 import Translator
    from sentencepiece import SentencePieceProcessor

    path = models_dir() / pair
    model = path / "model"
    if not (model / "model.bin").is_file() or not (path / "sentencepiece.model").is_file():
        raise FileNotFoundError(f"本地翻译模型不可用（{pair}）。请检查安装包是否完整。")
    tokenizer = SentencePieceProcessor(model_proto=(path / "sentencepiece.model").read_bytes())
    # The in-memory loader also handles Unicode Windows installation paths.
    files = {item.name: item.read_bytes() for item in model.iterdir() if item.is_file()}
    translator = Translator(pair, device="cpu", compute_type="int8", intra_threads=2, files=files)
    return tokenizer, translator


def translate_text(text, pair=None):
    pair = pair or translation_direction(text)
    tokenizer, translator = translation_model(pair)
    lines = text.split("\n")
    tokens = [tokenizer.encode(line, out_type=str) for line in lines if line.strip()]
    lengths = [len(line) for line in tokens]
    if max(lengths, default=0) > 1000:
        raise ValueError("单行文字过长，请缩小截图选区后再试。")
    translations = translator.translate_batch(tokens, beam_size=4, max_input_length=0,
                                              max_decoding_length=1000, max_batch_size=8)
    decoded = iter(tokenizer.decode(item.hypotheses[0]).replace("▁", " ").strip()
                   for item in translations)
    result = "\n".join(next(decoded) if line.strip() else "" for line in lines)
    if not result.strip():
        raise ValueError("本地模型未返回可用译文。")
    return pair, result

