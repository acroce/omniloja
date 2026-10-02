#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
RECIPIENT="${DAILY_PLENO_REPORTS_RECIPIENT:-marcela.silva@diagroup.com}"
NODE_BIN="${NODE_BIN:-}"

if [ -z "$NODE_BIN" ]; then
  if command -v node >/dev/null 2>&1; then
    NODE_BIN="$(command -v node)"
  else
    NODE_BIN="/Users/alexandrematheuscrose/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
  fi
fi

cd "$ROOT_DIR"
python3 "$ROOT_DIR/scripts/generate_daily_pleno_reports.py" --email "$RECIPIENT" --no-chat
"$NODE_BIN" "$ROOT_DIR/scripts/send_daily_pleno_reports_google_chat_web.mjs" --recipient "$RECIPIENT"
