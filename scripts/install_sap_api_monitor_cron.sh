#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
TMP_CURRENT="$(mktemp "${TMPDIR:-/tmp}/sap-api-cron-current.XXXXXX")"
TMP_NEXT="$(mktemp "${TMPDIR:-/tmp}/sap-api-cron-next.XXXXXX")"
trap 'rm -f "$TMP_CURRENT" "$TMP_NEXT"' EXIT HUP INT TERM

BEGIN="# BEGIN Codex Monitor APIs SAP"
END="# END Codex Monitor APIs SAP"
RUNNER="$ROOT_DIR/scripts/update_sap_api_monitor.py"
CHECKIN_RUNNER="$ROOT_DIR/scripts/update_checkin_notas_monitor.py"
LOG_DIR="$ROOT_DIR/outputs/pleno_business_monitor/logs"
LOG_FILE="$LOG_DIR/sap_api_monitor_cron.log"
CHECKIN_LOG_FILE="$LOG_DIR/checkin_notas_monitor_cron.log"

mkdir -p "$LOG_DIR"

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
  printf "PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin\n"
  printf "*/10 * * * * cd %s && python3 %s >> %s 2>&1\n" "$ROOT_DIR" "$RUNNER" "$LOG_FILE"
  printf "*/10 * * * * cd %s && python3 %s >> %s 2>&1\n" "$ROOT_DIR" "$CHECKIN_RUNNER" "$CHECKIN_LOG_FILE"
  printf "%s\n" "$END"
} >> "$TMP_NEXT"

crontab "$TMP_NEXT"
echo "Crontab instalada para Monitor APIs SAP e check-in de notas a cada 10 minutos."
