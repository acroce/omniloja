#!/bin/sh
set -eu

if [ -d /app/scripts ]; then
  DEFAULT_ROOT=/app
else
  DEFAULT_ROOT=/home/dia-brasil/cofre-inteligente
fi

ROOT="${TESOURARIA_ROOT:-$DEFAULT_ROOT}"
LOG="$ROOT/outputs/tesouraria_cofre_inteligente/cron.log"
LOCK_FILE="${TESOURARIA_LOCK_FILE:-/tmp/tesouraria-cofre-inteligente.lock}"

mkdir -p "$(dirname "$LOG")"
cd "$ROOT"

# A trava evita duas sessões do Chrome atuando no mesmo fluxo financeiro.
exec flock -n "$LOCK_FILE" \
  env TESOURARIA_LIMIT=1000 TESOURARIA_INCLUDE_RETRIES=1 \
  xvfb-run -a node scripts/tesouraria-cofre-lote.mjs >> "$LOG" 2>&1
