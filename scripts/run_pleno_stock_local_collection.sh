#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LOJAS_FILE="${LOJAS_FILE:-$PROJECT_DIR/config/pleno_stock_audit_lojas.txt}"
LOG_PREFIX="${LOG_PREFIX:-}"
ALL_LOJAS=0

usage() {
  cat <<'EOF'
Uso:
  scripts/run_pleno_stock_local_collection.sh estoque
  scripts/run_pleno_stock_local_collection.sh auditoria [--date YYYY-MM-DD]
  scripts/run_pleno_stock_local_collection.sh tudo [--date YYYY-MM-DD]

Roda no proprio Linux, usando o MySQL do Pleno:
  estoque   baixa o CSV oficial do Pleno em outputs/recebidos_servidor
  auditoria gera pacote diario de movimentos em outputs/recebidos_servidor
  tudo      roda estoque e auditoria em sequencia

Opcoes:
  --all-lojas       ignora o arquivo de lojas e coleta todas as lojas
  --date YYYY-MM-DD data da auditoria de movimentos
EOF
}

log() {
  printf '[%s] %s%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$LOG_PREFIX" "$*"
}

ACTION="${1:-}"
if [[ -z "$ACTION" || "$ACTION" == "--help" || "$ACTION" == "-h" ]]; then
  usage
  exit 0
fi
shift || true

DATE_ARG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --date)
      DATE_ARG="$2"
      shift 2
      ;;
    --all-lojas)
      ALL_LOJAS=1
      shift
      ;;
    *)
      echo "Opcao desconhecida: $1" >&2
      usage
      exit 1
      ;;
  esac
done

run_estoque() {
  log "Buscando estoque oficial CSV no servidor Pleno"
  cd "$PROJECT_DIR"
  local args=()
  if [[ -n "$DATE_ARG" ]]; then
    args+=("--date" "$DATE_ARG")
  fi
  "$PROJECT_DIR/scripts/fetch_pleno_stock_official_latest.sh" "${args[@]}"
}

run_auditoria() {
  if [[ "$ALL_LOJAS" -eq 1 ]]; then
    log "Gerando auditoria de movimentos via MySQL para todas as lojas"
  else
    log "Gerando auditoria de movimentos via MySQL para lojas em $LOJAS_FILE"
  fi
  local args=("--package-dir" "$PROJECT_DIR/outputs/recebidos_servidor")
  if [[ "$ALL_LOJAS" -eq 1 ]]; then
    args+=("--all-lojas")
  else
    args+=("--lojas-file" "$LOJAS_FILE")
  fi
  if [[ -n "$DATE_ARG" ]]; then
    args+=("--date" "$DATE_ARG")
  fi
  PYTHON_BIN="$PYTHON_BIN" "$PROJECT_DIR/scripts/run_pleno_stock_audit_server.sh" "${args[@]}"
}

case "$ACTION" in
  estoque)
    run_estoque
    ;;
  auditoria)
    run_auditoria
    ;;
  tudo)
    run_estoque
    run_auditoria
    ;;
  *)
    echo "Acao desconhecida: $ACTION" >&2
    usage
    exit 1
    ;;
esac
