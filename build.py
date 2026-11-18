#!/usr/bin/env python3
"""Packs the add-on into dist/ask_about_card.ankiaddon.

That file is what people install: in Anki, Tools → Add-ons → Install from file… and choose it.

Run:  python3 build.py
"""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "addon"
TARGET = ROOT / "dist" / "ask_about_card.ankiaddon"
SKIP_FOLDERS = {"__pycache__"}
SKIP_FILES = {"meta.json", ".DS_Store"}        # meta.json holds a user's own settings
SKIP_ENDINGS = {".pyc", ".log"}


def files() -> list[Path]:
    found = []
    for p in sorted(SOURCE.rglob("*")):
        inside = p.relative_to(SOURCE)
        if (p.is_file() and not set(inside.parts[:-1]) & SKIP_FOLDERS and p.name not in SKIP_FILES
                and p.suffix not in SKIP_ENDINGS):
            found.append(p)
    return found


def main() -> None:
    TARGET.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(TARGET, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files():
            # a fixed date and plain permissions: the same source always gives the same file
            info = zipfile.ZipInfo(p.relative_to(SOURCE).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, p.read_bytes())
    print(f"Built {TARGET.relative_to(ROOT)} ({TARGET.stat().st_size} bytes, {len(files())} files)")


if __name__ == "__main__":
    main()
