#!/usr/bin/env python3
"""OCR em português com Tesseract e pré-processamento de imagem.

Instalação no Ubuntu:
  sudo apt-get install -y tesseract-ocr tesseract-ocr-por
  python3 -m pip install --user pytesseract opencv-python-headless pillow numpy

Modelo de maior precisão (tessdata_best):
  sudo mkdir -p /usr/share/tesseract-ocr/5/tessdata_best
  sudo wget -O /usr/share/tesseract-ocr/5/tessdata_best/por.traineddata \
    https://github.com/tesseract-ocr/tessdata_best/raw/main/por.traineddata

Exemplo:
  python3 scripts/ocr_tesseract_otimizado.py comprovante.jpeg \
    --tessdata-dir /usr/share/tesseract-ocr/5/tessdata_best --save-processed /tmp/ocr.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from PIL import Image, ImageFile


def load_image(image_path: Path) -> np.ndarray:
    """Abre inclusive JPEGs com final truncado e entrega uma imagem RGB."""
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    with Image.open(image_path) as source:
        source.load()
        return np.asarray(source.convert("RGB"))


def preprocess(image: np.ndarray) -> np.ndarray:
    """Prepara uma imagem monocromática nítida para a leitura do Tesseract."""
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)  # Remove informação de cor irrelevante.

    if max(gray.shape) < 2200:
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)  # Amplia caracteres pequenos.

    denoised = cv2.GaussianBlur(gray, (3, 3), 0)  # Suaviza ruído fino sem apagar letras.
    _, binary = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)  # Separa texto e fundo automaticamente.
    return binary


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR Tesseract otimizado para comprovantes.")
    parser.add_argument("image", type=Path)
    parser.add_argument("--tessdata-dir", type=Path, help="Diretório com por.traineddata, por exemplo tessdata_best.")
    parser.add_argument("--psm", type=int, default=6, help="Page segmentation mode do Tesseract.")
    parser.add_argument("--save-processed", type=Path, help="Salva o PNG pré-processado para inspeção.")
    args = parser.parse_args()

    processed = preprocess(load_image(args.image))
    if args.save_processed:
        args.save_processed.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(args.save_processed), processed)

    config = f"--oem 1 --psm {args.psm}"
    if args.tessdata_dir:
        config += f' --tessdata-dir "{args.tessdata_dir}"'
    print(pytesseract.image_to_string(processed, lang="por", config=config).strip())


if __name__ == "__main__":
    main()
