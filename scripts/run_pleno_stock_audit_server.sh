#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATE_ARG=""
START_DATE=""
END_DATE=""
LOJAS=""
ALL_LOJAS=0
OUT_DIR="$PROJECT_DIR/outputs/pleno_stock_audit"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PACKAGE_DIR="$PROJECT_DIR/outputs/pleno_stock_audit_packages"
LOJAS_FILE="$PROJECT_DIR/config/pleno_stock_audit_lojas.txt"

usage() {
  cat <<'EOF'
Uso:
  scripts/run_pleno_stock_audit_server.sh [opcoes]

Roda no servidor, exporta a auditoria de estoque do Pleno e empacota a pasta
do dia em .tar.gz para trazer para a maquina local.

Opcoes:
  --date YYYY-MM-DD              Data unica da auditoria. Padrao: ontem.
  --start-date YYYY-MM-DD        Data inicial.
  --end-date YYYY-MM-DD          Data final.
  --lojas 155,203                Lista de lojas. Se omitido, le o arquivo de lojas; sem arquivo, exporta todas.
  --all-lojas                    Ignora arquivo/lista e exporta todas as lojas.
  --lojas-file FILE              Arquivo com lojas configuradas.
  --out-dir DIR                  Diretorio dos CSVs.
  --package-dir DIR              Diretorio dos pacotes .tar.gz.
  --project-dir DIR              Diretorio do projeto no servidor.
  --python-bin CMD               Python a usar. Padrao: python3 ou PYTHON_BIN.
  --help                         Mostra esta ajuda.

Exemplo cron diario as 01:30:
  30 1 * * * /caminho/tabelas-pleno-vamos-criar-uma-conex/scripts/run_pleno_stock_audit_server.sh --lojas 155,203 >> /var/log/pleno_stock_audit.log 2>&1
EOF
}

die() {
  echo "Erro: $*" >&2
  exit 1
}

has_mysql_env() {
  [[ -n "${MYSQL_HOST:-}" && -n "${MYSQL_USER:-}" && -n "${MYSQL_PASSWORD:-}" ]]
}

is_date() {
  [[ "$1" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]
}

read_lojas_file() {
  local file="$1"
  [[ -f "$file" ]] || return 1
  awk '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*$/ { next }
    {
      gsub(/[[:space:]]+/, "", $0)
      if ($0 != "") {
        if (out != "") out = out ","
        out = out $0
      }
    }
    END { print out }
  ' "$file"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --date)
      DATE_ARG="$2"
      shift 2
      ;;
    --start-date)
      START_DATE="$2"
      shift 2
      ;;
    --end-date)
      END_DATE="$2"
      shift 2
      ;;
    --lojas)
      LOJAS="$2"
      shift 2
      ;;
    --all-lojas)
      ALL_LOJAS=1
      shift
      ;;
    --lojas-file)
      LOJAS_FILE="$2"
      shift 2
      ;;
    --out-dir)
      OUT_DIR="$2"
      shift 2
      ;;
    --package-dir)
      PACKAGE_DIR="$2"
      shift 2
      ;;
    --project-dir)
      PROJECT_DIR="$2"
      shift 2
      ;;
    --python-bin)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      die "opcao desconhecida: $1"
      ;;
  esac
done

[[ -d "$PROJECT_DIR" ]] || die "diretorio do projeto nao encontrado: $PROJECT_DIR"
[[ -f "$PROJECT_DIR/.env" || has_mysql_env ]] || die "arquivo .env nao encontrado em $PROJECT_DIR e variaveis MYSQL_HOST/MYSQL_USER/MYSQL_PASSWORD ausentes"
[[ -f "$PROJECT_DIR/scripts/export_pleno_stock_audit.py" ]] || die "exportador Python nao encontrado"

if [[ "$ALL_LOJAS" -eq 0 && -z "$LOJAS" ]]; then
  LOJAS="$(read_lojas_file "$LOJAS_FILE" || true)"
fi

if [[ -n "$DATE_ARG" && ( -n "$START_DATE" || -n "$END_DATE" ) ]]; then
  die "use --date ou --start-date/--end-date, nao os dois"
fi

if [[ -n "$DATE_ARG" ]]; then
  is_date "$DATE_ARG" || die "--date deve estar no formato YYYY-MM-DD"
fi

if [[ -n "$START_DATE" || -n "$END_DATE" ]]; then
  [[ -n "$START_DATE" && -n "$END_DATE" ]] || die "informe --start-date e --end-date juntos"
  is_date "$START_DATE" || die "--start-date deve estar no formato YYYY-MM-DD"
  is_date "$END_DATE" || die "--end-date deve estar no formato YYYY-MM-DD"
fi

mkdir -p "$OUT_DIR" "$PACKAGE_DIR"

default_run_date() {
  "$PYTHON_BIN" - <<'PY'
from datetime import date, timedelta
print((date.today() - timedelta(days=1)).isoformat())
PY
}

cmd=("$PYTHON_BIN" "$PROJECT_DIR/scripts/export_pleno_stock_audit.py" "--out-dir" "$OUT_DIR")
run_stamp=""

if [[ -n "$DATE_ARG" ]]; then
  cmd+=("--date" "$DATE_ARG")
  run_stamp="$DATE_ARG"
elif [[ -n "$START_DATE" ]]; then
  cmd+=("--start-date" "$START_DATE" "--end-date" "$END_DATE")
  run_stamp="${START_DATE}_a_${END_DATE}"
else
  run_stamp="$(default_run_date)"
fi

if [[ "$ALL_LOJAS" -eq 1 ]]; then
  cmd+=("--all-lojas")
  run_stamp="${run_stamp}_lojas_todas"
elif [[ -n "$LOJAS" ]]; then
  cmd+=("--lojas" "$LOJAS")
  loja_stamp="${LOJAS//,/-}"
  loja_stamp="${loja_stamp// /}"
  run_stamp="${run_stamp}_lojas_${loja_stamp}"
fi

echo "Iniciando auditoria Pleno em $(date '+%Y-%m-%d %H:%M:%S')"
echo "Projeto: $PROJECT_DIR"
echo "Saida: $OUT_DIR"
if [[ "$ALL_LOJAS" -eq 1 ]]; then
  echo "Lojas: todas"
else
  echo "Lojas: ${LOJAS:-todas}"
fi

cd "$PROJECT_DIR"
PYTHONPATH="$PROJECT_DIR/.python_packages${PYTHONPATH:+:$PYTHONPATH}" "${cmd[@]}"

latest_dir="$OUT_DIR/$run_stamp"
[[ -d "$latest_dir" ]] || die "pasta esperada nao encontrada: $latest_dir"

package_name="$(basename "$latest_dir").tar.gz"
package_path="$PACKAGE_DIR/$package_name"

tar -C "$OUT_DIR" -czf "$package_path" "$(basename "$latest_dir")"

echo "Pacote gerado: $package_path"
echo "Finalizado em $(date '+%Y-%m-%d %H:%M:%S')"
