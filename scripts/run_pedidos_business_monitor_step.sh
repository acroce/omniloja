#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
STEP="${1:-all}"
LOG_DIR="$ROOT_DIR/outputs/pleno_business_monitor/logs"
STATUS_FILE="${PEDIDOS_MONITOR_STATUS_FILE:-$ROOT_DIR/outputs/pleno_business_monitor/pedidos.json}"
REMOTE_SCRIPT_FILE="$ROOT_DIR/config/pedidos_monitor_json.remote.example.sh"
LOCK_FILE="${STATUS_FILE}.collect.lock"

mkdir -p "$LOG_DIR" "$(dirname "$STATUS_FILE")"
# BusyBox ps does not support -p. Kernel locking serializes cron, watcher and UI.
exec 9> "$LOCK_FILE"
lock_attempts=0
while ! flock -n 9; do
  lock_attempts=$((lock_attempts + 1))
  if [ "$lock_attempts" -ge 120 ]; then
    echo "Nao consegui obter lock de pedidos em $LOCK_FILE." >&2
    exit 75
  fi
  sleep 1
done

load_env_file() {
  if [ -f "$1" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$1"
    set +a
  fi
}

load_env_file_fallback() {
  file="$1"
  [ -f "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    key="$(printf "%s\n" "$line" | sed -n 's/^[[:space:]]*\([A-Za-z_][A-Za-z0-9_]*\)[[:space:]]*=.*/\1/p')"
    [ -n "$key" ] || continue
    if eval '[ -z "${'"$key"'+x}" ]'; then
      value="$(set -a; . "$file"; eval 'printf "%s" "${'"$key"'-}"')"
      export "$key=$value"
    fi
  done < "$file"
}

load_env_file "$ROOT_DIR/.env"
load_env_file_fallback "$ROOT_DIR/config/pleno_fetch_remote.env"
load_env_file_fallback "$ROOT_DIR/config/pedidos_business_monitor_pull.env"

export PEDIDOS_REMOTE_USER="${PEDIDOS_REMOTE_USER:-${STOCK_REMOTE_USER:-}}"
export PEDIDOS_REMOTE_HOST="${PEDIDOS_REMOTE_HOST:-${STOCK_REMOTE_HOST:-}}"
export PEDIDOS_REMOTE_PORT="${PEDIDOS_REMOTE_PORT:-${STOCK_REMOTE_PORT:-22}}"
export PEDIDOS_SSH_PASSWORD="${PEDIDOS_SSH_PASSWORD:-${STOCK_REMOTE_PASSWORD:-}}"
export STOCK_REMOTE_USER="${STOCK_REMOTE_USER:-$PEDIDOS_REMOTE_USER}"
export STOCK_REMOTE_HOST="${STOCK_REMOTE_HOST:-$PEDIDOS_REMOTE_HOST}"
export STOCK_REMOTE_PORT="${STOCK_REMOTE_PORT:-$PEDIDOS_REMOTE_PORT}"
export STOCK_REMOTE_PASSWORD="${STOCK_REMOTE_PASSWORD:-$PEDIDOS_SSH_PASSWORD}"
export PEDIDOS_SSH_STRICT_HOST_KEY_CHECKING="${PEDIDOS_SSH_STRICT_HOST_KEY_CHECKING:-accept-new}"
export PEDIDOS_SSH_TIMEOUT_SECONDS="${PEDIDOS_SSH_TIMEOUT_SECONDS:-60}"
export PEDIDOS_MONITOR_STATUS_FILE="$STATUS_FILE"
export PEDIDOS_REMOTE_SCRIPT_FILE="$REMOTE_SCRIPT_FILE"
export PEDIDOS_REMOTE_COMMAND="PEDIDOS_DIR=/servpleno/importacao PEDIDOS_EXPORT_DIR=/servpleno/exportacao PEDIDOS_PROCESSED_DIR=/servpleno/exportacao/processados sh -s"

timestamp() {
  date "+%Y-%m-%d %H:%M:%S"
}

run_remote() {
  echo "[$(timestamp)] Coletando arquivos/RELEX no servidor..."
  "$ROOT_DIR/scripts/pull_pedidos_business_monitor.sh"
}

run_mysql() {
  event_id="$1"
  target_time="$2"
  echo "[$(timestamp)] Atualizando consulta MySQL $event_id..."
  python3 "$ROOT_DIR/scripts/update_pedidos_mysql_monitor.py" \
    --status-file "$STATUS_FILE" \
    --event-id "$event_id" \
    --target-time "$target_time"
}

run_file_vs_pleno() {
  echo "[$(timestamp)] Cruzando arquivo de pedidos com Pleno..."
  python3 "$ROOT_DIR/scripts/check_pedidos_arquivo_vs_pleno.py" \
    --status-file "$STATUS_FILE"
}

run_expected_stores() {
  echo "[$(timestamp)] Atualizando lojas esperadas para pedidos no Pleno..."
  python3 "$ROOT_DIR/scripts/update_pedidos_lojas_esperadas_monitor.py" \
    --status-file "$STATUS_FILE"
}

time_reached() {
  target="$1"
  now_hm="$(date "+%H%M")"
  target_hm="$(printf "%s" "$target" | tr -d ':')"
  [ "$now_hm" -ge "$target_hm" ]
}

mark_waiting() {
  event_id="$1"
  target_time="$2"
  details="$3"
  python3 - "$STATUS_FILE" "$event_id" "$target_time" "$details" <<'PY'
import json
import sys
from datetime import datetime
from pathlib import Path

path = Path(sys.argv[1])
event_id = sys.argv[2]
target_time = sys.argv[3]
details = sys.argv[4]
data = json.loads(path.read_text(encoding="utf-8"))
data["updatedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
data.setdefault("events", {})[event_id] = {
    "targetTime": target_time,
    "status": "aguardando",
    "actualAt": "",
    "count": 0,
    "source": "agenda local",
    "details": details,
}
tmp = path.with_suffix(path.suffix + ".tmp")
tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
tmp.replace(path)
PY
}

collection_failed=0
run_checked() {
  affected_events="$1"
  shift
  if "$@"; then
    return 0
  else
    step_status=$?
    collection_failed=1
    python3 - "$STATUS_FILE" "$affected_events" "$step_status" <<'PYERROR'
import json, os, sys, tempfile
from datetime import datetime
from pathlib import Path
path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text())
except (OSError, ValueError):
    data = {}
now = datetime.now().astimezone().isoformat(timespec="seconds")
data["updatedAt"] = now
for key in sys.argv[2].split(","):
    data.setdefault("events", {})[key] = {
        "status": "erro", "actualAt": "", "checkedAt": now, "count": 0,
        "source": "coleta local",
        "details": f"Falha na coleta atual de {key} (codigo {sys.argv[3]}). Consulte o log de pedidos; dados anteriores nao confirmados.",
    }
with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=path.name+".", suffix=".tmp", delete=False) as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    name = f.name
os.replace(name, path)
PYERROR
    return 0
  fi
}

case "$STEP" in
  remote|arquivos_0755|relex_0930|relex_processados)
    run_checked arquivo_original,arquivo_chegada,envio_relex,relex_processados run_remote
    ;;
  mysql_0805)
    run_checked checagem_0805 run_mysql checagem_0805 08:05
    ;;
  mysql_0810)
    run_checked checagem_0810 run_mysql checagem_0810 08:10
    ;;
  arquivo_vs_pleno)
    run_checked arquivo_vs_pleno,pedido_concluido run_file_vs_pleno
    ;;
  lojas_esperadas)
    run_checked lojas_diaflex run_expected_stores
    ;;
  check_0810)
    run_checked lojas_diaflex run_expected_stores
    run_checked arquivo_original,arquivo_chegada,envio_relex,relex_processados run_remote
    run_checked arquivo_vs_pleno,pedido_concluido run_file_vs_pleno
    run_checked checagem_0810 run_mysql checagem_0810 08:10
    ;;
  all)
    run_checked lojas_diaflex run_expected_stores
    run_checked arquivo_original,arquivo_chegada,envio_relex,relex_processados run_remote
    if time_reached "08:10"; then
      run_checked arquivo_vs_pleno,pedido_concluido run_file_vs_pleno
    else
      mark_waiting arquivo_vs_pleno 08:10 "Aguardando horario 08:10 para cruzar arquivo de pedidos com o Pleno."
    fi
    if time_reached "08:05"; then
      run_checked checagem_0805 run_mysql checagem_0805 08:05
    else
      mark_waiting checagem_0805 08:05 "Aguardando horario 08:05 para consulta MySQL."
    fi
    if time_reached "08:10"; then
      run_checked checagem_0810 run_mysql checagem_0810 08:10
    else
      mark_waiting checagem_0810 08:10 "Aguardando horario 08:10 para segunda consulta MySQL."
    fi
    ;;
  *)
    echo "Uso: $0 {remote|mysql_0805|mysql_0810|arquivo_vs_pleno|check_0810|all}" >&2
    exit 64
    ;;
esac


if [ "$collection_failed" -ne 0 ]; then
  echo "Coleta de pedidos incompleta; eventos de falha atualizados." >&2
  exit 1
fi
echo "[$(timestamp)] Etapa $STEP concluida."
