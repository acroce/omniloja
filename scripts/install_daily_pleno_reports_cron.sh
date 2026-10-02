#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
TMP_CURRENT="$(mktemp "${TMPDIR:-/tmp}/daily-pleno-cron-current.XXXXXX")"
TMP_NEXT="$(mktemp "${TMPDIR:-/tmp}/daily-pleno-cron-next.XXXXXX")"
trap 'rm -f "$TMP_CURRENT" "$TMP_NEXT"' EXIT HUP INT TERM

BEGIN_MARK="# BEGIN Codex Daily Pleno Reports"
END_MARK="# END Codex Daily Pleno Reports"
RUNNER="$HOME/.pleno_daily_reports_cron/run_daily_pleno_reports_status.sh"
LOG_DIR="$ROOT_DIR/outputs/daily_pleno_reports/logs"
LOG="$LOG_DIR/daily_pleno_reports.log"

mkdir -p "$LOG_DIR"

if crontab -l > "$TMP_CURRENT" 2>/dev/null; then
  awk -v begin="$BEGIN_MARK" -v end="$END_MARK" '
    $0 == begin { skip = 1; next }
    $0 == end { skip = 0; next }
    skip != 1 { print }
  ' "$TMP_CURRENT" > "$TMP_NEXT"
else
  : > "$TMP_NEXT"
fi

{
  printf "\n%s\n" "$BEGIN_MARK"
  printf "SHELL=/bin/sh\n"
  printf "PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin\n"
  printf "0 9 * * * cd %s && sh %s >> %s 2>&1\n" "$ROOT_DIR" "$RUNNER" "$LOG"
  printf "%s\n" "$END_MARK"
} >> "$TMP_NEXT"

crontab "$TMP_NEXT"
echo "Cron instalado: relatorios Pleno todos os dias as 09:00. Log: $LOG"
