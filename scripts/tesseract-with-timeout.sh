#!/bin/sh
# OCR auxiliar nunca pode bloquear o fluxo: o Paddle assume se ele exceder o limite.
timeout 5 tesseract "$@" || true
