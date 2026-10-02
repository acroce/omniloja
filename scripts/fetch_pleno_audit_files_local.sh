#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${PLENO_FETCH_CONFIG:-${PROJECT_ROOT}/config/pleno_fetch_remote.env}"

if [[ -f "${CONFIG_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${CONFIG_FILE}"
fi

REMOTE_USER="${REMOTE_USER:-root}"
REMOTE_HOST="${REMOTE_HOST:-BRHDCVLNX027}"
REMOTE_PORT="${REMOTE_PORT:-22}"
REMOTE_PASSWORD="${REMOTE_PASSWORD:-}"

PACKAGE_REMOTE_USER="${PACKAGE_REMOTE_USER:-${REMOTE_USER}}"
PACKAGE_REMOTE_HOST="${PACKAGE_REMOTE_HOST:-${REMOTE_HOST}}"
PACKAGE_REMOTE_PORT="${PACKAGE_REMOTE_PORT:-${REMOTE_PORT}}"
PACKAGE_REMOTE_PASSWORD="${PACKAGE_REMOTE_PASSWORD:-${REMOTE_PASSWORD}}"
PACKAGE_REMOTE_PASSWORD_FILE="${PACKAGE_REMOTE_PASSWORD_FILE:-}"
PACKAGE_REMOTE_DIRS="${PACKAGE_REMOTE_DIRS:-${REMOTE_PACKAGE_DIRS:-/dev/audit_lojas/outputs/pleno_stock_audit_packages /dev/audit_lojas/outputs/pleno_stock_snapshot_packages}}"

STOCK_REMOTE_USER="${STOCK_REMOTE_USER:-${REMOTE_USER}}"
STOCK_REMOTE_HOST="${STOCK_REMOTE_HOST:-${REMOTE_HOST}}"
STOCK_REMOTE_PORT="${STOCK_REMOTE_PORT:-${REMOTE_PORT}}"
STOCK_REMOTE_PASSWORD="${STOCK_REMOTE_PASSWORD:-${REMOTE_PASSWORD}}"
STOCK_REMOTE_PASSWORD_FILE="${STOCK_REMOTE_PASSWORD_FILE:-}"
STOCK_REMOTE_DIRS="${STOCK_REMOTE_DIRS:-${REMOTE_STOCK_DIRS:-/dev/audit_lojas/outputs/pleno_stock_official /dev/audit_lojas/outputs/recebidos_servidor}}"

LOCAL_INBOX="${LOCAL_INBOX:-outputs/recebidos_servidor}"

if [[ "${LOCAL_INBOX}" != /* ]]; then
  LOCAL_INBOX="${PROJECT_ROOT}/${LOCAL_INBOX}"
fi

STATE_DIR="${PROJECT_ROOT}/outputs/.fetch_state"
STATE_FILE="${STATE_DIR}/pleno_remote_files.tsv"
LOG_DIR="${PROJECT_ROOT}/outputs/logs"

mkdir -p "${LOCAL_INBOX}" "${STATE_DIR}" "${LOG_DIR}"
touch "${STATE_FILE}"

read_password_file() {
  local password_file="$1"

  if [[ -z "${password_file}" ]]; then
    return 0
  fi

  if [[ "${password_file}" != /* ]]; then
    password_file="${PROJECT_ROOT}/${password_file}"
  fi

  if [[ -f "${password_file}" ]]; then
    perl -0pe 's/\r?\n\z//' "${password_file}"
  fi
}

if [[ -n "${PACKAGE_REMOTE_PASSWORD_FILE}" ]]; then
  PACKAGE_REMOTE_PASSWORD="$(read_password_file "${PACKAGE_REMOTE_PASSWORD_FILE}")"
fi

if [[ -n "${STOCK_REMOTE_PASSWORD_FILE}" ]]; then
  STOCK_REMOTE_PASSWORD="$(read_password_file "${STOCK_REMOTE_PASSWORD_FILE}")"
fi

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

remote_quote() {
  printf '%q' "$1"
}

run_ssh() {
  local remote_user="$1"
  local remote_host="$2"
  local remote_port="$3"
  local remote_password="$4"
  local remote_command="$5"
  local ssh_target="${remote_user}@${remote_host}"

  if [[ -z "${remote_password}" ]]; then
    ssh -o LogLevel=ERROR -p "${remote_port}" "${ssh_target}" "${remote_command}"
    return
  fi

  REMOTE_PORT="${remote_port}" \
  REMOTE_TARGET="${ssh_target}" \
  REMOTE_PASSWORD="${remote_password}" \
  REMOTE_COMMAND="${remote_command}" \
expect <<'EOF'
set timeout -1
spawn -noecho ssh -o LogLevel=ERROR -p $env(REMOTE_PORT) $env(REMOTE_TARGET) $env(REMOTE_COMMAND)
expect {
  -re "(?i)are you sure you want to continue connecting" {
    send -- "yes\r"
    exp_continue
  }
  -re "(?i)password:" {
    send -- "$env(REMOTE_PASSWORD)\r"
    exp_continue
  }
  eof
}
catch wait result
exit [lindex $result 3]
EOF
}

run_scp() {
  local remote_user="$1"
  local remote_host="$2"
  local remote_port="$3"
  local remote_password="$4"
  local remote_path="$5"
  local local_path="$6"
  local ssh_target="${remote_user}@${remote_host}"

  if [[ -z "${remote_password}" ]]; then
    scp -o LogLevel=ERROR -P "${remote_port}" -p "${ssh_target}:${remote_path}" "${local_path}"
    return
  fi

  REMOTE_PORT="${remote_port}" \
  REMOTE_TARGET="${ssh_target}" \
  REMOTE_PASSWORD="${remote_password}" \
  REMOTE_PATH="${remote_path}" \
  LOCAL_PATH="${local_path}" \
expect <<'EOF'
set timeout -1
spawn -noecho scp -o LogLevel=ERROR -P $env(REMOTE_PORT) -p "$env(REMOTE_TARGET):$env(REMOTE_PATH)" $env(LOCAL_PATH)
expect {
  -re "(?i)are you sure you want to continue connecting" {
    send -- "yes\r"
    exp_continue
  }
  -re "(?i)password:" {
    send -- "$env(REMOTE_PASSWORD)\r"
    exp_continue
  }
  eof
}
catch wait result
exit [lindex $result 3]
EOF
}

download_remote_file() {
  local remote_user="$1"
  local remote_host="$2"
  local remote_port="$3"
  local remote_password="$4"
  local remote_path="$5"
  local size="$6"
  local mtime="$7"
  local ssh_target="${remote_user}@${remote_host}"
  local signature="${ssh_target}:${remote_path}\t${size}\t${mtime}"
  local base tmp dest

  if grep -Fqx "${signature}" "${STATE_FILE}"; then
    return 0
  fi

  base="$(basename "${remote_path}")"
  tmp="${LOCAL_INBOX}/.${base}.part.$$"
  dest="${LOCAL_INBOX}/${base}"

  log "Baixando ${ssh_target}:${remote_path}"
  run_scp "${remote_user}" "${remote_host}" "${remote_port}" "${remote_password}" "${remote_path}" "${tmp}"
  mv -f "${tmp}" "${dest}"
  printf '%b\n' "${signature}" >> "${STATE_FILE}"
  log "Arquivo recebido: ${dest}"
}

scan_remote_dir() {
  local remote_user="$1"
  local remote_host="$2"
  local remote_port="$3"
  local remote_password="$4"
  local remote_dir="$5"
  local remote_dir_q
  local listing_file
  local detail
  remote_dir_q="$(remote_quote "${remote_dir}")"
  listing_file="$(mktemp "${LOCAL_INBOX}/.remote_listing.XXXXXX")"

  if ! run_ssh "${remote_user}" "${remote_host}" "${remote_port}" "${remote_password}" \
    "if [ -d ${remote_dir_q} ]; then find ${remote_dir_q} -maxdepth 1 -type f \\( -name '*.tar.gz' -o -name 'estoque_*.csv' \\) -printf '%p\t%s\t%T@\n'; fi" > "${listing_file}"; then
    detail="$(tail -5 "${listing_file}" | tr '\n' ' ' | sed 's/[[:space:]][[:space:]]*/ /g')"
    rm -f "${listing_file}"
    log "Erro ao listar ${remote_user}@${remote_host}:${remote_dir}"
    if [[ -n "${detail}" ]]; then
      log "Detalhe: ${detail}"
    fi
    return 1
  fi

  while IFS=$'\t' read -r remote_path size mtime; do
    [[ -n "${remote_path:-}" ]] || continue
    download_remote_file "${remote_user}" "${remote_host}" "${remote_port}" "${remote_password}" "${remote_path}" "${size}" "${mtime}"
  done < "${listing_file}"

  rm -f "${listing_file}"
}

main() {
  local package_target="${PACKAGE_REMOTE_USER}@${PACKAGE_REMOTE_HOST}"
  local stock_target="${STOCK_REMOTE_USER}@${STOCK_REMOTE_HOST}"
  local failures=0

  log "Iniciando busca Pleno"
  log "Servidor movimentos/pacotes: ${package_target}:${PACKAGE_REMOTE_PORT}"
  log "Servidor estoque oficial: ${stock_target}:${STOCK_REMOTE_PORT}"
  log "Entrada local: ${LOCAL_INBOX}"

  for remote_dir in ${PACKAGE_REMOTE_DIRS}; do
    if ! scan_remote_dir "${PACKAGE_REMOTE_USER}" "${PACKAGE_REMOTE_HOST}" "${PACKAGE_REMOTE_PORT}" "${PACKAGE_REMOTE_PASSWORD}" "${remote_dir}"; then
      failures=$((failures + 1))
    fi
  done

  for remote_dir in ${STOCK_REMOTE_DIRS}; do
    if ! scan_remote_dir "${STOCK_REMOTE_USER}" "${STOCK_REMOTE_HOST}" "${STOCK_REMOTE_PORT}" "${STOCK_REMOTE_PASSWORD}" "${remote_dir}"; then
      failures=$((failures + 1))
    fi
  done

  if [[ "${failures}" -gt 0 ]]; then
    log "Busca finalizada com ${failures} erro(s)"
    return 1
  fi

  log "Busca finalizada"
}

main "$@"
