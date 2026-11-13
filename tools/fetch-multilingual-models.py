"""Fetch and verify the pinned model assets used by the offline screenshot translator."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import shutil
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1] / ".build-tools" / "capture-models"
NLLB = "https://huggingface.co/mydubber-org/nllb-200-distilled-600M-ct2-int8/resolve/9e63a771e9ec358ef812d2ea149d97e16d5f8cee/"
OCR = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx/"
NLLB_FILES = {
    "config.json": "72901fbd8abd89fb5cf4a388f26fc681f5c4c58a1e1a88b30b879f107270e7ee",
    "LICENSE": "41003d4a74749c0220e33dd415042164b5a1093ed401f36277234f772d22d3d0",
    "model.bin": "2dd4860e679616ff223f46b7d8262d816996a7f25aea0adc39836131b1ef8558",
    "sentencepiece.bpe.model": "14bb8dfb35c0ffdea7bc01e56cea38b9e3d5efcdcb9c251d6b40538e1aab555a",
    "shared_vocabulary.json": "768aa4170693765cb4c62fc485ea4fd954cd3e5a44bc645d11d83f41f2393776",
}
OCR_FILES = {
    "PP-OCRv6/rec/PP-OCRv6_rec_small.onnx": "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884",
    "PP-OCRv5/rec/arabic_PP-OCRv5_rec_mobile.onnx": "c1192e632d0baa9146ae5b756a0e635e3dc63c1733737ebfd1629e87144e9295",
    "PP-OCRv5/rec/cyrillic_PP-OCRv5_rec_mobile.onnx": "90f761b4bfcce0c8c561c0cb5c887b0971d3ec01c32164bdf7374a35b0982711",
    "PP-OCRv5/rec/devanagari_PP-OCRv5_rec_mobile.onnx": "d6f0a906580e3fa6b324a318718f1f31f268b6ea8ef985f91c2012a37f52c91e",
    "PP-OCRv5/rec/el_PP-OCRv5_rec_mobile.onnx": "b4368bccd557123c702b7549fee6cd1e94b581337d1c9b65310f109131542b7f",
    "PP-OCRv5/rec/korean_PP-OCRv5_rec_mobile.onnx": "cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b",
    "PP-OCRv5/rec/th_PP-OCRv5_rec_mobile.onnx": "de541dd83161c241ff426f7ecfd602a0ba77d686cf3ab9a6c255ea82fd08006e",
}


def fetch(asset):
    path, url, expected = asset
    destination = ROOT / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file():
        with destination.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual == expected:
            return f"{path} {actual} {url}"
    partial = destination.with_name(destination.name + ".download")
    try:
        with urlopen(url, timeout=120) as source, partial.open("wb") as stream:
            shutil.copyfileobj(source, stream)
        with partial.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise RuntimeError(f"Checksum mismatch: {url}")
        partial.replace(destination)
        return f"{path} {actual} {url}"
    finally:
        partial.unlink(missing_ok=True)


if __name__ == "__main__":
    assets = [(f"nllb/{name}", NLLB + name, digest) for name, digest in NLLB_FILES.items()]
    assets += [(f"multilingual-ocr/{Path(name).name}", OCR + name, digest) for name, digest in OCR_FILES.items()]
    with ThreadPoolExecutor(4) as workers:
        sources = list(workers.map(fetch, assets))
    (ROOT / "multilingual-sources.txt").write_text("\n".join(sources) + "\n", encoding="utf-8")
