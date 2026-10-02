#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-${ROOT_DIR}/.env}"
LOJAS_FILE="${LOJAS_FILE:-${ROOT_DIR}/config/pleno_stock_audit_lojas.txt}"
MYSQL_BIN="${MYSQL_BIN:-/opt/homebrew/opt/mysql-client/bin/mysql}"
MYSQLDUMP_BIN="${MYSQLDUMP_BIN:-/opt/homebrew/opt/mysql-client/bin/mysqldump}"

OMNILOJA_DB_CONTAINER="${OMNILOJA_DB_CONTAINER:-omniloja-db}"
OMNILOJA_DB_NAME="${OMNILOJA_DB_NAME:-omniloja}"
OMNILOJA_DB_ROOT_PASSWORD="${OMNILOJA_DB_ROOT_PASSWORD:-omniloja_root_dev_password}"

START_DATE="${START_DATE:-}"
END_DATE="${END_DATE:-}"
LOJAS="${LOJAS:-}"

usage() {
  cat <<'EOF'
Uso:
  scripts/seed_omniloja_demo_db.sh [opcoes]

Cria uma base demo no MySQL local do Omniloja copiando um recorte do banco
Pleno configurado no .env local. A copia e filtrada por lojas/datas e, no fim,
remove referencias textuais a DIA/DIABRASIL, substituindo por OMNILOJA.

Opcoes:
  --start-date YYYY-MM-DD     Data inicial. Padrao: 7 dias antes da maior data das lojas.
  --end-date YYYY-MM-DD       Data final. Padrao: maior data encontrada nas lojas.
  --lojas 155,203             Lojas. Padrao: config/pleno_stock_audit_lojas.txt.
  --env-file ARQUIVO          Env do banco origem. Padrao: .env.
  --help                      Mostra esta ajuda.

Variaveis uteis:
  OMNILOJA_DB_CONTAINER       Container MySQL destino. Padrao: omniloja-db.
  OMNILOJA_DB_NAME            Database destino. Padrao: omniloja.
  OMNILOJA_DB_ROOT_PASSWORD   Senha root do MySQL destino.
EOF
}

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

die() {
  echo "Erro: $*" >&2
  exit 1
}

need_value() {
  [[ $# -ge 2 && -n "${2:-}" ]] || die "opcao $1 exige valor"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --start-date)
      need_value "$@"; START_DATE="$2"; shift 2 ;;
    --end-date)
      need_value "$@"; END_DATE="$2"; shift 2 ;;
    --lojas)
      need_value "$@"; LOJAS="$2"; shift 2 ;;
    --env-file)
      need_value "$@"; ENV_FILE="$2"; shift 2 ;;
    --help|-h)
      usage; exit 0 ;;
    *)
      die "opcao desconhecida: $1" ;;
  esac
done

[[ -f "${ENV_FILE}" ]] || die "env nao encontrado: ${ENV_FILE}"
[[ -x "${MYSQL_BIN}" ]] || die "mysql nao encontrado em ${MYSQL_BIN}"
[[ -x "${MYSQLDUMP_BIN}" ]] || die "mysqldump nao encontrado em ${MYSQLDUMP_BIN}"
docker inspect "${OMNILOJA_DB_CONTAINER}" >/dev/null 2>&1 || die "container destino nao encontrado: ${OMNILOJA_DB_CONTAINER}"

if [[ -z "${LOJAS}" ]]; then
  [[ -f "${LOJAS_FILE}" ]] || die "arquivo de lojas nao encontrado: ${LOJAS_FILE}"
  LOJAS="$(grep -E '^[0-9]+' "${LOJAS_FILE}" | paste -sd, -)"
fi
[[ -n "${LOJAS}" ]] || die "nenhuma loja informada"

for loja in ${LOJAS//,/ }; do
  [[ "${loja}" =~ ^[0-9]+$ ]] || die "loja invalida: ${loja}"
done
LOJAS_SQL="${LOJAS}"

SOURCE_CNF="$(mktemp /tmp/omniloja-source.XXXXXX.cnf)"
SOURCE_DB="$(python3 - "${ENV_FILE}" <<'PY'
from pathlib import Path
import sys

env = {}
for line in Path(sys.argv[1]).read_text(errors="ignore").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    env[key.strip()] = value.strip().strip('"').strip("'")

print(env.get("MYSQL_DATABASE", "pleno"))
PY
)"
cleanup() {
  rm -f "${SOURCE_CNF}" "${SANITIZE_SQL:-}" "${DROP_SQL:-}" "${SCHEMA_SQL:-}" "${DATA_SQL:-}"
}
trap cleanup EXIT

python3 - "${ENV_FILE}" > "${SOURCE_CNF}" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
env = {}
for line in env_path.read_text(errors="ignore").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    env[key.strip()] = value.strip().strip('"').strip("'")

required = ["MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"]
missing = [key for key in required if not env.get(key)]
if missing:
    raise SystemExit(f"Variaveis ausentes no env: {', '.join(missing)}")

print("[client]")
print(f"host={env.get('MYSQL_HOST', '')}")
print(f"port={env.get('MYSQL_PORT', '3306')}")
print(f"user={env.get('MYSQL_USER', '')}")
print(f"password={env.get('MYSQL_PASSWORD', '')}")
print("default-character-set=latin1")
PY
chmod 600 "${SOURCE_CNF}"

if [[ -z "${END_DATE}" ]]; then
  END_DATE="$("${MYSQL_BIN}" --defaults-extra-file="${SOURCE_CNF}" -N -B "${SOURCE_DB}" -e "
    SELECT MAX(ed.est01_data)
    FROM est01_estoque_diario ed
    JOIN mcd03_mercadoria_filial mf ON mf.mcd03_id = ed.mcd03_mercadoria_filial_id
    JOIN cfg06_filial f ON f.cfg06_id = mf.cfg06_filial_id
    WHERE f.cfg06_numero IN (${LOJAS_SQL})
  ")"
fi
[[ "${END_DATE}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || die "data final invalida: ${END_DATE}"

if [[ -z "${START_DATE}" ]]; then
  START_DATE="$(python3 - "${END_DATE}" <<'PY'
from datetime import date, timedelta
import sys
print((date.fromisoformat(sys.argv[1]) - timedelta(days=7)).isoformat())
PY
)"
fi
[[ "${START_DATE}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || die "data inicial invalida: ${START_DATE}"

log "Seed demo Omniloja"
log "Lojas: ${LOJAS}"
log "Periodo: ${START_DATE} a ${END_DATE}"

TABLES=(
  cfg06_filial
  pes03_estabelecimento
  pes04_pessoa
  mcd01_mercadoria
  mcd03_mercadoria_filial
  est01_estoque_diario
  est06_estoque_atual
  fcx01_cupom
  fcx02_cupom_item
  est05_estoque_movimento
  fis01_notafiscal
  fis02_notafiscal_item
  fis25_notafiscal_item_fisico
  com16_pretransferencia
  com19_pretransferencia_item
  com33_pedtransf_atendido
  est03_inventario
  est04_inventario_item
  est02_boletim_consumo_producao
  adm22_motivo_troca
  est09_troca_movimento
  dia01_ajustes_recebimento
  dom14_operacao_fiscal
)

mysql_target() {
  docker exec -i -e MYSQL_PWD="${OMNILOJA_DB_ROOT_PASSWORD}" "${OMNILOJA_DB_CONTAINER}" \
    mysql -uroot "${OMNILOJA_DB_NAME}"
}

DROP_SQL="$(mktemp /tmp/omniloja-drop.XXXXXX.sql)"
{
  echo "SET FOREIGN_KEY_CHECKS=0;"
  for (( idx=${#TABLES[@]}-1 ; idx>=0 ; idx-- )); do
    printf 'DROP TABLE IF EXISTS `%s`;\n' "${TABLES[$idx]}"
  done
  echo "SET FOREIGN_KEY_CHECKS=1;"
} > "${DROP_SQL}"
mysql_target < "${DROP_SQL}"

SCHEMA_SQL="$(mktemp /tmp/omniloja-schema.XXXXXX.sql)"
{
  echo "SET FOREIGN_KEY_CHECKS=0;"
  "${MYSQLDUMP_BIN}" --defaults-extra-file="${SOURCE_CNF}" \
    --no-data --single-transaction --skip-lock-tables --no-tablespaces \
    --set-gtid-purged=OFF "${SOURCE_DB}" "${TABLES[@]}"
  echo "SET FOREIGN_KEY_CHECKS=1;"
} > "${SCHEMA_SQL}"
mysql_target < "${SCHEMA_SQL}"

dump_table() {
  local table="$1"
  local where="$2"
  log "Copiando ${table}"
  "${MYSQLDUMP_BIN}" --defaults-extra-file="${SOURCE_CNF}" \
    --no-create-info --skip-triggers --single-transaction --quick --skip-lock-tables \
    --no-tablespaces --set-gtid-purged=OFF \
    --where="${where}" "${SOURCE_DB}" "${table}" | mysql_target
}

STORE_FILTER="cfg06_numero IN (${LOJAS_SQL})"
STORE_ID_FILTER="cfg06_id IN (SELECT cfg06_id FROM cfg06_filial WHERE cfg06_numero IN (${LOJAS_SQL}))"
STORE_PES03_FILTER="pes03_id IN (SELECT pes03_estabelecimento_id FROM cfg06_filial WHERE cfg06_numero IN (${LOJAS_SQL}))"
MF_FILTER="mcd03_id IN (SELECT mf.mcd03_id FROM mcd03_mercadoria_filial mf JOIN cfg06_filial f ON f.cfg06_id = mf.cfg06_filial_id WHERE f.cfg06_numero IN (${LOJAS_SQL}))"
MERC_FILTER="mcd01_id IN (SELECT mf.mcd01_mercadoria_id FROM mcd03_mercadoria_filial mf JOIN cfg06_filial f ON f.cfg06_id = mf.cfg06_filial_id WHERE f.cfg06_numero IN (${LOJAS_SQL}))"
CUPOM_FILTER="fcx01_id IN (SELECT c.fcx01_id FROM fcx01_cupom c JOIN cfg06_filial f ON f.cfg06_id = c.cfg06_filial_id WHERE f.cfg06_numero IN (${LOJAS_SQL}) AND c.fcx01_data BETWEEN '${START_DATE}' AND '${END_DATE}')"
MOV_FIS02_FILTER="fis02_id IN (SELECT e.fis02_notafiscal_item_id FROM est05_estoque_movimento e JOIN mcd03_mercadoria_filial mf ON mf.mcd03_id = e.mcd03_mercadoria_filial_id JOIN cfg06_filial f ON f.cfg06_id = mf.cfg06_filial_id WHERE f.cfg06_numero IN (${LOJAS_SQL}) AND e.est05_data BETWEEN '${START_DATE}' AND '${END_DATE}' AND e.fis02_notafiscal_item_id IS NOT NULL)"
NF_ID_FILTER="fis01_id IN (SELECT ni.fis01_notafiscal_id FROM fis02_notafiscal_item ni JOIN mcd03_mercadoria_filial mf ON mf.mcd03_id = ni.mcd03_mercadoria_filial_id JOIN cfg06_filial f ON f.cfg06_id = mf.cfg06_filial_id WHERE f.cfg06_numero IN (${LOJAS_SQL}) AND ni.fis01_notafiscal_id IS NOT NULL) AND fis01_data_entrada_saida BETWEEN '${START_DATE}' AND '${END_DATE}'"
INV_FILTER="est03_id IN (SELECT i.est03_id FROM est03_inventario i JOIN cfg06_filial f ON f.cfg06_id = i.cfg06_filial_id WHERE f.cfg06_numero IN (${LOJAS_SQL}) AND (DATE(i.est03_data_hora_fim) BETWEEN '${START_DATE}' AND '${END_DATE}' OR i.est03_data_criacao BETWEEN '${START_DATE}' AND '${END_DATE}'))"
PEDIDO_FILTER="com16_id IN (SELECT p.com16_id FROM com16_pretransferencia p JOIN cfg06_filial f ON f.cfg06_id = p.cfg06_filial_dest_id WHERE f.cfg06_numero IN (${LOJAS_SQL}) AND DATE(COALESCE(p.com16_dthr, p.com16_dthr_importacao_trd, p.com16_dthr_exportado_trd)) BETWEEN '${START_DATE}' AND '${END_DATE}')"

dump_table cfg06_filial "${STORE_FILTER}"
dump_table pes03_estabelecimento "${STORE_PES03_FILTER}"
dump_table pes04_pessoa "pes03_estabelecimento_id IN (SELECT pes03_estabelecimento_id FROM cfg06_filial WHERE cfg06_numero IN (${LOJAS_SQL}))"
dump_table mcd03_mercadoria_filial "${MF_FILTER}"
dump_table mcd01_mercadoria "${MERC_FILTER}"
dump_table est01_estoque_diario "est01_data BETWEEN DATE_SUB('${START_DATE}', INTERVAL 1 DAY) AND '${END_DATE}' AND mcd03_mercadoria_filial_id IN (SELECT mf.mcd03_id FROM mcd03_mercadoria_filial mf JOIN cfg06_filial f ON f.cfg06_id = mf.cfg06_filial_id WHERE f.cfg06_numero IN (${LOJAS_SQL}))"
dump_table est06_estoque_atual "mcd03_mercadoria_filial_id IN (SELECT mf.mcd03_id FROM mcd03_mercadoria_filial mf JOIN cfg06_filial f ON f.cfg06_id = mf.cfg06_filial_id WHERE f.cfg06_numero IN (${LOJAS_SQL}))"
dump_table fcx01_cupom "cfg06_filial_id IN (SELECT cfg06_id FROM cfg06_filial WHERE cfg06_numero IN (${LOJAS_SQL})) AND fcx01_data BETWEEN '${START_DATE}' AND '${END_DATE}'"
dump_table fcx02_cupom_item "fcx01_cupom_id IN (SELECT c.fcx01_id FROM fcx01_cupom c JOIN cfg06_filial f ON f.cfg06_id = c.cfg06_filial_id WHERE f.cfg06_numero IN (${LOJAS_SQL}) AND c.fcx01_data BETWEEN '${START_DATE}' AND '${END_DATE}')"
dump_table est05_estoque_movimento "est05_data BETWEEN '${START_DATE}' AND '${END_DATE}' AND mcd03_mercadoria_filial_id IN (SELECT mf.mcd03_id FROM mcd03_mercadoria_filial mf JOIN cfg06_filial f ON f.cfg06_id = mf.cfg06_filial_id WHERE f.cfg06_numero IN (${LOJAS_SQL}))"
dump_table fis01_notafiscal "${NF_ID_FILTER}"
dump_table fis02_notafiscal_item "fis01_notafiscal_id IN (SELECT nf.fis01_id FROM fis01_notafiscal nf WHERE ${NF_ID_FILTER}) OR ${MOV_FIS02_FILTER}"
dump_table fis25_notafiscal_item_fisico "fis02_notafiscal_item_id IN (SELECT ni.fis02_id FROM fis02_notafiscal_item ni WHERE ni.fis01_notafiscal_id IN (SELECT nf.fis01_id FROM fis01_notafiscal nf WHERE ${NF_ID_FILTER}))"
dump_table est03_inventario "${INV_FILTER}"
dump_table est04_inventario_item "est03_inventario_id IN (SELECT i.est03_id FROM est03_inventario i JOIN cfg06_filial f ON f.cfg06_id = i.cfg06_filial_id WHERE f.cfg06_numero IN (${LOJAS_SQL}) AND (DATE(i.est03_data_hora_fim) BETWEEN '${START_DATE}' AND '${END_DATE}' OR i.est03_data_criacao BETWEEN '${START_DATE}' AND '${END_DATE}'))"
dump_table est02_boletim_consumo_producao "est02_id IN (SELECT e.est02_boletim_consumo_producao_id FROM est05_estoque_movimento e JOIN mcd03_mercadoria_filial mf ON mf.mcd03_id=e.mcd03_mercadoria_filial_id JOIN cfg06_filial f ON f.cfg06_id=mf.cfg06_filial_id WHERE f.cfg06_numero IN (${LOJAS_SQL}) AND e.est05_data BETWEEN '${START_DATE}' AND '${END_DATE}' AND e.est02_boletim_consumo_producao_id IS NOT NULL)"
dump_table est09_troca_movimento "fis02_notafiscal_item_id IN (SELECT ni.fis02_id FROM fis02_notafiscal_item ni WHERE ni.fis01_notafiscal_id IN (SELECT nf.fis01_id FROM fis01_notafiscal nf WHERE ${NF_ID_FILTER}))"
dump_table adm22_motivo_troca "adm22_id IN (SELECT tr.adm22_motivo_troca_id FROM est09_troca_movimento tr WHERE tr.fis02_notafiscal_item_id IN (SELECT ni.fis02_id FROM fis02_notafiscal_item ni WHERE ni.fis01_notafiscal_id IN (SELECT nf.fis01_id FROM fis01_notafiscal nf WHERE ${NF_ID_FILTER})))"
dump_table dia01_ajustes_recebimento "cfg06_filial_id IN (SELECT cfg06_id FROM cfg06_filial WHERE cfg06_numero IN (${LOJAS_SQL})) AND dia01_data_nf BETWEEN '${START_DATE}' AND '${END_DATE}'"
dump_table dom14_operacao_fiscal "dom14_id IN (SELECT nf.dom14_operacao_fiscal_id FROM fis01_notafiscal nf WHERE ${NF_ID_FILTER})"
dump_table com16_pretransferencia "${PEDIDO_FILTER}"
dump_table com19_pretransferencia_item "com16_pretransferencia_id IN (SELECT p.com16_id FROM com16_pretransferencia p JOIN cfg06_filial f ON f.cfg06_id = p.cfg06_filial_dest_id WHERE f.cfg06_numero IN (${LOJAS_SQL}) AND DATE(COALESCE(p.com16_dthr, p.com16_dthr_importacao_trd, p.com16_dthr_exportado_trd)) BETWEEN '${START_DATE}' AND '${END_DATE}')"
dump_table com33_pedtransf_atendido "com19_pretransferencia_item_id IN (SELECT i.com19_id FROM com19_pretransferencia_item i JOIN com16_pretransferencia p ON p.com16_id = i.com16_pretransferencia_id JOIN cfg06_filial f ON f.cfg06_id = p.cfg06_filial_dest_id WHERE f.cfg06_numero IN (${LOJAS_SQL}) AND DATE(COALESCE(p.com16_dthr, p.com16_dthr_importacao_trd, p.com16_dthr_exportado_trd)) BETWEEN '${START_DATE}' AND '${END_DATE}')"

log "Anonimizando textos da base demo"
SANITIZE_SQL="$(mktemp /tmp/omniloja-sanitize.XXXXXX.sql)"
docker exec -i -e MYSQL_PWD="${OMNILOJA_DB_ROOT_PASSWORD}" "${OMNILOJA_DB_CONTAINER}" \
  mysql -uroot -N -B "${OMNILOJA_DB_NAME}" <<SQL > "${SANITIZE_SQL}"
SELECT CONCAT(
  'UPDATE \`', table_name, '\` SET \`', column_name, '\` = ',
  'REPLACE(REPLACE(REPLACE(REPLACE(\`', column_name, '\`, ''DIA BRASIL'', ''OMNILOJA''), ''DIABRASIL'', ''OMNILOJA''), ''Dia Brasil'', ''Omniloja''), ''DiaBrasil'', ''Omniloja'') ',
  'WHERE \`', column_name, '\` IS NOT NULL;'
)
FROM information_schema.columns
WHERE table_schema = DATABASE()
  AND table_name IN ($(printf "'%s'," "${TABLES[@]}" | sed 's/,$//'))
  AND data_type IN ('char','varchar','tinytext','text','mediumtext','longtext');
SQL
{
  echo "SET SQL_SAFE_UPDATES=0;"
  cat "${SANITIZE_SQL}"
  cat <<'SQL'
UPDATE cfg06_filial
SET cfg06_nome = CONCAT('Loja Demo ', cfg06_numero)
WHERE cfg06_numero IS NOT NULL;
SQL
} | mysql_target

log "Resumo destino"
docker exec -i -e MYSQL_PWD="${OMNILOJA_DB_ROOT_PASSWORD}" "${OMNILOJA_DB_CONTAINER}" \
  mysql -uroot "${OMNILOJA_DB_NAME}" <<SQL
SELECT 'cfg06_filial' tabela, COUNT(*) linhas FROM cfg06_filial
UNION ALL SELECT 'mcd03_mercadoria_filial', COUNT(*) FROM mcd03_mercadoria_filial
UNION ALL SELECT 'est01_estoque_diario', COUNT(*) FROM est01_estoque_diario
UNION ALL SELECT 'est05_estoque_movimento', COUNT(*) FROM est05_estoque_movimento
UNION ALL SELECT 'fcx01_cupom', COUNT(*) FROM fcx01_cupom
UNION ALL SELECT 'fcx02_cupom_item', COUNT(*) FROM fcx02_cupom_item
UNION ALL SELECT 'fis01_notafiscal', COUNT(*) FROM fis01_notafiscal
UNION ALL SELECT 'fis02_notafiscal_item', COUNT(*) FROM fis02_notafiscal_item;
SQL

log "Seed demo concluido."
