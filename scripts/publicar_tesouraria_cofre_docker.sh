#!/usr/bin/env bash
# Publica o Cofre Inteligente como uma pilha Docker isolada no Linux.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE="${TESOURARIA_REMOTE:-dia-brasil@10.106.111.48}"
REMOTE_DIR="${TESOURARIA_REMOTE_DIR:-/home/dia-brasil/cofre-inteligente}"
PROJECT="${TESOURARIA_DOCKER_PROJECT:-tesouraria-cofre}"
PORT="${TESOURARIA_PORT:-8095}"
STAMP="$(date +%Y%m%d_%H%M%S)"
ARCHIVE="$(mktemp "${TMPDIR:-/tmp}/tesouraria-cofre-docker-${STAMP}.XXXXXX.tgz")"
STAGE="/tmp/tesouraria-cofre-docker-${STAMP}"

cleanup() { rm -f "$ARCHIVE"; }
trap cleanup EXIT
cd "$ROOT"

tar -czf "$ARCHIVE" package.json audit-web scripts docker Dockerfile.tesouraria-cofre docker-compose.tesouraria-cofre.yml .env.pleno-robo

echo "[1/4] Enviando a pilha Docker..."
ssh "$REMOTE" "rm -rf '$STAGE' && mkdir -p '$STAGE'"
scp "$ARCHIVE" "${REMOTE}:${STAGE}/publicacao.tgz"

echo "[2/4] Validando e atualizando arquivos..."
ssh "$REMOTE" "REMOTE_DIR='$REMOTE_DIR' STAGE='$STAGE' PROJECT='$PROJECT' PORT='$PORT' STAMP='$STAMP' bash -s" <<'REMOTE_SCRIPT'
set -euo pipefail
cd "$REMOTE_DIR"
tar -xzf "$STAGE/publicacao.tgz" -C "$STAGE"
python3 -m py_compile "$STAGE/scripts/tesouraria_cofre_pleno.py" "$STAGE/scripts/tesouraria_cofre_status.py"

BACKUP="$REMOTE_DIR/outputs/tesouraria_cofre_inteligente/publicacoes/docker-$STAMP"
mkdir -p "$BACKUP"
for item in audit-web scripts docker Dockerfile.tesouraria-cofre docker-compose.tesouraria-cofre.yml package.json .env.pleno-robo; do
  if [[ -e "$item" ]]; then cp -a "$item" "$BACKUP/"; fi
done
cp -a "$STAGE/audit-web" "$STAGE/scripts" "$STAGE/docker" "$STAGE/Dockerfile.tesouraria-cofre" "$STAGE/docker-compose.tesouraria-cofre.yml" "$STAGE/package.json" "$STAGE/.env.pleno-robo" .

mkdir -p outputs/tesouraria_cofre_inteligente .cache/tesouraria-cofre models

if docker compose version >/dev/null 2>&1; then COMPOSE='docker compose'; else COMPOSE='docker-compose'; fi

echo "[3/4] Construindo imagem Docker do Cofre Inteligente..."
$COMPOSE -p "$PROJECT" -f docker-compose.tesouraria-cofre.yml build cofre-inteligente

# Libera somente a porta do painel antigo desse mesmo usuario. Docker e demais usuarios nao sao tocados.
PIDS="$(pgrep -u "$(id -u)" -f '^node audit-web/server.mjs$' || true)"
if [[ -n "$PIDS" ]]; then kill $PIDS; fi

$COMPOSE -p "$PROJECT" -f docker-compose.tesouraria-cofre.yml up -d --remove-orphans cofre-inteligente

# A partir desta publicacao o cron e interno ao container. A remocao da linha
# antiga nao interrompe uma rodada do host que eventualmente ja esteja ativa.
if crontab -l 2>/dev/null | grep -q 'run-tesouraria-cofre-cron.sh'; then
  crontab -l | grep -v 'run-tesouraria-cofre-cron.sh' | crontab -
fi

for attempt in {1..30}; do
  if curl -fsS "http://127.0.0.1:${PORT}/tesouraria-cofre-inteligente.html" >/dev/null; then
    $COMPOSE -p "$PROJECT" -f docker-compose.tesouraria-cofre.yml ps
    rm -rf "$STAGE"
    exit 0
  fi
  sleep 2
done

echo "Container nao respondeu na porta ${PORT}. Backup em ${BACKUP}." >&2
$COMPOSE -p "$PROJECT" -f docker-compose.tesouraria-cofre.yml logs --tail=80 cofre-inteligente >&2 || true
exit 1
REMOTE_SCRIPT

echo "[4/4] Confirmando acesso externo..."
curl -fsS "http://10.106.111.48:${PORT}/tesouraria-cofre-inteligente.html" >/dev/null
echo "Docker publicado: http://10.106.111.48:${PORT}/tesouraria-cofre-inteligente.html"
