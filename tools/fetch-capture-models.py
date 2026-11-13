"""Prepare the pinned Argos models at build time, never at runtime."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path, PurePosixPath
import shutil
from urllib.request import urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1] / ".build-tools" / "capture-models"
VERSIONS = {"zh_en": "1_9", "en_zh": "1_9"}
SHA256 = {
    "zh_en": "62e7af5a3a48b530e47b7b3e5c78c2de79073ecd815750d2bf3ab35b4a67da2d",
    "en_zh": "433e7c4f034d87fbe2353161e05f18646d7999452f801a4e1f0378522b9850ab",
}


def fetch(pair):
    url = f"https://data.argosopentech.com/argospm/v1/translate-{pair}-{VERSIONS[pair]}.argosmodel"
    ROOT.mkdir(parents=True, exist_ok=True)
    archive = ROOT / f"{pair}.argosmodel"
    if not archive.exists():
        partial = archive.with_suffix(".part")
        with urlopen(url, timeout=90) as source, partial.open("wb") as destination:
            shutil.copyfileobj(source, destination)
        partial.replace(archive)
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != SHA256[pair]:
        raise RuntimeError(f"Argos model checksum mismatch: {archive}")
    with ZipFile(archive) as package:
        for member in package.infolist():
            parts = PurePosixPath(member.filename).parts[1:]
            if member.is_dir() or not parts or any(part in ("..", ".") or "\\" in part or ":" in part for part in parts):
                continue
            if parts[0] not in ("model", "sentencepiece.model", "metadata.json", "LICENSE", "README.md"):
                continue
            target = ROOT.joinpath(pair, *parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with package.open(member) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
    folder = ROOT / pair
    if not (folder / "sentencepiece.model").is_file() or not (folder / "model" / "model.bin").is_file():
        raise RuntimeError(f"Invalid Argos model: {pair}")
    return f"{pair} {digest} {url}"


if __name__ == "__main__":
    with ThreadPoolExecutor(2) as workers:
        sources = "\n".join(workers.map(fetch, VERSIONS))
    (ROOT / "sources.txt").write_text(sources + "\n", encoding="utf-8")
    print(sources)


