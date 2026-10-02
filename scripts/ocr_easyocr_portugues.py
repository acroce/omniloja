#!/usr/bin/env python3
"""OCR por IA com EasyOCR em português, usando somente CPU.

Instalação no Ubuntu:
  python3 -m venv .venv-ocr
  .venv-ocr/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
  .venv-ocr/bin/pip install easyocr pillow

Os modelos são baixados automaticamente somente na primeira execução.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

import easyocr
from PIL import Image, ImageFile


def normalize_image(image_path: Path) -> Path:
    """Repara JPEG truncado em um PNG temporário antes da leitura por IA."""
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    with Image.open(image_path) as source:
        source.load()
        descriptor, target_name = tempfile.mkstemp(suffix=".png", prefix="ocr-easy-")
        os.close(descriptor)
        target = Path(target_name)
        source.convert("RGB").save(target)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR EasyOCR em português.")
    parser.add_argument("image", type=Path)
    args = parser.parse_args()

    normalized = normalize_image(args.image)
    try:
        reader = easyocr.Reader(["pt", "en"], gpu=False, verbose=False)
        print("\n".join(reader.readtext(str(normalized), detail=0, paragraph=False, canvas_size=1280, mag_ratio=1.0)))
    finally:
        normalized.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
