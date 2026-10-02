#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
if [ -z "${PACKAGE:-}" ]; then
  PACKAGE="$(ls -1t "$ROOT_DIR"/noc-pleno-linux-*.tar.gz 2>/dev/null | head -1)"
fi
REMOTE_HOST="${REMOTE_HOST:-192.168.7.15}"
REMOTE_USER="${REMOTE_USER:-acroce}"
REMOTE_BASE="${REMOTE_BASE:-/home/acroce/Downloads}"
REMOTE_DIR="${REMOTE_DIR:-$REMOTE_BASE/tabelas-pleno-vamos-criar-uma-conex}"
REMOTE_PACKAGE="/tmp/$(basename "$PACKAGE")"
NOC_CONTAINER_NAME="${NOC_CONTAINER_NAME:-noc-pleno-audit-web}"
NOC_WEB_PORT="${NOC_WEB_PORT:-8094}"
NOC_COMPOSE_PROJECT="${NOC_COMPOSE_PROJECT:-noc-pleno}"

if [ ! -f "$PACKAGE" ]; then
  echo "Pacote nao encontrado: $PACKAGE" >&2
  exit 1
fi

if ! command -v expect >/dev/null 2>&1; then
  echo "expect nao encontrado nesta maquina; preciso dele para enviar senha SSH/sudo sem gravar no script." >&2
  exit 1
fi

if [ -z "${SAP_MONITOR_DEPLOY_PASSWORD:-}" ]; then
  printf "Senha SSH/sudo de %s@%s: " "$REMOTE_USER" "$REMOTE_HOST" >&2
  stty -echo
  read -r SAP_MONITOR_DEPLOY_PASSWORD
  stty echo
  printf "\n" >&2
fi
export SAP_MONITOR_DEPLOY_PASSWORD

echo "Enviando pacote para $REMOTE_USER@$REMOTE_HOST:$REMOTE_PACKAGE"
PACKAGE="$PACKAGE" REMOTE_TARGET="$REMOTE_USER@$REMOTE_HOST:$REMOTE_PACKAGE" expect <<'EXPECT'
set timeout 120
spawn scp -o StrictHostKeyChecking=accept-new "$env(PACKAGE)" "$env(REMOTE_TARGET)"
expect {
  -re "(?i)are you sure" { send "yes\r"; exp_continue }
  -re "(?i)password:" { send -- "$env(SAP_MONITOR_DEPLOY_PASSWORD)\r"; exp_continue }
  eof {
    catch wait result
    exit [lindex $result 3]
  }
  timeout { exit 124 }
}
EXPECT

REMOTE_DEPLOY_SCRIPT="/tmp/deploy_sap_api_monitor_$(date +%Y%m%d_%H%M%S).sh"
REMOTE_SCRIPT=$(cat <<'REMOTE_SH'
set -eu

echo "Host remoto: $(hostname)"
echo "Usuario remoto: $(id -un)"
echo "Diretorio alvo: __REMOTE_DIR__"
echo "Container alvo: __NOC_CONTAINER_NAME__"
echo "Porta alvo: __NOC_WEB_PORT__"

mkdir -p "__REMOTE_BASE__"

if [ -d "__REMOTE_DIR__/outputs/pleno_business_monitor" ]; then
  BACKUP="__REMOTE_DIR__/outputs/pleno_business_monitor.backup_$(date +%Y%m%d_%H%M%S)"
  echo "Backup dos JSONs atuais em: $BACKUP"
  cp -a "__REMOTE_DIR__/outputs/pleno_business_monitor" "$BACKUP"
fi

tar -xzf "__REMOTE_PACKAGE__" -C "__REMOTE_BASE__"
cd "__REMOTE_DIR__"
chmod +x scripts/install_sap_api_monitor_linux_docker.sh

echo "Validando build context do NOC:"
test -f audit-web/public/operacional-monitor.html
test -f audit-web/public/operacional-monitor.js
test -f audit-web/public/app.js

echo "Containers antes do deploy:"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' || true

export NOC_CONTAINER_NAME="__NOC_CONTAINER_NAME__"
export NOC_WEB_PORT="__NOC_WEB_PORT__"
export NOC_COMPOSE_PROJECT="__NOC_COMPOSE_PROJECT__"
sh scripts/install_sap_api_monitor_linux_docker.sh

echo "Validando pagina operacional:"
docker exec "__NOC_CONTAINER_NAME__" test -f /app/audit-web/public/operacional-monitor.html
if command -v curl >/dev/null 2>&1; then
  curl -fsS "http://127.0.0.1:__NOC_WEB_PORT__/operacional-monitor.html" >/dev/null \
    && echo "Pagina operacional OK." \
    || echo "Aviso: pagina operacional ainda nao respondeu via HTTP local."
  for path in \
    /api/business-monitor/pedidos \
    /api/business-monitor/promopreco \
    /api/business-monitor/notas-rejeitadas \
    /api/business-monitor/estoque-relex \
    /api/business-monitor/retificacao-ret \
    /api/business-monitor/devolucao-as400 \
    /api/business-monitor/mercadoria-filial \
    /api/business-monitor/sg-estoque-custo \
    /api/business-monitor/pdv-processes \
    /api/business-monitor/pdv-queue \
    /api/business-monitor/sap-api \
    /api/business-monitor/sap-api/routing \
    /api/business-monitor/sap-api/google-chat \
    /api/business-monitor/checkin-notas; do
    curl -fsS "http://127.0.0.1:__NOC_WEB_PORT__${path}" >/dev/null
  done
  echo "Endpoints business-monitor OK."
fi

echo "Containers depois do deploy:"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
echo "URL operacional: http://__REMOTE_HOST__:__NOC_WEB_PORT__/operacional-monitor.html"
REMOTE_SH
)

REMOTE_SCRIPT="${REMOTE_SCRIPT//__REMOTE_HOST__/$REMOTE_HOST}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//__REMOTE_DIR__/$REMOTE_DIR}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//__REMOTE_BASE__/$REMOTE_BASE}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//__REMOTE_PACKAGE__/$REMOTE_PACKAGE}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//__NOC_CONTAINER_NAME__/$NOC_CONTAINER_NAME}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//__NOC_WEB_PORT__/$NOC_WEB_PORT}"
REMOTE_SCRIPT="${REMOTE_SCRIPT//__NOC_COMPOSE_PROJECT__/$NOC_COMPOSE_PROJECT}"

LOCAL_REMOTE_SCRIPT="$(mktemp "${TMPDIR:-/tmp}/deploy-sap-api-monitor.XXXXXX.sh")"
trap 'rm -f "$LOCAL_REMOTE_SCRIPT"' EXIT
printf "%s\n" "$REMOTE_SCRIPT" > "$LOCAL_REMOTE_SCRIPT"

echo "Enviando script remoto temporario para $REMOTE_DEPLOY_SCRIPT"
LOCAL_REMOTE_SCRIPT="$LOCAL_REMOTE_SCRIPT" REMOTE_TARGET="$REMOTE_USER@$REMOTE_HOST:$REMOTE_DEPLOY_SCRIPT" expect <<'EXPECT'
set timeout 120
spawn scp -o StrictHostKeyChecking=accept-new "$env(LOCAL_REMOTE_SCRIPT)" "$env(REMOTE_TARGET)"
expect {
  -re "(?i)are you sure" { send "yes\r"; exp_continue }
  -re "(?i)password:" { send -- "$env(SAP_MONITOR_DEPLOY_PASSWORD)\r"; exp_continue }
  eof {
    catch wait result
    exit [lindex $result 3]
  }
  timeout { exit 124 }
}
EXPECT

echo "Executando deploy remoto sem tocar nos outros containers."
REMOTE_TARGET="$REMOTE_USER@$REMOTE_HOST" REMOTE_DEPLOY_SCRIPT="$REMOTE_DEPLOY_SCRIPT" expect <<'EXPECT'
set timeout 600
spawn ssh -tt -o StrictHostKeyChecking=accept-new "$env(REMOTE_TARGET)" "sh '$env(REMOTE_DEPLOY_SCRIPT)'; status=\$?; rm -f '$env(REMOTE_DEPLOY_SCRIPT)'; exit \$status"
expect {
  -re "(?i)are you sure" { send "yes\r"; exp_continue }
  -re "(?i)password:" { send -- "$env(SAP_MONITOR_DEPLOY_PASSWORD)\r"; exp_continue }
  -re "(?i)\\\[sudo\\\].*password.*:" { send -- "$env(SAP_MONITOR_DEPLOY_PASSWORD)\r"; exp_continue }
  -re "(?i)senha.*:" { send -- "$env(SAP_MONITOR_DEPLOY_PASSWORD)\r"; exp_continue }
  -re "(?i)password for .*:" { send -- "$env(SAP_MONITOR_DEPLOY_PASSWORD)\r"; exp_continue }
  eof {
    catch wait result
    exit [lindex $result 3]
  }
  timeout { exit 124 }
}
EXPECT
