#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
LOJAS_FILE="${PLENO_STOCK_AUDIT_LOJAS_FILE:-$ROOT_DIR/config/pleno_stock_audit_lojas.txt}"

usage() {
  cat <<'EOF'
Uso:
  scripts/add_pleno_stock_audit_lojas.sh 259 1174 1201
  scripts/add_pleno_stock_audit_lojas.sh 259,1174,1201

Inclui lojas no config/pleno_stock_audit_lojas.txt sem duplicar.
EOF
}

if [ "$#" -eq 0 ]; then
  usage
  exit 1
fi

mkdir -p "$(dirname "$LOJAS_FILE")"
touch "$LOJAS_FILE"

TMP_FILE="$(mktemp "${TMPDIR:-/tmp}/pleno-lojas.XXXXXX")"
trap 'rm -f "$TMP_FILE"' EXIT HUP INT TERM

{
  sed 's/#.*$//' "$LOJAS_FILE" | tr ',[:space:]' '\n'
  printf '%s\n' "$@" | tr ',[:space:]' '\n'
} | awk '
  /^[0-9]+$/ { lojas[$0] = 1 }
  END {
    for (loja in lojas) print loja
  }
' | sort -n > "$TMP_FILE"

mv "$TMP_FILE" "$LOJAS_FILE"
echo "Lojas configuradas em $LOJAS_FILE:"
tr '\n' ' ' < "$LOJAS_FILE"
printf '\n'
