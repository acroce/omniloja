#!/usr/bin/env python3
"""OCR por IA com PaddleOCR em português.

Instalação no Ubuntu (CPU):
  python3 -m pip install --user paddlepaddle paddleocr pillow

Para GPU, instale antes a variante PaddlePaddle compatível com CUDA:
  https://www.paddlepaddle.org.cn/install/quick

Exemplo:
  python3 scripts/ocr_paddle_portugues.py comprovante.jpeg
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageFile
from paddleocr import PaddleOCR


def normalize_image(image_path: Path) -> Path:
    """Converte JPEG truncado em PNG completo para o leitor baseado em IA."""
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    with Image.open(image_path) as source:
        source.load()
        descriptor, target_name = tempfile.mkstemp(suffix=".png", prefix="ocr-paddle-")
        os.close(descriptor)
        target = Path(target_name)
        source.convert("RGB").save(target)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR PaddleOCR em português.")
    parser.add_argument("image", type=Path)
    args = parser.parse_args()

    normalized = normalize_image(args.image)
    try:
        ocr = PaddleOCR(use_angle_cls=True, lang="pt")
        pages = ocr.ocr(str(normalized), cls=True)
        lines = []
        for page in pages or []:
            for item in page or []:
                lines.append(item[1][0])
        print("\n".join(lines))
    finally:
        normalized.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
