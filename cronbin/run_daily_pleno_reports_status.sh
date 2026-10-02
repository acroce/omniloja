#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
RECIPIENT="${DAILY_PLENO_REPORTS_RECIPIENT:-marcela.silva@diagroup.com}"
LOG_DIR="$ROOT_DIR/outputs/daily_pleno_reports/logs"
STATUS_FILE="$LOG_DIR/latest_status.txt"
TELEGRAM_SENDER="$ROOT_DIR/scripts/send_telegram_message.py"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

if output="$(python3 "$ROOT_DIR/scripts/generate_daily_pleno_reports.py" --email "$RECIPIENT" --no-chat 2>&1)"; then
  first_line="$(printf "%s\n" "$output" | sed -n '1p')"
  message="OK: arquivos Pleno gerados em $(date '+%Y-%m-%d %H:%M:%S'). Pasta: $first_line"
  printf "%s\n%s\n" "$message" "$output" > "$STATUS_FILE"
  printf "%s\n" "$message" | python3 "$TELEGRAM_SENDER" --chat-ids-env TELEGRAM_REPORT_CHAT_IDS || true
  printf "%s\n" "$message"
else
  status=$?
  message="ERRO: falha ao gerar arquivos Pleno em $(date '+%Y-%m-%d %H:%M:%S')."
  printf "%s\n%s\n" "$message" "$output" > "$STATUS_FILE"
  printf "%s\n%s\n" "$message" "$output" | python3 "$TELEGRAM_SENDER" --chat-ids-env TELEGRAM_REPORT_CHAT_IDS || true
  printf "%s\n%s\n" "$message" "$output" >&2
  exit "$status"
fi
