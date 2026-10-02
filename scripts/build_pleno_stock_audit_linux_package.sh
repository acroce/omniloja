#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PROJECT_NAME="$(basename "$ROOT_DIR")"
STAMP="${1:-$(date '+%Y%m%d-%H%M')}"
PACKAGE_NAME="pleno-stock-audit-linux-${STAMP}.tar.gz"
TMP_PACKAGE="${TMPDIR:-/tmp}/${PACKAGE_NAME}"
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/pleno-stock-audit-package.XXXXXX")"
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
  --exclude='./__pycache__' \
  --exclude='*/__pycache__' \
  --exclude='./tmp' \
  --exclude='./reports' \
  --exclude='./outputs' \
  --exclude='./.env' \
  --exclude='./config/pleno_fetch_remote.env' \
  --exclude='./config/pedidos_business_monitor_pull.env' \
  --exclude='./config/.pleno_*password*' \
  --exclude='./config/whatsapp-web-cert' \
  --exclude='./noc-pleno-linux-*.tar.gz' \
  --exclude='./pleno-stock-audit-linux-*.tar.gz' \
  --exclude='./pleno-stock-audit-dados*.tar.gz' \
  --exclude='./sap-api-monitor-linux-*.tar.gz' \
  --exclude='./whatsapp-monitor-linux-*.tar.gz' \
  --exclude='./.git' \
  . | tar -xf - -C "$STAGING_DIR/$PROJECT_NAME"

mkdir -p "$STAGING_DIR/$PROJECT_NAME/outputs/recebidos_servidor" \
  "$STAGING_DIR/$PROJECT_NAME/outputs/pleno_stock_audit" \
  "$STAGING_DIR/$PROJECT_NAME/outputs/pleno_stock_snapshots" \
  "$STAGING_DIR/$PROJECT_NAME/outputs/pleno_stock_audit_excel" \
  "$STAGING_DIR/$PROJECT_NAME/outputs/pleno_stock_official" \
  "$STAGING_DIR/$PROJECT_NAME/outputs/pleno_stock_official_index" \
  "$STAGING_DIR/$PROJECT_NAME/outputs/logs"

cd "$STAGING_DIR"
COPYFILE_DISABLE=1 tar -czf "$TMP_PACKAGE" "$PROJECT_NAME"

mv "$TMP_PACKAGE" "$ROOT_DIR/$PACKAGE_NAME"
printf '%s\n' "$ROOT_DIR/$PACKAGE_NAME"
