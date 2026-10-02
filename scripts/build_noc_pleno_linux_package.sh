#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PROJECT_NAME="$(basename "$ROOT_DIR")"
STAMP="${1:-$(date '+%Y%m%d-%H%M')}"
PACKAGE_NAME="noc-pleno-linux-${STAMP}.tar.gz"
TMP_PACKAGE="${TMPDIR:-/tmp}/${PACKAGE_NAME}"
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/noc-pleno-package.XXXXXX")"
trap 'rm -rf "$STAGING_DIR"' EXIT HUP INT TERM

mkdir -p "$STAGING_DIR/$PROJECT_NAME"

cd "$ROOT_DIR"
COPYFILE_DISABLE=1 tar -cf - \
  --exclude='./node_modules' \
  --exclude='./.venv' \
  --exclude='./.venv_devolucao' \
  --exclude='./.cache' \
  --exclude='./.google-chat-profile' \
  --exclude='./.python_packages' \
  --exclude='./tmp' \
  --exclude='./reports' \
  --exclude='./outputs' \
  --exclude='./*.tar.gz' \
  --exclude='./*.tgz' \
  --exclude='./estoque_*.csv' \
  --exclude='./estoque_*.csv.zip' \
  --exclude='./.git' \
  . | tar -xf - -C "$STAGING_DIR/$PROJECT_NAME"

cd "$STAGING_DIR"
COPYFILE_DISABLE=1 tar -czf "$TMP_PACKAGE" "$PROJECT_NAME"

mv "$TMP_PACKAGE" "$ROOT_DIR/$PACKAGE_NAME"
printf '%s\n' "$ROOT_DIR/$PACKAGE_NAME"
