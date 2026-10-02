#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${PLENO_FETCH_CONFIG:-${PROJECT_ROOT}/config/pleno_fetch_remote.env}"

if [[ -f "${CONFIG_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${CONFIG_FILE}"
fi

STOCK_REMOTE_USER="${STOCK_REMOTE_USER:-amc018br}"
STOCK_REMOTE_HOST="${STOCK_REMOTE_HOST:-172.22.20.101}"
STOCK_REMOTE_PORT="${STOCK_REMOTE_PORT:-22}"
STOCK_REMOTE_PASSWORD="${STOCK_REMOTE_PASSWORD:-${REMOTE_PASSWORD:-}}"
STOCK_REMOTE_PASSWORD_FILE="${STOCK_REMOTE_PASSWORD_FILE:-}"
STOCK_CURRENT_DIR="${STOCK_CURRENT_DIR:-/servpleno/exportacao}"
STOCK_PREVIOUS_DIR="${STOCK_PREVIOUS_DIR:-/servpleno/exportacao/processados}"
LOCAL_INBOX="${LOCAL_INBOX:-outputs/recebidos_servidor}"

if [[ "${LOCAL_INBOX}" != /* ]]; then
  LOCAL_INBOX="${PROJECT_ROOT}/${LOCAL_INBOX}"
fi

mkdir -p "${LOCAL_INBOX}"

usage() {
  cat <<'EOF'
Uso:
  scripts/fetch_pleno_stock_official_latest.sh [--date YYYY-MM-DD] [--no-previous]

Baixa o estoque oficial do Pleno:
  data alvo:     /servpleno/exportacao/estoque_YYYYMMDD*.csv
  data anterior: /servpleno/exportacao/processados/estoque_YYYYMMDD*.csv

Quando houver mais de um arquivo no mesmo dia, usa o mais recente por criacao
quando disponivel no filesystem remoto; caso contrario, usa modificacao.
EOF
}

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

read_password_file() {
  local password_file="$1"
  [[ -n "${password_file}" ]] || return 0
  if [[ "${password_file}" != /* ]]; then
    password_file="${PROJECT_ROOT}/${password_file}"
  fi
  if [[ -f "${password_file}" ]]; then
    perl -0pe 's/\r?\n\z//' "${password_file}"
  fi
}

if [[ -n "${STOCK_REMOTE_PASSWORD_FILE}" ]]; then
  STOCK_REMOTE_PASSWORD="$(read_password_file "${STOCK_REMOTE_PASSWORD_FILE}")"
fi

remote_quote() {
  printf '%q' "$1"
}

run_ssh() {
  local remote_command="$1"
  local ssh_target="${STOCK_REMOTE_USER}@${STOCK_REMOTE_HOST}"

  if [[ -z "${STOCK_REMOTE_PASSWORD}" ]]; then
    ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=2 -o LogLevel=ERROR -p "${STOCK_REMOTE_PORT}" "${ssh_target}" "${remote_command}"
    return
  fi

  if command -v sshpass >/dev/null 2>&1; then
    SSHPASS="${STOCK_REMOTE_PASSWORD}" sshpass -e ssh \
      -o StrictHostKeyChecking=no \
      -o ConnectTimeout=20 \
      -o ServerAliveInterval=15 \
      -o ServerAliveCountMax=2 \
      -o LogLevel=ERROR \
      -p "${STOCK_REMOTE_PORT}" \
      "${ssh_target}" \
      "${remote_command}"
    return
  fi

  REMOTE_PORT="${STOCK_REMOTE_PORT}" \
  REMOTE_TARGET="${ssh_target}" \
  REMOTE_PASSWORD="${STOCK_REMOTE_PASSWORD}" \
  REMOTE_COMMAND="${remote_command}" \
expect <<'EOF'
set timeout 60
spawn -noecho ssh -o LogLevel=ERROR -p $env(REMOTE_PORT) $env(REMOTE_TARGET) $env(REMOTE_COMMAND)
expect {
  -re "(?i)are you sure you want to continue connecting" {
    send -- "yes\r"
    exp_continue
  }
  -re "(?i)assword:" {
    send -- "$env(REMOTE_PASSWORD)\r"
    exp_continue
  }
  timeout {
    exit 124
  }
  eof
}
catch wait result
exit [lindex $result 3]
EOF
}

run_scp() {
  local remote_path="$1"
  local local_path="$2"
  local ssh_target="${STOCK_REMOTE_USER}@${STOCK_REMOTE_HOST}"

  if [[ -z "${STOCK_REMOTE_PASSWORD}" ]]; then
    scp -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=2 -o LogLevel=ERROR -P "${STOCK_REMOTE_PORT}" -p "${ssh_target}:${remote_path}" "${local_path}"
    return
  fi

  if command -v sshpass >/dev/null 2>&1; then
    SSHPASS="${STOCK_REMOTE_PASSWORD}" sshpass -e scp \
      -o StrictHostKeyChecking=no \
      -o ConnectTimeout=20 \
      -o ServerAliveInterval=15 \
      -o ServerAliveCountMax=2 \
      -o LogLevel=ERROR \
      -P "${STOCK_REMOTE_PORT}" \
      -p \
      "${ssh_target}:${remote_path}" \
      "${local_path}"
    return
  fi

  REMOTE_PORT="${STOCK_REMOTE_PORT}" \
  REMOTE_TARGET="${ssh_target}" \
  REMOTE_PASSWORD="${STOCK_REMOTE_PASSWORD}" \
  REMOTE_PATH="${remote_path}" \
  LOCAL_PATH="${local_path}" \
expect <<'EOF'
set timeout 300
spawn -noecho scp -o LogLevel=ERROR -P $env(REMOTE_PORT) -p "$env(REMOTE_TARGET):$env(REMOTE_PATH)" $env(LOCAL_PATH)
expect {
  -re "(?i)are you sure you want to continue connecting" {
    send -- "yes\r"
    exp_continue
  }
  -re "(?i)assword:" {
    send -- "$env(REMOTE_PASSWORD)\r"
    exp_continue
  }
  timeout {
    exit 124
  }
  eof
}
catch wait result
exit [lindex $result 3]
EOF
}

date_compact() {
  printf '%s' "$1" | tr -d '-'
}

date_offset() {
  local date_text="$1"
  local offset_days="$2"
  python3 - "$date_text" "$offset_days" <<'PY'
from datetime import date, timedelta
import sys

base = date.fromisoformat(sys.argv[1])
print((base + timedelta(days=int(sys.argv[2]))).isoformat())
PY
}

default_target_date() {
  python3 - <<'PY'
from datetime import date, timedelta
print((date.today() - timedelta(days=1)).isoformat())
PY
}

latest_remote_stock() {
  local remote_dir="$1"
  local yyyymmdd="$2"
  local remote_dir_q pattern_q
  remote_dir_q="$(remote_quote "${remote_dir}")"
  pattern_q="$(remote_quote "estoque_${yyyymmdd}*.csv")"

  run_ssh "if [ -d ${remote_dir_q} ]; then find ${remote_dir_q} -maxdepth 1 -type f -name ${pattern_q} -exec stat -c '%W	%Y	%s	%n' {} \\; 2>/dev/null | awk -F '\t' '{ord=\$1; if (ord <= 0) ord=\$2; print ord \"\t\" \$2 \"\t\" \$3 \"\t\" \$4}' | sort -k1,1nr -k2,2nr | head -1; fi"
}

fetch_for_date() {
  local label="$1"
  local date_text="$2"
  local remote_dir="$3"
  local yyyymmdd
  local listing
  local remote_path size dest tmp
  yyyymmdd="$(date_compact "${date_text}")"

  log "Procurando estoque ${label} (${date_text}) em ${STOCK_REMOTE_USER}@${STOCK_REMOTE_HOST}:${remote_dir}"
  listing="$(latest_remote_stock "${remote_dir}" "${yyyymmdd}")"
  if [[ -z "${listing}" ]]; then
    log "Nenhum arquivo estoque_${yyyymmdd}*.csv encontrado em ${remote_dir}"
    return 1
  fi

  remote_path="$(printf '%s\n' "${listing}" | awk -F '\t' '{print $4}')"
  size="$(printf '%s\n' "${listing}" | awk -F '\t' '{print $3}')"
  dest="${LOCAL_INBOX}/$(basename "${remote_path}")"

  if [[ -f "${dest}" ]]; then
    local local_size
    local_size="$(wc -c < "${dest}" | tr -d ' ')"
    if [[ "${local_size}" == "${size}" ]]; then
      log "Arquivo ja existe com mesmo tamanho: ${dest}"
      return 0
    fi
  fi

  tmp="${dest}.part.$$"
  log "Baixando ${remote_path} -> ${dest}"
  run_scp "${remote_path}" "${tmp}"
  mv -f "${tmp}" "${dest}"
  log "Arquivo recebido: ${dest}"
}

fetch_for_date_with_fallback() {
  local label="$1"
  local date_text="$2"
  local primary_dir="$3"
  local fallback_dir="$4"

  if fetch_for_date "${label}" "${date_text}" "${primary_dir}"; then
    return 0
  fi

  if [[ "${fallback_dir}" != "${primary_dir}" ]]; then
    log "Tentando estoque ${label} (${date_text}) na pasta alternativa: ${fallback_dir}"
    fetch_for_date "${label}" "${date_text}" "${fallback_dir}"
    return
  fi

  return 1
}

TARGET_DATE=""
INCLUDE_PREVIOUS=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --date)
      TARGET_DATE="$2"
      shift 2
      ;;
    --no-previous)
      INCLUDE_PREVIOUS=0
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Opcao desconhecida: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "${TARGET_DATE}" ]]; then
  TARGET_DATE="$(default_target_date)"
fi

if [[ ! "${TARGET_DATE}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "--date deve estar no formato YYYY-MM-DD" >&2
  exit 1
fi

log "Iniciando busca de estoque oficial Pleno"
log "Entrada local: ${LOCAL_INBOX}"
failures=0

if [[ "${INCLUDE_PREVIOUS}" -eq 1 ]]; then
  PREVIOUS_DATE="$(date_offset "${TARGET_DATE}" -1)"
  fetch_for_date_with_fallback "anterior" "${PREVIOUS_DATE}" "${STOCK_PREVIOUS_DIR}" "${STOCK_CURRENT_DIR}" || failures=$((failures + 1))
fi

fetch_for_date_with_fallback "fechamento" "${TARGET_DATE}" "${STOCK_CURRENT_DIR}" "${STOCK_PREVIOUS_DIR}" || failures=$((failures + 1))

if [[ "${failures}" -gt 0 ]]; then
  log "Busca de estoque finalizada com ${failures} erro(s)"
  exit 1
fi

log "Busca de estoque finalizada"
