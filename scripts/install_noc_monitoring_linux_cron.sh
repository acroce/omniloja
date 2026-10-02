#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
TMP_CURRENT="$(mktemp "${TMPDIR:-/tmp}/noc-linux-cron-current.XXXXXX")"
TMP_NEXT="$(mktemp "${TMPDIR:-/tmp}/noc-linux-cron-next.XXXXXX")"
trap 'rm -f "$TMP_CURRENT" "$TMP_NEXT"' EXIT HUP INT TERM

BEGIN="# BEGIN Codex NOC Pleno Docker"
END="# END Codex NOC Pleno Docker"
CONTAINER="${NOC_CONTAINER_NAME:-noc-pleno-audit-web}"
DOCKER_COMMAND="${NOC_DOCKER_COMMAND:-docker}"
LOG_DIR="$ROOT_DIR/outputs/pleno_business_monitor/logs"
HOST_CRON_LOG="$LOG_DIR/noc_dispatcher_host_cron.log"

mkdir -p "$LOG_DIR"

if ! command -v crontab >/dev/null 2>&1; then
  echo "crontab nao encontrado no Linux; instale cron/cronie para agendar as coletas." >&2
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

run_in_container="$DOCKER_COMMAND exec $CONTAINER"

{
  printf "\n%s\n" "$BEGIN"
  printf "SHELL=/bin/sh\n"
  printf "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin\n"
  # date -Is evita '%' no crontab, que o cron interpreta como quebra de linha.
  printf "* * * * * date -Is >> %s 2>&1; %s python3 /app/scripts/noc_monitor_dispatcher.py >> %s 2>&1\n" "$HOST_CRON_LOG" "$run_in_container" "$HOST_CRON_LOG"
  printf "%s\n" "$END"
} >> "$TMP_NEXT"

crontab "$TMP_NEXT"
echo "Crontab Linux NOC instalada para o container $CONTAINER."
echo "Agendamento: dispatcher a cada minuto, com controle interno para rodar cada monitor no horario correto."
echo "Log de batimento do cron: $HOST_CRON_LOG"
