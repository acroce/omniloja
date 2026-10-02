#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

PLENO_STOCK_AUDIT_CONTAINER_NAME="${PLENO_STOCK_AUDIT_CONTAINER_NAME:-pleno-audit-web}"
PLENO_STOCK_AUDIT_WEB_PORT="${PLENO_STOCK_AUDIT_WEB_PORT:-8094}"
PLENO_STOCK_AUDIT_COMPOSE_PROJECT="${PLENO_STOCK_AUDIT_COMPOSE_PROJECT:-pleno-stock-audit}"
export NOC_CONTAINER_NAME="$PLENO_STOCK_AUDIT_CONTAINER_NAME"
export NOC_WEB_PORT="$PLENO_STOCK_AUDIT_WEB_PORT"
export COMPOSE_PROJECT_NAME="$PLENO_STOCK_AUDIT_COMPOSE_PROJECT"
export PLENO_STOCK_AUDIT_CONTAINER_NAME

if [ "$(id -u)" -ne 0 ] && [ "${PLENO_STOCK_AUDIT_INSTALL_NO_SUDO:-0}" != "1" ]; then
  if command -v sudo >/dev/null 2>&1; then
    echo "Relancando instalador com sudo para acessar o Docker."
    exec sudo -E sh "$0" "$@"
  fi
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker nao encontrado nesta maquina." >&2
  exit 1
fi

if command -v systemctl >/dev/null 2>&1 && [ "$(id -u)" -eq 0 ]; then
  if systemctl list-unit-files cron.service >/dev/null 2>&1; then
    systemctl enable --now cron.service >/dev/null 2>&1 || echo "Aviso: nao consegui ativar cron.service automaticamente."
  elif systemctl list-unit-files crond.service >/dev/null 2>&1; then
    systemctl enable --now crond.service >/dev/null 2>&1 || echo "Aviso: nao consegui ativar crond.service automaticamente."
  fi
fi

if ! docker ps >/dev/null 2>&1; then
  echo "Nao consegui acessar o Docker em /var/run/docker.sock." >&2
  echo "Verifique se o servico Docker esta rodando: systemctl status docker" >&2
  echo "Se o Docker estiver parado, rode: sudo systemctl start docker" >&2
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
else
  echo "Docker Compose nao encontrado nesta maquina." >&2
  exit 1
fi

if [ ! -f "config/pleno_fetch_remote.env" ]; then
  echo "Arquivo config/pleno_fetch_remote.env nao encontrado." >&2
  echo "Copie config/pleno_fetch_remote.env.example para config/pleno_fetch_remote.env e ajuste os dois servidores." >&2
  exit 1
fi

mkdir -p \
  outputs/recebidos_servidor \
  outputs/pleno_stock_audit \
  outputs/pleno_stock_snapshots \
  outputs/pleno_stock_audit_excel \
  outputs/pleno_stock_official \
  outputs/pleno_stock_official_index \
  outputs/logs

$COMPOSE -p "$PLENO_STOCK_AUDIT_COMPOSE_PROJECT" -f "$ROOT_DIR/docker-compose.audit.yml" up -d --build pleno-audit-web

PLENO_STOCK_AUDIT_DOCKER_COMMAND="docker" "$ROOT_DIR/scripts/install_pleno_stock_audit_linux_cron.sh"

echo "Auditoria de estoque publicada em http://0.0.0.0:$PLENO_STOCK_AUDIT_WEB_PORT"
echo "Container: $PLENO_STOCK_AUDIT_CONTAINER_NAME"
echo "Projeto Docker Compose: $PLENO_STOCK_AUDIT_COMPOSE_PROJECT"
echo "Entrada monitorada: $ROOT_DIR/outputs/recebidos_servidor"
echo "Coleta local: estoque 01:00 e auditoria de movimentos 01:30 via MySQL do Pleno."
