#!/usr/bin/env python3
"""OCR rapido para imagens JPEG/PNG usando PaddleOCR e ONNX Runtime."""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageFile
from paddleocr import PaddleOCR

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "paddle-onnx"

# Evita que bibliotecas numericas abram muitos workers para uma imagem pequena.
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("ORT_DISABLE_ALL", "0")


def build_ocr() -> PaddleOCR:
    return PaddleOCR(
        lang="pt",
        use_onnx=True,
        use_gpu=False,
        use_angle_cls=False,
        show_log=False,
        det_model_dir=str(MODEL_DIR / "det" / "model.onnx"),
        rec_model_dir=str(MODEL_DIR / "rec" / "model.onnx"),
        cls_model_dir=str(MODEL_DIR / "cls" / "model.onnx"),
    )


def normalized_image_path(image_path: Path) -> Path:
    """Converte imagens de download parcialmente truncadas para um PNG legível."""
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    with Image.open(image_path) as source:
        source.load()
        image = source.convert("RGB")
    descriptor, target_name = tempfile.mkstemp(suffix=".png", prefix="ocr-paddle-")
    os.close(descriptor)
    target = Path(target_name)
    image.save(target, format="PNG", optimize=False)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Extrai texto de uma imagem PNG/JPG com PaddleOCR ONNX.")
    parser.add_argument("image", type=Path)
    parser.add_argument("--benchmark", action="store_true", help="Mostra o tempo no stderr.")
    args = parser.parse_args()

    if args.image.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise SystemExit("Somente imagens PNG, JPG ou JPEG sao aceitas.")
    if not args.image.is_file():
        raise SystemExit(f"Imagem nao encontrada: {args.image}")

    normalized = normalized_image_path(args.image)
    rotated = None
    try:
        ocr = build_ocr()
        started = time.perf_counter()
        result = ocr.ocr(str(normalized), cls=False)
        lines = [item[1][0] for item in result[0] if result]
        if len(re.findall(r"\d{2}/\d{2}/\d{4}", "\n".join(lines))) < 2:
            with Image.open(normalized) as source:
                image = source.rotate(-90, expand=True)
                descriptor, rotated_name = tempfile.mkstemp(suffix=".png", prefix="ocr-paddle-rotated-")
                os.close(descriptor)
                rotated = Path(rotated_name)
                image.save(rotated, format="PNG", optimize=False)
            result = ocr.ocr(str(rotated), cls=False)
        elapsed = time.perf_counter() - started
    finally:
        normalized.unlink(missing_ok=True)
        if rotated:
            rotated.unlink(missing_ok=True)

    def normalize_line(text: str) -> str:
        text = re.sub(r"(\d{4})(?=\d{2}:\d{2})", r"\1 ", text)
        text = text.replace("/88/", "/08/")
        text = re.sub(r"\d+([0-3]\d/[01]\d/\d{4})", r"\1", text)
        return re.sub(r"\bTota[1l]\b", "Total", text, flags=re.IGNORECASE)

    lines = [normalize_line(item[1][0]) for item in result[0] if result]
    for index, line in enumerate(lines):
        # Em fotos fracas, o OCR pode separar "Total:" do valor por uma linha de ruído.
        if re.fullmatch(r"Total\s*:?", line, flags=re.IGNORECASE):
            nearby = next((candidate for candidate in lines[index + 1:index + 4]
                           if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})*[.,]\d{2}", candidate)), None)
            if nearby:
                print(f"Total: {nearby}")
        print(line)
    if args.benchmark:
        print(f"OCR_ONNX_SECONDS={elapsed:.3f}", file=sys.stderr)


if __name__ == "__main__":
    main()
