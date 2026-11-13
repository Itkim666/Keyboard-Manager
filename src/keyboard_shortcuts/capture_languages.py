"""Bundled offline text recognition and translation for screenshot selections."""
from functools import lru_cache
import re

from .capture_manga import apply_translations, group_lines
from .capture_text import OCR_LOCK, models_dir, recognizer, translate_text


OCR_MODELS = {
    "PP-OCRv6_rec_small": None,
    "arabic_PP-OCRv5_rec_mobile": r"[\u0600-\u06ff]",
    "cyrillic_PP-OCRv5_rec_mobile": r"[\u0400-\u052f]",
    "devanagari_PP-OCRv5_rec_mobile": r"[\u0900-\u097f]",
    "el_PP-OCRv5_rec_mobile": r"[\u0370-\u03ff\u1f00-\u1fff]",
    "korean_PP-OCRv5_rec_mobile": r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]",
    "th_PP-OCRv5_rec_mobile": r"[\u0e00-\u0e7f]",
}

LANGUAGE_CODES = dict(code.split(":") for code in (
    "af:afr_Latn ar:arb_Arab az:azj_Latn be:bel_Cyrl bg:bul_Cyrl bs:bos_Latn ca:cat_Latn "
    "cs:ces_Latn cy:cym_Latn da:dan_Latn de:deu_Latn el:ell_Grek en:eng_Latn es:spa_Latn "
    "et:est_Latn eu:eus_Latn fa:pes_Arab fi:fin_Latn fr:fra_Latn ga:gle_Latn gl:glg_Latn "
    "hi:hin_Deva hr:hrv_Latn hu:hun_Latn id:ind_Latn is:isl_Latn it:ita_Latn ja:jpn_Jpan "
    "kk:kaz_Cyrl ko:kor_Hang la:lat_Latn lt:lit_Latn lv:lvs_Latn mk:mkd_Cyrl mn:khk_Cyrl "
    "mr:mar_Deva ms:zsm_Latn ne:npi_Deva nl:nld_Latn no:nob_Latn pl:pol_Latn ps:pbt_Arab "
    "pt:por_Latn ro:ron_Latn ru:rus_Cyrl sk:slk_Latn sl:slv_Latn sq:als_Latn sr:srp_Cyrl "
    "sv:swe_Latn sw:swh_Latn th:tha_Thai tl:tgl_Latn tr:tur_Latn uk:ukr_Cyrl ur:urd_Arab "
    "uz:uzn_Latn vi:vie_Latn zh:zho_Hans"
).split())


@lru_cache(maxsize=1)
def multilingual_recognizers():
    from rapidocr_onnxruntime.ch_ppocr_rec import TextRecognizer

    root = models_dir() / "multilingual-ocr"
    return [
        (TextRecognizer({
            "model_path": str(root / f"{name}.onnx"), "rec_img_shape": [3, 48, 320],
            "rec_batch_num": 6, "intra_op_num_threads": 2, "inter_op_num_threads": 1,
        }), re.compile(script) if script else None)
        for name, script in OCR_MODELS.items()
    ]


def recognize_multilingual(rgb):
    """Detect and crop each line once, then compare candidates from the script models."""
    ocr = recognizer()
    bgr = rgb[:, :, ::-1].copy()
    with OCR_LOCK:
        image, ratio_h, ratio_w = ocr.preprocess(bgr)
        image, transform = ocr.maybe_add_letterbox(image, {"preprocess": {
            "ratio_h": ratio_h, "ratio_w": ratio_w,
        }})
        boxes, _ = ocr.auto_text_det(image)
        if boxes is None or not len(boxes):
            return []
        # Small closing punctuation can lie just beyond the detector's text box.
        bounds = [(box[:, 0].min(), box[:, 1].min(), box[:, 0].max(), box[:, 1].max()) for box in boxes]
        for index, (_, top, right, bottom) in enumerate(bounds):
            next_left = min((left for left, y1, _, y2 in bounds if left > right and y1 < bottom and y2 > top),
                            default=image.shape[1] - 1)
            pad = max(0, min(round((bottom - top) * .45), next_left - right - 1))
            boxes[index][1:3, 0] += pad
        crops, _, _ = ocr.text_cls(ocr.get_crop_img_list(image, boxes))
        candidates = [(engine(crops)[0], script) for engine, script in multilingual_recognizers()]
        ambiguous = [index for index, (text, score) in enumerate(candidates[0][0])
                     if len(text.strip()) == 1 and text.strip().isascii() and .5 <= score < .80]
        verified = {}
        if ambiguous:
            original, _ = ocr.text_rec([crops[index] for index in ambiguous])
            verified = dict(zip(ambiguous, original))
        boxes = ocr._get_origin_points(boxes, transform, *bgr.shape[:2])

    rows = []
    for index, box in enumerate(boxes):
        best_text, best_score = candidates[0][0][index]
        for results, script in candidates[1:]:
            text, score = results[index]
            letters = [char for char in text if char.isalpha()]
            if (letters and sum(bool(script.fullmatch(char)) for char in letters) > len(letters) / 2
                    and score > best_score + .035):
                if script.pattern == OCR_MODELS["arabic_PP-OCRv5_rec_mobile"]:
                    # The Arabic recognizer emits visual order. Keep Latin runs in order.
                    text = "".join(reversed(re.findall(r"[a-zA-Z0-9 :*./%+-]+|.", text)))
                best_text, best_score = text, score
        if index in verified and (best_text, best_score) == candidates[0][0][index]:
            # Icons can be misread as a single ASCII character. Check low-confidence matches.
            check, confidence = verified[index]
            if check.strip() != best_text.strip() or confidence < .5:
                continue
        if best_text.strip() and best_score >= .5:
            rows.append((box, re.sub(r"\s*·\s*", " · ", best_text).strip(), best_score))
    return rows


@lru_cache(maxsize=1)
def multilingual_translator():
    from ctranslate2 import Translator
    from sentencepiece import SentencePieceProcessor

    root = models_dir() / "nllb"
    tokenizer = SentencePieceProcessor(model_proto=(root / "sentencepiece.bpe.model").read_bytes())
    files = {name: (root / name).read_bytes()
             for name in ("model.bin", "config.json", "shared_vocabulary.json")}
    return tokenizer, Translator("nllb", files=files, device="cpu", compute_type="int8", intra_threads=2)


def translate_multilingual(language, lines):
    tokenizer, model = multilingual_translator()
    source = [[LANGUAGE_CODES[language], *tokenizer.encode(text, out_type=str), "</s>"] for text in lines]
    if any(len(tokens) > 512 for tokens in source):
        raise ValueError("单行文字过长，请缩小截图选区后再试。")
    target = [["zho_Hans"] for _ in source]
    result = model.translate_batch(source, target_prefix=target, beam_size=4,
                                   max_batch_size=8, max_input_length=512, max_decoding_length=512)
    return [tokenizer.decode(row.hypotheses[0][1:]).strip() for row in result]


def detect_language(text):
    from py3langid import rank

    rankings = rank(text)
    language, score = rankings[0]
    code = LANGUAGE_CODES.get(language, "")
    if (code.endswith("_Latn") and score - rankings[1][1] < 4
            and len(re.findall(r"[^\W\d_]+", text)) >= 3):
        # Short Latin-script sentences can have almost identical first-pass scores.
        from langdetect import DetectorFactory, LangDetectException, detect_langs

        DetectorFactory.seed = 0
        try:
            result = detect_langs(text)[0]
        except LangDetectException:
            return language
        if result.prob >= .90 and LANGUAGE_CODES.get(result.lang, "").endswith("_Latn"):
            return result.lang
    return language


def translate_recognized_lines(lines):
    rows, pending = group_lines(lines, detect_language)
    for language, group in pending.items():
        if language not in LANGUAGE_CODES:
            raise ValueError(f"识别到了当前翻译模型未支持的语言（{language}）。")
        source = [part.strip() for _, _, part in group]
        if language == "en":
            result = translate_text("\n".join(source), "en_zh")[1].split("\n")
        else:
            result = translate_multilingual(language, source)
        apply_translations(group, result)
    return [(box, original, "".join(pieces)) for box, original, pieces in rows]
