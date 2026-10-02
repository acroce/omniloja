#!/usr/bin/env bash
# Publica o robo de Prevencao e Perdas como uma pilha Docker isolada no Linux.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE="${PREV_PERDAS_REMOTE:-dia-brasil@10.106.111.48}"
REMOTE_DIR="${PREV_PERDAS_REMOTE_DIR:-/home/dia-brasil/prevencao-perdas}"
PROJECT="${PREV_PERDAS_DOCKER_PROJECT:-prevencao-perdas}"
PORT="${PREV_PERDAS_PORT:-8096}"
SSH_OPTS=(${PREV_PERDAS_SSH_OPTS:-})
STAMP="$(date +%Y%m%d_%H%M%S)"
ARCHIVE="$(mktemp "${TMPDIR:-/tmp}/prevencao-perdas-docker-${STAMP}.XXXXXX.tgz")"
STAGE="/tmp/prevencao-perdas-docker-${STAMP}"

cleanup() { rm -f "$ARCHIVE"; }
trap cleanup EXIT
cd "$ROOT"

tar -czf "$ARCHIVE" \
  package.json \
  audit-web \
  scripts/prevencao-perdas-lote.mjs \
  scripts/recheck_prevencao_timeout_urls.mjs \
  scripts/prevencao_perdas_status.py \
  scripts/run-prevencao-perdas-cron.sh \
  docker/prevencao-perdas-entrypoint.sh \
  Dockerfile.prevencao-perdas \
  docker-compose.prevencao-perdas.yml \
  .env

echo "[1/4] Enviando a pilha Docker de Prevencao e Perdas..."
ssh "${SSH_OPTS[@]}" "$REMOTE" "mkdir -p '$REMOTE_DIR' && rm -rf '$STAGE' && mkdir -p '$STAGE'"
scp "${SSH_OPTS[@]}" "$ARCHIVE" "${REMOTE}:${STAGE}/publicacao.tgz"

echo "[2/4] Validando e atualizando arquivos..."
ssh "${SSH_OPTS[@]}" "$REMOTE" "REMOTE_DIR='$REMOTE_DIR' STAGE='$STAGE' PROJECT='$PROJECT' PORT='$PORT' STAMP='$STAMP' bash -s" <<'REMOTE_SCRIPT'
set -euo pipefail
cd "$REMOTE_DIR"
tar -xzf "$STAGE/publicacao.tgz" -C "$STAGE"

python3 -m py_compile "$STAGE/scripts/prevencao_perdas_status.py"
node --check "$STAGE/audit-web/server.mjs"
node --check "$STAGE/audit-web/public/prevencao-perdas.js"
node --check "$STAGE/scripts/recheck_prevencao_timeout_urls.mjs"

BACKUP="$REMOTE_DIR/outputs/prevencao_perdas/publicacoes/docker-$STAMP"
mkdir -p "$BACKUP"
for item in audit-web scripts docker Dockerfile.prevencao-perdas docker-compose.prevencao-perdas.yml package.json .env; do
  if [[ -e "$item" ]]; then cp -a "$item" "$BACKUP/"; fi
done

mkdir -p scripts docker outputs/prevencao_perdas .cache/prevencao-perdas
cp -a "$STAGE/audit-web" "$STAGE/package.json" "$STAGE/Dockerfile.prevencao-perdas" "$STAGE/docker-compose.prevencao-perdas.yml" .
cp -a "$STAGE/scripts/prevencao-perdas-lote.mjs" "$STAGE/scripts/recheck_prevencao_timeout_urls.mjs" "$STAGE/scripts/prevencao_perdas_status.py" "$STAGE/scripts/run-prevencao-perdas-cron.sh" scripts/
cp -a "$STAGE/docker/prevencao-perdas-entrypoint.sh" docker/
cp -a "$STAGE/.env" .env

chmod +x scripts/run-prevencao-perdas-cron.sh docker/prevencao-perdas-entrypoint.sh

if docker compose version >/dev/null 2>&1; then COMPOSE='docker compose'; else COMPOSE='docker-compose'; fi

echo "[3/4] Construindo imagem Docker..."
$COMPOSE -p "$PROJECT" -f docker-compose.prevencao-perdas.yml build prevencao-perdas
$COMPOSE -p "$PROJECT" -f docker-compose.prevencao-perdas.yml up -d --remove-orphans prevencao-perdas

for attempt in {1..30}; do
  if curl -fsS "http://127.0.0.1:${PORT}/prevencao-perdas.html" >/dev/null; then
    $COMPOSE -p "$PROJECT" -f docker-compose.prevencao-perdas.yml ps
    rm -rf "$STAGE"
    exit 0
  fi
  sleep 2
done

echo "Container nao respondeu na porta ${PORT}. Backup em ${BACKUP}." >&2
$COMPOSE -p "$PROJECT" -f docker-compose.prevencao-perdas.yml logs --tail=80 prevencao-perdas >&2 || true
exit 1
REMOTE_SCRIPT

echo "[4/4] Confirmando acesso externo..."
curl -fsS "http://10.106.111.48:${PORT}/prevencao-perdas.html" >/dev/null
echo "Docker publicado: http://10.106.111.48:${PORT}/prevencao-perdas.html"
