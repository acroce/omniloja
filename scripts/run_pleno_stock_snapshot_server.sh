#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOJAS=""
LABEL="snapshot"
OUT_DIR="$PROJECT_DIR/outputs/pleno_stock_snapshots"
PACKAGE_DIR="$PROJECT_DIR/outputs/pleno_stock_snapshot_packages"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LOJAS_FILE="$PROJECT_DIR/config/pleno_stock_audit_lojas.txt"

usage() {
  cat <<'EOF'
Uso:
  scripts/run_pleno_stock_snapshot_server.sh [opcoes]

Roda no servidor e coleta um retrato do estoque atual do Pleno. Use para
coletas pontuais, por exemplo 06:00 e 10:30, nas lojas configuradas.

Opcoes:
  --label 0600                 Rotulo da coleta.
  --lojas 155,203              Lista de lojas. Se omitido, le config/pleno_stock_audit_lojas.txt.
  --lojas-file FILE            Arquivo com lojas configuradas.
  --out-dir DIR                Diretorio dos CSVs.
  --package-dir DIR            Diretorio dos pacotes .tar.gz.
  --project-dir DIR            Diretorio do projeto no servidor.
  --python-bin CMD             Python a usar. Padrao: python3 ou PYTHON_BIN.
  --help                       Mostra esta ajuda.

Exemplo cron:
  0 6 * * * /caminho/projeto/scripts/run_pleno_stock_snapshot_server.sh --label 0600 >> /var/log/pleno_stock_snapshot.log 2>&1
  30 10 * * * /caminho/projeto/scripts/run_pleno_stock_snapshot_server.sh --label 1030 >> /var/log/pleno_stock_snapshot.log 2>&1
EOF
}

die() {
  echo "Erro: $*" >&2
  exit 1
}

has_mysql_env() {
  [[ -n "${MYSQL_HOST:-}" && -n "${MYSQL_USER:-}" && -n "${MYSQL_PASSWORD:-}" ]]
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
    --label)
      LABEL="$2"
      shift 2
      ;;
    --lojas)
      LOJAS="$2"
      shift 2
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
[[ -f "$PROJECT_DIR/scripts/export_pleno_stock_snapshot.py" ]] || die "exportador de snapshot nao encontrado"

if [[ -z "$LOJAS" ]]; then
  LOJAS="$(read_lojas_file "$LOJAS_FILE" || true)"
fi

[[ -n "$LOJAS" ]] || die "nenhuma loja informada; use --lojas ou crie $LOJAS_FILE"

mkdir -p "$OUT_DIR" "$PACKAGE_DIR"

before_file="$(mktemp)"
after_file="$(mktemp)"
find "$OUT_DIR" -mindepth 1 -maxdepth 1 -type d -print | sort > "$before_file"

echo "Iniciando snapshot Pleno em $(date '+%Y-%m-%d %H:%M:%S')"
echo "Projeto: $PROJECT_DIR"
echo "Lojas: $LOJAS"
echo "Label: $LABEL"

cd "$PROJECT_DIR"
PYTHONPATH="$PROJECT_DIR/.python_packages${PYTHONPATH:+:$PYTHONPATH}" \
  "$PYTHON_BIN" "$PROJECT_DIR/scripts/export_pleno_stock_snapshot.py" \
    --out-dir "$OUT_DIR" \
    --label "$LABEL" \
    --lojas "$LOJAS"

find "$OUT_DIR" -mindepth 1 -maxdepth 1 -type d -print | sort > "$after_file"
run_dir="$(comm -13 "$before_file" "$after_file" | tail -n 1)"
rm -f "$before_file" "$after_file"

[[ -n "$run_dir" && -d "$run_dir" ]] || die "nao consegui identificar a pasta gerada"

package_path="$PACKAGE_DIR/$(basename "$run_dir").tar.gz"
tar -C "$OUT_DIR" -czf "$package_path" "$(basename "$run_dir")"

echo "Pacote gerado: $package_path"
echo "Finalizado em $(date '+%Y-%m-%d %H:%M:%S')"
