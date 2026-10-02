#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ROOT="${PREV_PERDAS_ROOT:-$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)}"
LOG="$ROOT/outputs/prevencao_perdas/cron.log"
LOCK_FILE="${PREV_PERDAS_LOCK_FILE:-$ROOT/outputs/prevencao_perdas/prevencao-perdas.lock}"

mkdir -p "$(dirname "$LOG")"
cd "$ROOT"

exec flock -n -o "$LOCK_FILE" \
  env PREV_PERDAS_LIMIT="${PREV_PERDAS_LIMIT:-1000}" PREV_PERDAS_INCLUDE_RETRIES="${PREV_PERDAS_INCLUDE_RETRIES:-1}" \
  PREV_PERDAS_EMISSAO_TIMEOUT_MS="${PREV_PERDAS_EMISSAO_TIMEOUT_MS:-30000}" \
  PREV_PERDAS_NOTA_NAV_TIMEOUT_MS="${PREV_PERDAS_NOTA_NAV_TIMEOUT_MS:-15000}" \
  PREV_PERDAS_NOTA_COMMIT_TIMEOUT_MS="${PREV_PERDAS_NOTA_COMMIT_TIMEOUT_MS:-8000}" \
  PREV_PERDAS_NOTA_SETTLE_MS="${PREV_PERDAS_NOTA_SETTLE_MS:-3000}" \
  PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/ms-playwright}" \
  HOME="${HOME:-/root}" \
  xvfb-run -a node scripts/prevencao-perdas-lote.mjs >> "$LOG" 2>&1
