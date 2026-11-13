"""Line-level recognition and translation in the optional manga-translator environment."""
import asyncio
from collections import defaultdict
import json
from pathlib import Path
import re
import sys


PROTECTED = r"(?<![A-Za-z0-9])(?:[A-Z][a-z]+(?:[A-Z][A-Za-z0-9]*)+|\d+(?:[.,]\d+)*(?:[kKmM%])?)(?![A-Za-z0-9])"
HAN = r"[\u3400-\u9fff\U00020000-\U000323af]+"


def line_parts(source, preserve_han=False):
    protected = f"(?:{PROTECTED}|{HAN})" if preserve_han else PROTECTED
    parts = re.split(f"({protected})", source)
    return [(part, index % 2 == 0 and any(char.isalpha() for char in part))
            for index, part in enumerate(parts)]


def fit_part(original, translated):
    leading = original[:len(original) - len(original.lstrip())]
    trailing = original[len(original.rstrip()):]
    return leading + translated.strip() + trailing


def group_lines(lines, classify):
    rows = []
    pending = defaultdict(list)
    for corners, source in lines:
        language = classify(source)
        parts = line_parts(source, preserve_han=language in ("zh", "en"))
        words = [part.strip() for part, translatable in parts if translatable]
        if language == "zh" and words:
            language = classify(" ".join(words))
        pieces = [part for part, _ in parts]
        for index, (part, translatable) in enumerate(parts):
            if translatable:
                pending[language].append((pieces, index, part))
        rows.append((corners, source, pieces))
    return rows, pending


def apply_translations(group, results):
    if len(results) != len(group) or any(not value.strip() for value in results):
        raise ValueError("本地模型未返回完整译文。")
    for (pieces, index, part), value in zip(group, results):
        pieces[index] = fit_part(part, value)


async def translate_lines(lines, classify, translator, supported):
    rows, pending = group_lines(lines, classify)
    if pending:
        unsupported = pending.keys() - supported.keys()
        if unsupported:
            raise ValueError("不支持识别出的源语言：" + "、".join(sorted(unsupported)))
        await translator.load("auto", "CHS", "cpu")
        for language, group in pending.items():
            results = await translator.translate(supported[language], "CHS", [part.strip() for _, _, part in group])
            apply_translations(group, results)
    return [(corners, source, "".join(pieces)) for corners, source, pieces in rows]


async def main(source, destination):
    import numpy as np
    from PIL import Image
    import py3langid
    from manga_translator.config import Config, Translator
    from manga_translator.detection import dispatch as detect
    from manga_translator.ocr import dispatch as recognize
    from manga_translator.translators import get_translator
    from manga_translator.translators.nllb import ISO_639_1_TO_FLORES_200

    config = Config()
    with Image.open(source) as image:
        pixels = np.array(image.convert("RGB"))
    d = config.detector
    lines, _, _ = await detect(d.detector, pixels, d.detection_size, d.text_threshold,
                               d.box_threshold, d.unclip_ratio, d.det_invert, d.det_gamma_correct,
                               d.det_rotate, d.det_auto_rotate, "cpu", False)
    lines = await recognize(config.ocr.ocr, pixels, lines, config.ocr, "cpu", False)
    translator = get_translator(Translator.nllb)
    language_codes = {model: code for code, model in translator._LANGUAGE_CODE_MAP.items()}
    supported = {iso: language_codes[model] for iso, model in ISO_639_1_TO_FLORES_200.items()
                 if model in language_codes}
    output = await translate_lines(
        [(line.pts.tolist(), line.text.strip()) for line in lines if line.text.strip()],
        lambda text: py3langid.classify(text)[0], translator, supported)
    Path(destination).write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:]))
