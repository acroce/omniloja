#!/usr/bin/env bash
# Publica somente o robo e o painel de Cofre Inteligente no Linux.
# Nao executa comandos Docker e nao altera outros servicos da maquina.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE="${TESOURARIA_REMOTE:-dia-brasil@10.106.111.48}"
REMOTE_DIR="${TESOURARIA_REMOTE_DIR:-/home/dia-brasil/cofre-inteligente}"
PORT="${TESOURARIA_PORT:-8095}"
STAMP="$(date +%Y%m%d_%H%M%S)"
ARCHIVE="$(mktemp "${TMPDIR:-/tmp}/cofre-inteligente-${STAMP}.XXXXXX.tgz")"
STAGE="/tmp/cofre-inteligente-${STAMP}"

cleanup() { rm -f "$ARCHIVE"; }
trap cleanup EXIT

cd "$ROOT"

FILES=(
  "scripts/tesouraria_cofre_pleno.py"
  "scripts/tesouraria_cofre_status.py"
  "scripts/tesouraria-cofre-lote.mjs"
  "audit-web/server.mjs"
  "audit-web/public/tesouraria-cofre-inteligente.html"
  "audit-web/public/tesouraria-cofre-inteligente.js"
  "audit-web/public/styles.css"
)

echo "[1/4] Empacotando arquivos da Tesouraria..."
tar -czf "$ARCHIVE" "${FILES[@]}"

echo "[2/4] Enviando para ${REMOTE}..."
ssh "$REMOTE" "rm -rf '$STAGE' && mkdir -p '$STAGE'"
scp "$ARCHIVE" "${REMOTE}:${STAGE}/publicacao.tgz"

echo "[3/4] Validando, publicando e reiniciando somente o painel ${PORT}..."
ssh "$REMOTE" "REMOTE_DIR='$REMOTE_DIR' STAGE='$STAGE' PORT='$PORT' STAMP='$STAMP' bash -s" <<'REMOTE_SCRIPT'
set -euo pipefail

cd "$REMOTE_DIR"
tar -xzf "$STAGE/publicacao.tgz" -C "$STAGE"

python3 -m py_compile "$STAGE/scripts/tesouraria_cofre_pleno.py" "$STAGE/scripts/tesouraria_cofre_status.py"
node --check "$STAGE/audit-web/server.mjs"
node --check "$STAGE/audit-web/public/tesouraria-cofre-inteligente.js"

BACKUP="$REMOTE_DIR/outputs/tesouraria_cofre_inteligente/publicacoes/$STAMP"
mkdir -p "$BACKUP/scripts" "$BACKUP/audit-web/public"

for file in \
  scripts/tesouraria_cofre_pleno.py \
  scripts/tesouraria_cofre_status.py \
  scripts/tesouraria-cofre-lote.mjs \
  audit-web/server.mjs \
  audit-web/public/tesouraria-cofre-inteligente.html \
  audit-web/public/tesouraria-cofre-inteligente.js \
  audit-web/public/styles.css; do
  cp "$file" "$BACKUP/$file"
  cp "$STAGE/$file" "$file"
done

# Preenche a fila local uma única vez na publicacao. Depois disso, somente o
# robô atualiza esse cache no inicio de cada rodada; o painel nunca consulta o Pleno.
python3 scripts/tesouraria_cofre_pleno.py \
  --db outputs/tesouraria_cofre_inteligente/acompanhamento.sqlite \
  refresh-open-transfers > "$BACKUP/fila-inicial.json"

# Limita o reinicio ao processo do usuario atual; processos de outros usuarios e Docker nao sao afetados.
PIDS="$(pgrep -u "$(id -u)" -f '^node audit-web/server.mjs$' || true)"
if [[ -n "$PIDS" ]]; then
  kill $PIDS
  sleep 1
fi

nohup env AUDIT_WEB_HOST=0.0.0.0 AUDIT_WEB_PORT="$PORT" node audit-web/server.mjs \
  > outputs/tesouraria_cofre_inteligente/audit-web.log 2>&1 &

for attempt in {1..15}; do
  if curl -fsS "http://127.0.0.1:${PORT}/tesouraria-cofre-inteligente.html" >/dev/null; then
    echo "Painel ativo na porta ${PORT}. Backup: ${BACKUP}"
    rm -rf "$STAGE"
    exit 0
  fi
  sleep 1
done

echo "O painel nao respondeu apos o reinicio. Backup preservado em ${BACKUP}." >&2
exit 1
REMOTE_SCRIPT

echo "[4/4] Confirmando acesso externo..."
curl -fsS "http://10.106.111.48:${PORT}/tesouraria-cofre-inteligente.html" >/dev/null
echo "Publicacao concluida: http://10.106.111.48:${PORT}/tesouraria-cofre-inteligente.html"
