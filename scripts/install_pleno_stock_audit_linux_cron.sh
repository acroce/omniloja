#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
TMP_CURRENT="$(mktemp "${TMPDIR:-/tmp}/pleno-stock-audit-cron-current.XXXXXX")"
TMP_NEXT="$(mktemp "${TMPDIR:-/tmp}/pleno-stock-audit-cron-next.XXXXXX")"
trap 'rm -f "$TMP_CURRENT" "$TMP_NEXT"' EXIT HUP INT TERM

BEGIN="# BEGIN Codex Auditoria Estoque Pleno"
END="# END Codex Auditoria Estoque Pleno"
CONTAINER="${PLENO_STOCK_AUDIT_CONTAINER_NAME:-pleno-audit-web}"
DOCKER_COMMAND="${PLENO_STOCK_AUDIT_DOCKER_COMMAND:-docker}"
STOCK_TIME="${PLENO_STOCK_AUDIT_STOCK_TIME:-0 1 * * *}"
AUDIT_TIME="${PLENO_STOCK_AUDIT_AUDIT_TIME:-30 1 * * *}"
COLLECTION_ARGS="${PLENO_STOCK_AUDIT_COLLECTION_ARGS:-}"
LOG_DIR="$ROOT_DIR/outputs/logs"
STOCK_LOG="$LOG_DIR/pleno_stock_audit_estoque_local.log"
AUDIT_LOG="$LOG_DIR/pleno_stock_audit_movimentos_local.log"

mkdir -p "$LOG_DIR"

if ! command -v crontab >/dev/null 2>&1; then
  echo "crontab nao encontrado no Linux; instale cron/cronie para agendar a busca dos arquivos." >&2
  exit 0
fi

if crontab -l > "$TMP_CURRENT" 2>/dev/null; then
  awk -v begin="$BEGIN" -v end="$END" '
    $0 == begin { skip = 1; next }
    $0 == end { skip = 0; next }
    skip != 1 { print }
  ' "$TMP_CURRENT" > "$TMP_NEXT"
else
  : > "$TMP_NEXT"
fi

{
  printf "\n%s\n" "$BEGIN"
  printf "SHELL=/bin/sh\n"
  printf "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n"
  printf "%s cd %s && %s exec %s /app/scripts/run_pleno_stock_local_collection.sh estoque %s >> %s 2>&1\n" \
    "$STOCK_TIME" "$ROOT_DIR" "$DOCKER_COMMAND" "$CONTAINER" "$COLLECTION_ARGS" "$STOCK_LOG"
  printf "%s cd %s && %s exec %s /app/scripts/run_pleno_stock_local_collection.sh auditoria %s >> %s 2>&1\n" \
    "$AUDIT_TIME" "$ROOT_DIR" "$DOCKER_COMMAND" "$CONTAINER" "$COLLECTION_ARGS" "$AUDIT_LOG"
  printf "%s\n" "$END"
} >> "$TMP_NEXT"

crontab "$TMP_NEXT"
echo "Crontab da auditoria de estoque instalada para o container $CONTAINER."
echo "Estoque oficial local: $STOCK_TIME"
echo "Auditoria movimentos local: $AUDIT_TIME"
echo "Argumentos da coleta: ${COLLECTION_ARGS:-nenhum}"
echo "Logs: $STOCK_LOG e $AUDIT_LOG"
