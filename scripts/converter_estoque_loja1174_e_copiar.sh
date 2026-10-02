#!/usr/bin/env bash
set -Eeuo pipefail

SOURCE_PATH=""
SOURCE_DIR=""
SOURCE_MODE="mysql"
STORE="1174"
ENV_FILE=""
MYSQL_BIN=""
MYSQL_HOST="172.22.20.101"
MYSQL_PORT="3306"
MYSQL_USER="diabrasil"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-}"
MYSQL_DATABASE="pleno"
MYSQL_VIEW="view_dia_estoque_loja"
DEST_HOST=""
DEST_USER=""
DEST_PASSWORD=""
DEST_PORT="22"
DEST_PATH=""
OUT_DIR=""
OUTPUT_FILE=""
CREATE_DEST_DIR="1"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_OUT_DIR="${PROJECT_ROOT}/outputs/mercadoria_filial_convertido"
DEFAULT_SOURCE_DIR="${PROJECT_ROOT}/outputs"

usage() {
  cat <<'EOF'
Uso:
  scripts/converter_estoque_loja1174_e_copiar.sh [opcoes]

Por padrao consulta a view MySQL view_dia_estoque_loja e converte para
MERCADORIA_FILIAL_*.csv.

Tambem pode converter um estoque_*.csv no layout:
  nro_loja;codigo_interno;valor_estoque;...;qtd_estoque;...

para o layout MERCADORIA_FILIAL_*.csv:
  CODIGO_LOJA;CODIGO_ARTIGO;PRECO_VENDA_ATUAL;...;ESTOQUE_ATUAL;...

Depois da conversao, se informado, copia o MERCADORIA_FILIAL para outro Linux.
Por padrao a saida fica como MERCADORIA_FILIAL_AAAAMMDDHHMMSS.csv,
mantendo o nome que o outro sistema entende.

Opcoes:
  --env-file ARQUIVO            Opcional: sobrescreve os dados MySQL embutidos.
  --mysql-bin CAMINHO           Binario mysql. Padrao: mysql do PATH.
  --mysql-view VIEW             View de estoque. Padrao: view_dia_estoque_loja.
  --source-dir DIR               Pasta local onde buscar estoque_*.csv.
                                Ativa modo arquivo e pega o mais recente.
  --source-path ARQUIVO          Forca um arquivo estoque_*.csv especifico.
  --store LOJA                   Loja a converter. Padrao: 1174.
  --dest-host HOST               Linux de destino para receber o arquivo convertido.
  --dest-user USER               Usuario do Linux de destino.
  --dest-password SENHA          Senha do Linux de destino.
  --dest-port PORTA              Porta SSH do destino. Padrao: 22.
  --dest-path CAMINHO            Diretorio remoto terminado em / ou arquivo remoto completo.
                                Se for diretorio, preserva MERCADORIA_FILIAL_AAAAMMDDHHMMSS.csv.
  --out-dir DIR                  Diretorio local de saida.
  --output-file ARQUIVO          Arquivo local de saida.
  --no-create-dest-dir           Nao cria o diretorio remoto antes de copiar.
  --help                         Mostra esta ajuda.

Tambem aceita a senha do destino por variavel:
  DEST_PASSWORD_ENV=senha_destino scripts/converter_estoque_loja1174_e_copiar.sh ...

Exemplo local:
  scripts/converter_estoque_loja1174_e_copiar.sh

Exemplo convertendo e copiando:
  scripts/converter_estoque_loja1174_e_copiar.sh \
    --dest-host linux-destino \
    --dest-user usuario_destino \
    --dest-password senha_destino \
    --dest-path /servpleno/importacao/
EOF
}

die() {
  echo "Erro: $*" >&2
  exit 1
}

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

need_value() {
  [[ $# -ge 2 && -n "${2:-}" ]] || die "opcao $1 exige valor"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      need_value "$@"; ENV_FILE="$2"; shift 2 ;;
    --mysql-bin)
      need_value "$@"; MYSQL_BIN="$2"; shift 2 ;;
    --mysql-view)
      need_value "$@"; MYSQL_VIEW="$2"; shift 2 ;;
    --source-path)
      need_value "$@"; SOURCE_PATH="$2"; SOURCE_MODE="file"; shift 2 ;;
    --source-dir)
      need_value "$@"; SOURCE_DIR="$2"; SOURCE_MODE="file"; shift 2 ;;
    --store)
      need_value "$@"; STORE="$2"; shift 2 ;;
    --dest-host)
      need_value "$@"; DEST_HOST="$2"; shift 2 ;;
    --dest-user)
      need_value "$@"; DEST_USER="$2"; shift 2 ;;
    --dest-password)
      need_value "$@"; DEST_PASSWORD="$2"; shift 2 ;;
    --dest-port)
      need_value "$@"; DEST_PORT="$2"; shift 2 ;;
    --dest-path)
      need_value "$@"; DEST_PATH="$2"; shift 2 ;;
    --out-dir)
      need_value "$@"; OUT_DIR="$2"; shift 2 ;;
    --output-file)
      need_value "$@"; OUTPUT_FILE="$2"; shift 2 ;;
    --no-create-dest-dir)
      CREATE_DEST_DIR="0"; shift ;;
    --help|-h)
      usage; exit 0 ;;
    *)
      die "opcao desconhecida: $1" ;;
  esac
done

SOURCE_DIR="${SOURCE_DIR:-$DEFAULT_SOURCE_DIR}"

if [[ -n "$DEST_HOST" || -n "$DEST_USER" ]]; then
  [[ -n "$DEST_HOST" && -n "$DEST_USER" ]] || die "informe --dest-host e --dest-user juntos"
  [[ -n "$DEST_PATH" ]] || die "informe --dest-path quando usar --dest-host"
fi

DEST_PASSWORD="${DEST_PASSWORD:-${DEST_PASSWORD_ENV:-}}"
OUT_DIR="${OUT_DIR:-$DEFAULT_OUT_DIR}"
MYSQL_BIN="${MYSQL_BIN:-mysql}"

command -v awk >/dev/null 2>&1 || die "awk nao encontrado"
command -v scp >/dev/null 2>&1 || die "scp nao encontrado"
if [[ "$SOURCE_MODE" == "mysql" ]]; then
  command -v "$MYSQL_BIN" >/dev/null 2>&1 || die "mysql nao encontrado; use --mysql-bin CAMINHO"
  if [[ -n "$ENV_FILE" && ! -f "$ENV_FILE" ]]; then
    die "arquivo .env nao encontrado: $ENV_FILE"
  fi
fi
if [[ -n "$DEST_PASSWORD" ]]; then
  command -v expect >/dev/null 2>&1 || die "expect nao encontrado; necessario quando usa senha"
fi

remote_quote() {
  printf '%q' "$1"
}

run_ssh() {
  local host="$1"
  local user="$2"
  local port="$3"
  local password="$4"
  local remote_command="$5"
  local target="${user}@${host}"

  if [[ -z "$password" ]]; then
    ssh -v -p "$port" "$target" "$remote_command"
    return
  fi

  REMOTE_PORT="$port" \
  REMOTE_TARGET="$target" \
  REMOTE_PASSWORD="$password" \
  REMOTE_COMMAND="$remote_command" \
  expect <<'EOF'
set timeout -1
spawn ssh -v -p $env(REMOTE_PORT) $env(REMOTE_TARGET) $env(REMOTE_COMMAND)
expect {
  -re "(?i)are you sure you want to continue connecting" {
    send -- "yes\r"
    exp_continue
  }
  -re "(?i)password:" {
    send -- "$env(REMOTE_PASSWORD)\r"
    exp_continue
  }
  eof
}
catch wait result
exit [lindex $result 3]
EOF
}

run_scp_upload() {
  local host="$1"
  local user="$2"
  local port="$3"
  local password="$4"
  local local_path="$5"
  local remote_path="$6"
  local target="${user}@${host}"

  if [[ -z "$password" ]]; then
    scp -v -P "$port" -p "$local_path" "${target}:${remote_path}"
    return
  fi

  REMOTE_PORT="$port" \
  REMOTE_TARGET="$target" \
  REMOTE_PASSWORD="$password" \
  REMOTE_PATH="$remote_path" \
  LOCAL_PATH="$local_path" \
  expect <<'EOF'
set timeout -1
spawn scp -v -P $env(REMOTE_PORT) -p "$env(LOCAL_PATH)" "$env(REMOTE_TARGET):$env(REMOTE_PATH)"
expect {
  -re "(?i)are you sure you want to continue connecting" {
    send -- "yes\r"
    exp_continue
  }
  -re "(?i)password:" {
    send -- "$env(REMOTE_PASSWORD)\r"
    exp_continue
  }
  eof
}
catch wait result
exit [lindex $result 3]
EOF
}

extract_stamp() {
  local base
  base="$(basename "$1")"
  if [[ "$base" =~ ([0-9]{14}) ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
  else
    date '+%Y%m%d%H%M%S'
  fi
}

remote_output_path() {
  local dest_path="$1"
  local local_file="$2"
  if [[ "$dest_path" == */ ]]; then
    printf '%s%s\n' "$dest_path" "$(basename "$local_file")"
  else
    printf '%s\n' "$dest_path"
  fi
}

remote_dir_for() {
  local remote_path="$1"
  if [[ "$remote_path" == */ ]]; then
    printf '%s\n' "${remote_path%/}"
  else
    dirname "$remote_path"
  fi
}

latest_stock_file() {
  local dir="$1"
  local file
  local latest=""
  [[ -d "$dir" ]] || die "pasta de origem nao encontrada: $dir"

  while IFS= read -r -d '' file; do
    if [[ -z "$latest" || "$file" -nt "$latest" ]]; then
      latest="$file"
    fi
  done < <(find "$dir" -maxdepth 1 -type f -name 'estoque_*.csv' -print0)
  printf '%s\n' "$latest"
}

load_mysql_env() {
  if [[ -n "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
  fi

  : "${MYSQL_HOST:?MYSQL_HOST nao configurado}"
  : "${MYSQL_PORT:=3306}"
  : "${MYSQL_USER:?MYSQL_USER nao configurado}"
  : "${MYSQL_PASSWORD:?MYSQL_PASSWORD nao configurado}"
  : "${MYSQL_DATABASE:?MYSQL_DATABASE nao configurado}"
}

write_mysql_defaults_file() {
  local path="$1"
  umask 077
  cat > "$path" <<EOF
[client]
host=${MYSQL_HOST}
port=${MYSQL_PORT}
user=${MYSQL_USER}
password=${MYSQL_PASSWORD}
database=${MYSQL_DATABASE}
EOF
}

export_from_mysql() {
  local output_file="$1"
  local defaults_file="$2"
  local query

  query="
SELECT CONCAT(
  nro_loja, ';',
  cod_mercadoria, ';',
  '', ';',
  '0.0', ';',
  REPLACE(FORMAT(IF(qtd_estoque <> 0, valor_estoque / qtd_estoque, 0), 2), ',', ''), ';',
  REPLACE(FORMAT(IF(qtd_estoque <> 0, valor_estoque / qtd_estoque, 0), 4), ',', ''), ';',
  TRIM(TRAILING '.' FROM TRIM(TRAILING '0' FROM CAST(ROUND(qtd_estoque, 3) AS CHAR))), ';',
  '\"\"', ';',
  '\"\"', ';',
  '0', ';',
  '1', ';'
)
FROM ${MYSQL_VIEW}
WHERE nro_loja = ${STORE}
ORDER BY cod_mercadoria;
"

  {
    printf '%s\n' 'CODIGO_LOJA;CODIGO_ARTIGO;PRECO_VENDA_ATUAL;PRECO_VENDA_PROMOCAO;CUSTO_ULTIMA_ENTRADA;CUSTO_MEDIO;ESTOQUE_ATUAL;ESTOQUE_MINIMO;ESTOQUE_MAXIMO;STATUS_COMPRA;STATUS_VENDA;QTD_MAX_PEDIDO_TRANSF'
    "$MYSQL_BIN" --defaults-extra-file="$defaults_file" --batch --raw --skip-column-names -e "$query"
  } > "$output_file"
}

if [[ "$SOURCE_MODE" == "file" ]]; then
  if [[ -z "$SOURCE_PATH" ]]; then
    SOURCE_PATH="$(latest_stock_file "$SOURCE_DIR")"
  fi
  [[ -n "$SOURCE_PATH" ]] || die "nenhum arquivo estoque_*.csv encontrado em $SOURCE_DIR"
  [[ -f "$SOURCE_PATH" ]] || die "arquivo de origem nao encontrado: $SOURCE_PATH"
  STAMP="$(extract_stamp "$SOURCE_PATH")"
else
  STAMP="$(date '+%Y%m%d%H%M%S')"
fi
mkdir -p "$OUT_DIR"
if [[ -z "$OUTPUT_FILE" ]]; then
  OUTPUT_FILE="${OUT_DIR}/MERCADORIA_FILIAL_${STAMP}.csv"
fi

TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mercadoria_filial.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT HUP INT TERM

if [[ "$SOURCE_MODE" == "mysql" ]]; then
  MYSQL_DEFAULTS_FILE="${TMP_DIR}/mysql.cnf"
  load_mysql_env
  write_mysql_defaults_file "$MYSQL_DEFAULTS_FILE"
  log "Consultando MySQL ${MYSQL_USER}@${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_DATABASE}, view ${MYSQL_VIEW}, loja ${STORE}"
  export_from_mysql "$OUTPUT_FILE" "$MYSQL_DEFAULTS_FILE"
else
  log "Convertendo estoque para MERCADORIA_FILIAL da loja ${STORE}: ${SOURCE_PATH}"
  awk -F';' -v OFS=';' -v store="$STORE" '
function dec(v) {
  gsub(/^[ \t\r\n]+|[ \t\r\n]+$/, "", v)
  gsub(/,/, ".", v)
  if (v == "" || v == "\"\"") return 0
  return v + 0
}
function trim(v) {
  gsub(/^[ \t\r\n]+|[ \t\r\n]+$/, "", v)
  return v
}
function qtyfmt(v, s) {
  s = sprintf("%.3f", v)
  sub(/\.?0+$/, "", s)
  if (s == "-0") s = "0"
  return s
}
function moneyfmt(v) {
  return sprintf("%.2f", v)
}
NR == 1 {
  for (i = 1; i <= NF; i++) col[$i] = i
  required = "nro_loja codigo_interno valor_estoque qtd_estoque"
  split(required, req, " ")
  for (i in req) {
    if (!(req[i] in col)) {
      printf("Coluna obrigatoria ausente: %s\n", req[i]) > "/dev/stderr"
      exit 64
    }
  }
  print "CODIGO_LOJA","CODIGO_ARTIGO","PRECO_VENDA_ATUAL","PRECO_VENDA_PROMOCAO","CUSTO_ULTIMA_ENTRADA","CUSTO_MEDIO","ESTOQUE_ATUAL","ESTOQUE_MINIMO","ESTOQUE_MAXIMO","STATUS_COMPRA","STATUS_VENDA","QTD_MAX_PEDIDO_TRANSF"
  next
}
trim($col["nro_loja"]) == store {
  qtd = dec($col["qtd_estoque"])
  valor = dec($col["valor_estoque"])
  custo = 0
  if (qtd != 0) custo = valor / qtd
  printf "%s;%s;;0.0;%s;%s;%s;\"\";\"\";0;1;\n", store, trim($col["codigo_interno"]), moneyfmt(custo), sprintf("%.4f", custo), qtyfmt(qtd)
  count++
}
END {
  if (NR > 0) printf("%d\n", count + 0) > count_file
}
' count_file="${TMP_DIR}/count.txt" "$SOURCE_PATH" > "$OUTPUT_FILE"
fi

ROWS="$(( $(wc -l < "$OUTPUT_FILE" | tr -d ' ') - 1 ))"
log "Arquivo gerado: ${OUTPUT_FILE}"
log "Linhas da loja ${STORE}: ${ROWS}"

if [[ -n "$DEST_HOST" ]]; then
  FINAL_REMOTE_PATH="$(remote_output_path "$DEST_PATH" "$OUTPUT_FILE")"
  FILE_SIZE="$(wc -c < "$OUTPUT_FILE" | tr -d ' ')"
  log "Preparando SCP"
  log "Arquivo local: ${OUTPUT_FILE} (${FILE_SIZE} bytes)"
  log "Destino remoto: ${DEST_USER}@${DEST_HOST}:${FINAL_REMOTE_PATH}"
  if [[ "$CREATE_DEST_DIR" == "1" ]]; then
    DEST_DIR="$(remote_dir_for "$FINAL_REMOTE_PATH")"
    log "Criando diretorio remoto ${DEST_USER}@${DEST_HOST}:${DEST_DIR}"
    run_ssh "$DEST_HOST" "$DEST_USER" "$DEST_PORT" "$DEST_PASSWORD" "mkdir -p $(remote_quote "$DEST_DIR")"
  fi
  log "Copiando para ${DEST_USER}@${DEST_HOST}:${FINAL_REMOTE_PATH}"
  run_scp_upload "$DEST_HOST" "$DEST_USER" "$DEST_PORT" "$DEST_PASSWORD" "$OUTPUT_FILE" "$FINAL_REMOTE_PATH"
  log "Copia finalizada"
fi
