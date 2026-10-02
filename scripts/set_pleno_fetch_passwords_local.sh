#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIG_FILE="${PROJECT_ROOT}/config/pleno_fetch_remote.env"
PACKAGE_PASSWORD_FILE="${PROJECT_ROOT}/config/.pleno_package_password"
STOCK_PASSWORD_FILE="${PROJECT_ROOT}/config/.pleno_stock_password"

read_secret() {
  local prompt="$1"
  local value

  printf '%s' "${prompt}" >&2
  IFS= read -rs value
  printf '\n' >&2
  printf '%s' "${value}"
}

replace_or_append() {
  local key="$1"
  local value="$2"
  local file="$3"

  if grep -q "^${key}=" "${file}"; then
    perl -0pi -e "s|^${key}=.*$|${key}=\"${value}\"|m" "${file}"
  else
    printf '\n%s="%s"\n' "${key}" "${value}" >> "${file}"
  fi
}

package_password="$(read_secret 'Senha do servidor de movimentos/pacotes: ')"
stock_password="$(read_secret 'Senha do servidor de estoque oficial: ')"

printf '%s' "${package_password}" > "${PACKAGE_PASSWORD_FILE}"
printf '%s' "${stock_password}" > "${STOCK_PASSWORD_FILE}"
chmod 600 "${PACKAGE_PASSWORD_FILE}" "${STOCK_PASSWORD_FILE}"

replace_or_append "PACKAGE_REMOTE_PASSWORD" "" "${CONFIG_FILE}"
replace_or_append "STOCK_REMOTE_PASSWORD" "" "${CONFIG_FILE}"
replace_or_append "PACKAGE_REMOTE_PASSWORD_FILE" "config/.pleno_package_password" "${CONFIG_FILE}"
replace_or_append "STOCK_REMOTE_PASSWORD_FILE" "config/.pleno_stock_password" "${CONFIG_FILE}"
chmod 600 "${CONFIG_FILE}"

echo "Senhas salvas em arquivos locais protegidos."
