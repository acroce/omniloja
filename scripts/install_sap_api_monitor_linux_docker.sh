#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT_DIR"

NOC_CONTAINER_NAME="${NOC_CONTAINER_NAME:-noc-pleno-audit-web}"
NOC_WEB_PORT="${NOC_WEB_PORT:-8095}"
NOC_COMPOSE_PROJECT="${NOC_COMPOSE_PROJECT:-noc-pleno}"
export NOC_CONTAINER_NAME NOC_WEB_PORT NOC_COMPOSE_PROJECT COMPOSE_PROJECT_NAME="$NOC_COMPOSE_PROJECT"

if [ "$(id -u)" -ne 0 ] && [ "${NOC_INSTALL_NO_SUDO:-0}" != "1" ]; then
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

DOCKER="$(command -v docker)"
if ! docker ps >/dev/null 2>&1; then
  echo "Nao consegui acessar o Docker em /var/run/docker.sock." >&2
  echo "Verifique se o servico Docker esta rodando: systemctl status docker" >&2
  echo "Se o Docker estiver parado, rode: sudo systemctl start docker" >&2
  exit 1
fi

if $DOCKER compose version >/dev/null 2>&1; then
  COMPOSE="$DOCKER compose"
elif command -v docker-compose >/dev/null 2>&1; then
  if docker-compose ps >/dev/null 2>&1; then
    COMPOSE="docker-compose"
  elif command -v sudo >/dev/null 2>&1 && sudo docker-compose ps >/dev/null 2>&1; then
    COMPOSE="sudo docker-compose"
  else
    echo "Docker Compose encontrado, mas sem permissao para acessar o Docker." >&2
    exit 1
  fi
else
  echo "Docker Compose nao encontrado nesta maquina." >&2
  exit 1
fi

if [ ! -f ".env" ]; then
  echo "Arquivo .env nao encontrado em $ROOT_DIR." >&2
  exit 1
fi

mkdir -p outputs/pleno_business_monitor/logs

$COMPOSE -p "$NOC_COMPOSE_PROJECT" -f docker-compose.audit.yml -f docker-compose.audit-linux.yml up -d --build pleno-audit-web

if [ -x "$ROOT_DIR/scripts/install_noc_monitoring_linux_cron.sh" ]; then
  NOC_DOCKER_COMMAND="$DOCKER" "$ROOT_DIR/scripts/install_noc_monitoring_linux_cron.sh"
fi

echo "Monitor publicado em http://0.0.0.0:$NOC_WEB_PORT"
echo "Container: $NOC_CONTAINER_NAME"
echo "Projeto Docker Compose: $NOC_COMPOSE_PROJECT"
echo "Coletas automaticas: APIs SAP via SSH e notas/check-in a cada 10 minutos no container."
echo "Coletas NOC Pleno: promocoes/precos, pedidos, estoque RELEX, recursos e retificacao RET pela crontab Linux."
