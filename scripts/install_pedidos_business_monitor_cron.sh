#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
TMP_CURRENT="$(mktemp "${TMPDIR:-/tmp}/pedidos-cron-current.XXXXXX")"
TMP_NEXT="$(mktemp "${TMPDIR:-/tmp}/pedidos-cron-next.XXXXXX")"
trap 'rm -f "$TMP_CURRENT" "$TMP_NEXT"' EXIT HUP INT TERM

BEGIN_MARK="# BEGIN Codex Monitor Pedidos Pleno"
END_MARK="# END Codex Monitor Pedidos Pleno"
RUNNER="$ROOT_DIR/scripts/run_pedidos_business_monitor_step.sh"
LOG="$ROOT_DIR/outputs/pleno_business_monitor/logs/pedidos_cron.log"

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
  printf "55 7 * * * cd %s && %s remote >> %s 2>&1\n" "$ROOT_DIR" "$RUNNER" "$LOG"
  printf "5 8 * * * cd %s && %s mysql_0805 >> %s 2>&1\n" "$ROOT_DIR" "$RUNNER" "$LOG"
  printf "10 8 * * * cd %s && %s check_0810 >> %s 2>&1\n" "$ROOT_DIR" "$RUNNER" "$LOG"
  printf "30 9 * * * cd %s && %s relex_0930 >> %s 2>&1\n" "$ROOT_DIR" "$RUNNER" "$LOG"
  printf "35 9 * * * cd %s && %s relex_processados >> %s 2>&1\n" "$ROOT_DIR" "$RUNNER" "$LOG"
  printf "%s\n" "$END_MARK"
} >> "$TMP_NEXT"

crontab "$TMP_NEXT"
echo "Crontab do monitor de pedidos instalada."
