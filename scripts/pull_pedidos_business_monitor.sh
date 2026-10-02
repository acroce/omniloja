#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
STATUS_FILE="${PEDIDOS_MONITOR_STATUS_FILE:-$ROOT_DIR/outputs/pleno_business_monitor/pedidos.json}"
REMOTE_HOST="${PEDIDOS_REMOTE_HOST:-}"
REMOTE_USER="${PEDIDOS_REMOTE_USER:-}"
REMOTE_PORT="${PEDIDOS_REMOTE_PORT:-22}"
REMOTE_COMMAND="${PEDIDOS_REMOTE_COMMAND:-}"
REMOTE_SCRIPT_FILE="${PEDIDOS_REMOTE_SCRIPT_FILE:-}"
SSH_KEY="${PEDIDOS_SSH_KEY:-}"
SSH_PASSWORD="${PEDIDOS_SSH_PASSWORD:-}"
SSH_STRICT_HOST_KEY_CHECKING="${PEDIDOS_SSH_STRICT_HOST_KEY_CHECKING:-accept-new}"
SSH_TIMEOUT_SECONDS="${PEDIDOS_SSH_TIMEOUT_SECONDS:-60}"

if [ -z "$REMOTE_HOST" ] || [ -z "$REMOTE_USER" ]; then
  echo "Configure PEDIDOS_REMOTE_HOST e PEDIDOS_REMOTE_USER." >&2
  exit 64
fi

if [ -z "$REMOTE_COMMAND" ]; then
  REMOTE_COMMAND="PEDIDOS_DIR=/servpleno/importacao PEDIDOS_EXPORT_DIR=/servpleno/exportacao PEDIDOS_PROCESSED_DIR=/servpleno/exportacao/processados sh -s"
fi

mkdir -p "$(dirname "$STATUS_FILE")"

TMP_FILE="$(mktemp "${STATUS_FILE}.remote.XXXXXX")"
ASKPASS_FILE=""
trap 'rm -f "$TMP_FILE"; [ -z "$ASKPASS_FILE" ] || rm -f "$ASKPASS_FILE"' EXIT HUP INT TERM
ERR_FILE="${STATUS_FILE}.last_error"

SSH_BATCH_MODE=yes
if [ -n "$SSH_PASSWORD" ]; then
  SSH_BATCH_MODE=no
fi
SSH_ARGS="-p $REMOTE_PORT -o BatchMode=$SSH_BATCH_MODE -o ConnectTimeout=$SSH_TIMEOUT_SECONDS -o StrictHostKeyChecking=$SSH_STRICT_HOST_KEY_CHECKING"
if [ -n "$SSH_KEY" ]; then
  SSH_ARGS="$SSH_ARGS -i $SSH_KEY"
fi

validate_and_normalize_json() {
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$TMP_FILE" "$STATUS_FILE" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
status_path = Path(sys.argv[2])
text = path.read_text(encoding="utf-8", errors="replace")
start = text.find("{")
end = text.rfind("}")
if start < 0 or end < start:
    raise SystemExit("JSON nao encontrado na saida do SSH")
data = json.loads(text[start:end + 1])

local_event_ids = {
    "checagem_0805",
    "checagem_0810",
    "arquivo_vs_pleno",
    "pedido_concluido",
}
today = __import__("datetime").datetime.now().date().isoformat()

def event_is_today(event):
    actual_at = str((event or {}).get("checkedAt") or (event or {}).get("actualAt") or "")
    return actual_at.startswith(today)

if status_path.exists() and status_path.stat().st_size > 0:
    try:
        current = json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        current = {}
    current_events = current.get("events") or {}
    incoming_events = data.get("events") or {}
    merged_events = dict(current_events)
    for event_id, event in incoming_events.items():
        if event_id in local_event_ids and event_id in current_events and event_is_today(current_events[event_id]):
            continue
        merged_events[event_id] = event
    for event_id in local_event_ids:
        if event_id in merged_events and not event_is_today(merged_events[event_id]):
            merged_events.pop(event_id, None)
    data["events"] = merged_events

path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
  elif command -v node >/dev/null 2>&1; then
    node - "$TMP_FILE" "$STATUS_FILE" <<'JS'
const fs = require("fs");
const path = process.argv[2];
const statusPath = process.argv[3];
const text = fs.readFileSync(path, "utf8");
const start = text.indexOf("{");
const end = text.lastIndexOf("}");
if (start < 0 || end < start) throw new Error("JSON nao encontrado na saida do SSH");
const data = JSON.parse(text.slice(start, end + 1));
const localEventIds = new Set(["checagem_0805", "checagem_0810", "arquivo_vs_pleno", "pedido_concluido"]);
const now = new Date();
const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
const eventIsToday = (event) => String((event || {}).checkedAt || (event || {}).actualAt || "").startsWith(today);
if (fs.existsSync(statusPath) && fs.statSync(statusPath).size > 0) {
  let current = {};
  try {
    current = JSON.parse(fs.readFileSync(statusPath, "utf8"));
  } catch {}
  const mergedEvents = { ...(current.events || {}) };
  for (const [eventId, event] of Object.entries(data.events || {})) {
    if (localEventIds.has(eventId) && mergedEvents[eventId] && eventIsToday(mergedEvents[eventId])) continue;
    mergedEvents[eventId] = event;
  }
  for (const eventId of localEventIds) {
    if (mergedEvents[eventId] && !eventIsToday(mergedEvents[eventId])) delete mergedEvents[eventId];
  }
  data.events = mergedEvents;
}
fs.writeFileSync(path, JSON.stringify(data, null, 2) + "\n");
JS
  else
    echo "python3 ou node e necessario para validar o JSON." >&2
    exit 69
  fi
}

run_ssh() {
  if [ -n "$SSH_PASSWORD" ]; then
    if command -v sshpass >/dev/null 2>&1; then
      if [ -n "$REMOTE_SCRIPT_FILE" ]; then
        # shellcheck disable=SC2086
        sshpass -p "$SSH_PASSWORD" ssh $SSH_ARGS "$REMOTE_USER@$REMOTE_HOST" "$REMOTE_COMMAND" < "$REMOTE_SCRIPT_FILE"
      else
        # shellcheck disable=SC2086
        sshpass -p "$SSH_PASSWORD" ssh $SSH_ARGS "$REMOTE_USER@$REMOTE_HOST" "$REMOTE_COMMAND"
      fi
    else
      ASKPASS_FILE="$(mktemp "${TMPDIR:-/tmp}/pedidos-askpass.XXXXXX")"
      printf '#!/bin/sh\nprintf "%%s\\n" "$PEDIDOS_SSH_PASSWORD"\n' > "$ASKPASS_FILE"
      chmod 700 "$ASKPASS_FILE"
      if [ -n "$REMOTE_SCRIPT_FILE" ]; then
        # shellcheck disable=SC2086
        DISPLAY="${DISPLAY:-:0}" SSH_ASKPASS="$ASKPASS_FILE" SSH_ASKPASS_REQUIRE=force PEDIDOS_SSH_PASSWORD="$SSH_PASSWORD" ssh $SSH_ARGS "$REMOTE_USER@$REMOTE_HOST" "$REMOTE_COMMAND" < "$REMOTE_SCRIPT_FILE"
      else
        # shellcheck disable=SC2086
        DISPLAY="${DISPLAY:-:0}" SSH_ASKPASS="$ASKPASS_FILE" SSH_ASKPASS_REQUIRE=force PEDIDOS_SSH_PASSWORD="$SSH_PASSWORD" ssh $SSH_ARGS "$REMOTE_USER@$REMOTE_HOST" "$REMOTE_COMMAND"
      fi
    fi
  else
    if [ -n "$REMOTE_SCRIPT_FILE" ]; then
      # shellcheck disable=SC2086
      ssh $SSH_ARGS "$REMOTE_USER@$REMOTE_HOST" "$REMOTE_COMMAND" < "$REMOTE_SCRIPT_FILE"
    else
      # shellcheck disable=SC2086
      ssh $SSH_ARGS "$REMOTE_USER@$REMOTE_HOST" "$REMOTE_COMMAND"
    fi
  fi
}

if run_ssh > "$TMP_FILE" 2> "$ERR_FILE"; then
  validate_and_normalize_json
  mv "$TMP_FILE" "$STATUS_FILE"
  rm -f "$ERR_FILE"
  echo "Monitor de pedidos atualizado em $STATUS_FILE"
else
  rm -f "$TMP_FILE"
  echo "Falha ao buscar monitor de pedidos. Detalhe em $ERR_FILE" >&2
  exit 1
fi
