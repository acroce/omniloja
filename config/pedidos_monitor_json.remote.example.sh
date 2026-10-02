#!/usr/bin/env sh
set -eu

# Script para rodar no servidor Pleno via SSH.
# Ele imprime JSON para o NOC gravar em outputs/pleno_business_monitor/pedidos.json.

now="$(date -Iseconds)"
pedido_dir="${PEDIDOS_DIR:-/servpleno/importacao}"
export_dir="${PEDIDOS_EXPORT_DIR:-/servpleno/exportacao}"
processed_dir="${PEDIDOS_PROCESSED_DIR:-/servpleno/exportacao/processados}"
yyyymmdd="${PEDIDOS_DATE:-$(date +%Y%m%d)}"
mysql_command="${PEDIDOS_MYSQL_COMMAND:-mysql --batch --raw --skip-column-names}"

pedido_suffix="PEDIDO_${yyyymmdd}*.csv"
item_suffix="PEDIDO_ITEM_${yyyymmdd}*.csv"
relex_pedido_pattern="PEDIDO_RET_${yyyymmdd}??????.csv"
relex_item_pattern="PEDIDO_ITEM_RET_${yyyymmdd}??????.csv"

json_escape() {
  sed 's/\\/\\\\/g; s/"/\\"/g' | tr '\n' ' '
}

file_mtime_iso() {
  file="$1"
  if [ -f "$file" ]; then
    if stat -c %Y "$file" >/dev/null 2>&1; then
      date -Iseconds -d "@$(stat -c %Y "$file")"
    else
      date -r "$file" -Iseconds
    fi
  fi
}

file_ctime_iso() {
  file="$1"
  if [ -f "$file" ]; then
    if stat -c %Z "$file" >/dev/null 2>&1; then
      date -Iseconds -d "@$(stat -c %Z "$file")"
    else
      date -r "$file" -Iseconds
    fi
  fi
}

find_first() {
  pattern="$1"
  find "$pedido_dir" -maxdepth 1 -type f -name "$pattern" 2>/dev/null | sort | head -n 1
}

find_best() {
  pattern="$1"
  # Imported files may already be in pedido_processado.
  find "$pedido_dir" -maxdepth 2 -type f -name "$pattern" 2>/dev/null | while IFS= read -r file; do
    lines="$(wc -l < "$file" | tr -d ' ')"
    printf '%010d %s\n' "$lines" "$file"
  done | sort -rn | head -n 1 | cut -d' ' -f2-
}

find_first_in_dir() {
  dir="$1"
  pattern="$2"
  find "$dir" -maxdepth 1 -type f -name "$pattern" 2>/dev/null | sort | head -n 1
}

latest_time() {
  first="$1"
  second="$2"
  first_time="$(file_mtime_iso "$first" || true)"
  second_time="$(file_mtime_iso "$second" || true)"
  if [ -n "$first_time" ] && [ -n "$second_time" ]; then
    if [ "$first_time" \> "$second_time" ]; then
      echo "$first_time"
    else
      echo "$second_time"
    fi
  fi
}

latest_change_time() {
  first="$1"
  second="$2"
  first_time="$(file_ctime_iso "$first" || true)"
  second_time="$(file_ctime_iso "$second" || true)"
  if [ -n "$first_time" ] && [ -n "$second_time" ]; then
    if [ "$first_time" \> "$second_time" ]; then
      echo "$first_time"
    else
      echo "$second_time"
    fi
  fi
}

file_imp_time_iso() {
  file="$1"
  name="$(basename "$file")"
  stamp="$(printf '%s' "$name" | sed -n 's/^imp\.\([0-9]\{12\}\|[0-9]\{14\}\)\..*/\1/p')"
  [ -n "$stamp" ] || return 0
  formatted="$(printf '%s' "$stamp" | sed -n 's/^\([0-9]\{4\}\)\([0-9]\{2\}\)\([0-9]\{2\}\)\([0-9]\{2\}\)\([0-9]\{2\}\)\([0-9]\{2\}\)$/\1-\2-\3 \4:\5:\6/p; s/^\([0-9]\{4\}\)\([0-9]\{2\}\)\([0-9]\{2\}\)\([0-9]\{2\}\)\([0-9]\{2\}\)$/\1-\2-\3 \4:\5:00/p')"
  [ -n "$formatted" ] && date -Iseconds -d "$formatted"
}

latest_imp_time() {
  first="$1"
  second="$2"
  first_time="$(file_imp_time_iso "$first" || true)"
  second_time="$(file_imp_time_iso "$second" || true)"
  if [ -n "$first_time" ] && [ -n "$second_time" ]; then
    if [ "$first_time" \> "$second_time" ]; then echo "$first_time"; else echo "$second_time"; fi
  elif [ -n "$first_time" ]; then
    echo "$first_time"
  elif [ -n "$second_time" ]; then
    echo "$second_time"
  else
    latest_change_time "$first" "$second"
  fi
}

event_for_pair() {
  event_id="$1"
  target_time="$2"
  pedido_pattern="$3"
  item_pattern="$4"
  label="$5"

  pedido_file="$(find_first "$pedido_pattern" || true)"
  item_file="$(find_first "$item_pattern" || true)"
  count=0
  missing=""

  if [ -n "$pedido_file" ]; then count=$((count + 1)); else missing="$pedido_pattern"; fi
  if [ -n "$item_file" ]; then count=$((count + 1)); else missing="${missing}${missing:+, }$item_pattern"; fi

  if [ "$count" -eq 2 ]; then
    actual_at="$(latest_time "$pedido_file" "$item_file")"
    details="$label OK. Arquivos: $(basename "$pedido_file"), $(basename "$item_file")"
  else
    actual_at=""
    details="$label pendente. Faltando: $missing"
    forced_status=""
  fi

  details_json="$(printf '%s' "$details" | json_escape)"
  source_json="$(printf '%s' "$pedido_dir" | json_escape)"

  cat <<JSON
    "$event_id": {
      "targetTime": "$target_time",
      "actualAt": "$actual_at",
      "count": $count,
      "source": "$source_json",
      "details": "$details_json"
    }
JSON
}

# This embedded selector is generated from scripts/select_pedidos_files.py.
# Both file stages and the database comparison select the same type-3 execution.
selection="$(python3 - "$pedido_dir" "$yyyymmdd" shell 3 <<'PYSELECT'
"""Read-only selection shared by the remote file stages and Pleno comparison."""
import csv
import io
import json
import re
import shlex
import sys
from pathlib import Path


def select_pair(directory, day, order_type=3):
    root = Path(directory)
    paths = [p for folder in (root, root / 'pedido_processado') if folder.is_dir() for p in folder.iterdir() if p.is_file()]
    pattern = re.compile(r'^(?:imp\.[^.]+\.)?PEDIDO_(' + re.escape(day) + r'\d{6})\.csv$')
    candidates = []
    for p in paths:
        match = pattern.match(p.name)
        if not match:
            continue
        with p.open(encoding='utf-8-sig', errors='replace', newline='') as f:
            rows = list(csv.DictReader(f, delimiter=';'))
        typed = [r for r in rows if str(r.get('TIPO_PEDIDO', '')).strip() == str(order_type)]
        if typed:
            candidates.append((match.group(1), p, typed))
    empty = dict(original_pedido_file='', original_item_file='', imp_pedido_file='', imp_item_file='')
    if not candidates:
        return empty, None, []
    # The daily timeline represents the first execution of the scheduled run.
    # A later retry must not replace a batch that was already imported and reconciled.
    execution, selected, rows = min(
        candidates,
        key=lambda x: (x[0], x[1].name.startswith('imp.'), str(x[1])),
    )
    def find(kind, imported):
        suffix = f'{kind}_{execution}.csv'
        matching = [p for p in paths if (p.name.endswith('.' + suffix) and p.name.startswith('imp.'))] if imported else [p for p in paths if p.name == suffix]
        return str(max(matching, key=lambda p: (p.stat().st_mtime_ns, str(p)))) if matching else ''
    result = dict(original_pedido_file=find('PEDIDO', False), original_item_file=find('PEDIDO_ITEM', False), imp_pedido_file=find('PEDIDO', True), imp_item_file=find('PEDIDO_ITEM', True))
    return result, selected, rows


def main():
    directory, day, mode = sys.argv[1:4]
    order_type = int(sys.argv[4]) if len(sys.argv) > 4 else 3
    pair, selected, rows = select_pair(directory, day, order_type)
    if mode == 'shell':
        for k, v in pair.items():
            print(k + '=' + shlex.quote(v))
    elif mode == 'content':
        print('__PEDIDOS_FILE__=' + (selected.name if selected else ''))
        if selected:
            out = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]), delimiter=';', lineterminator='\n')
            out.writeheader()
            out.writerows(rows)
    else:
        print(json.dumps({'pair': pair, 'selected': str(selected) if selected else None, 'type': order_type, 'rows': len(rows)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
PYSELECT
)"
eval "$selection"

pair_event_from_files() {
  event_id="$1"
  target_time="$2"
  pedido_file="$3"
  item_file="$4"
  pedido_pattern="$5"
  item_pattern="$6"
  label="$7"
  fallback_label="${8:-}"
  forced_status="${9:-}"
  time_kind="${10:-mtime}"

  count=0
  missing=""
  if [ -n "$pedido_file" ]; then count=$((count + 1)); else missing="$pedido_pattern"; fi
  if [ -n "$item_file" ]; then count=$((count + 1)); else missing="${missing}${missing:+, }$item_pattern"; fi

  if [ "$count" -eq 2 ]; then
    if [ "$time_kind" = "imp" ]; then
      actual_at="$(latest_imp_time "$pedido_file" "$item_file")"
    elif [ "$time_kind" = "ctime" ]; then
      actual_at="$(latest_change_time "$pedido_file" "$item_file")"
    else
      actual_at="$(latest_time "$pedido_file" "$item_file")"
    fi
    if [ -n "$fallback_label" ]; then
      details="$label OK por $fallback_label. Arquivos: $(basename "$pedido_file"), $(basename "$item_file")"
    else
      details="$label OK. Arquivos: $(basename "$pedido_file"), $(basename "$item_file")"
    fi
  else
    actual_at=""
    details="$label pendente. Faltando: $missing"
    forced_status=""
  fi

  details_json="$(printf '%s' "$details" | json_escape)"
  source_json="$(printf '%s' "$pedido_dir" | json_escape)"

  cat <<JSON
    "$event_id": {
      "targetTime": "$target_time",
      "status": "$forced_status",
      "actualAt": "$actual_at",
      "count": $count,
      "source": "$source_json",
      "details": "$details_json"
    }
JSON
}

pair_event_from_files_with_source() {
  event_id="$1"
  target_time="$2"
  pedido_file="$3"
  item_file="$4"
  pedido_pattern="$5"
  item_pattern="$6"
  label="$7"
  source_dir="$8"
  forced_status="${9:-}"
  time_kind="${10:-mtime}"

  count=0
  missing=""
  if [ -n "$pedido_file" ]; then count=$((count + 1)); else missing="$pedido_pattern"; fi
  if [ -n "$item_file" ]; then count=$((count + 1)); else missing="${missing}${missing:+, }$item_pattern"; fi

  if [ "$count" -eq 2 ]; then
    if [ "$time_kind" = "imp" ]; then
      actual_at="$(latest_imp_time "$pedido_file" "$item_file")"
    elif [ "$time_kind" = "ctime" ]; then
      actual_at="$(latest_change_time "$pedido_file" "$item_file")"
    else
      actual_at="$(latest_time "$pedido_file" "$item_file")"
    fi
    details="$label OK. Arquivos: $(basename "$pedido_file"), $(basename "$item_file")"
  else
    actual_at=""
    details="$label pendente. Faltando: $missing"
    forced_status=""
  fi

  details_json="$(printf '%s' "$details" | json_escape)"
  source_json="$(printf '%s' "$source_dir" | json_escape)"

  cat <<JSON
    "$event_id": {
      "targetTime": "$target_time",
      "status": "$forced_status",
      "actualAt": "$actual_at",
      "count": $count,
      "source": "$source_json",
      "details": "$details_json"
    }
JSON
}

mysql_pedidos_event() {
  sql_file="$(mktemp)"
  out_file="$(mktemp)"
  err_file="$(mktemp)"
  cat > "$sql_file" <<'SQL'
WITH pedidos AS (
    SELECT
        com16_id,
        cfg06_filial_dest_id,
        com16_nro_pedtransf_trd,
        com16_flgatendido_trd,
        com16_dthr
    FROM pleno.com16_pretransferencia
    WHERE com16_dthr >= CURDATE() - INTERVAL 7 DAY
      AND dom83_tipo_pedtransf_id = 3
),
status_pedido AS (
    SELECT
        a.com16_pretransferencia_id,
        MAX(f.fis01_nronf) AS nr_nota_pedido,
        MAX(e.fis02_notafiscal_item_id) AS item_nf_pedido
    FROM pedidos b
    INNER JOIN pleno.com19_pretransferencia_item a
        ON a.com16_pretransferencia_id = b.com16_id
    LEFT JOIN pleno.com33_pedtransf_atendido d
        ON d.com19_pretransferencia_item_id = a.com19_id
    LEFT JOIN pleno.fis25_notafiscal_item_fisico e
        ON e.fis25_id = d.fis25_notafiscal_item_fisico_id
    LEFT JOIN pleno.fis01_notafiscal f
        ON f.fis01_id = e.fis01_notafiscal_id
    GROUP BY
       a.com16_pretransferencia_id
),
detalhe AS (
    SELECT
       c.cfg06_numero AS Loja,
       c.cfg06_nome AS Nome_loja,
       b.com16_nro_pedtransf_trd AS Pedido,
       b.com16_flgatendido_trd AS Atendido,
       b.com16_dthr AS Dt_Pedido,
       g.mcd01_codint AS SKU,
       g.mcd01_descricao_curta AS Descri,
       a.com19_qtd AS qtde_ped,
       a.com19_qtd_confirmada AS qtde_conf_ped,
       e.fis25_qtd_nf AS qtde_nota,
       COALESCE(f.fis01_nronf, sp.nr_nota_pedido) AS nr_nota,
       COALESCE(e.fis02_notafiscal_item_id, sp.item_nf_pedido) AS fis02_notafiscal_item_id,
       CASE
           WHEN sp.item_nf_pedido IS NOT NULL THEN 'Entrada realizada'
           ELSE 'Pendente Entrada'
       END AS Situacao
    FROM pedidos b
    INNER JOIN pleno.com19_pretransferencia_item a
        ON a.com16_pretransferencia_id = b.com16_id
    INNER JOIN pleno.cfg06_filial c
        ON c.cfg06_id = b.cfg06_filial_dest_id
    LEFT JOIN pleno.com33_pedtransf_atendido d
        ON d.com19_pretransferencia_item_id = a.com19_id
    LEFT JOIN pleno.fis25_notafiscal_item_fisico e
        ON e.fis25_id = d.fis25_notafiscal_item_fisico_id
    LEFT JOIN pleno.fis01_notafiscal f
        ON f.fis01_id = e.fis01_notafiscal_id
    LEFT JOIN pleno.mcd01_mercadoria g
        ON g.mcd01_id = a.mcd01_mercadoria_id
    LEFT JOIN status_pedido sp
        ON sp.com16_pretransferencia_id = b.com16_id
    WHERE b.com16_dthr >= '2026-07-02'
)
SELECT
    Situacao,
    COUNT(*) AS linhas,
    COUNT(DISTINCT Pedido) AS pedidos,
    COALESCE(SUM(qtde_ped), 0) AS qtde_ped,
    COALESCE(SUM(qtde_nota), 0) AS qtde_nota
FROM detalhe
GROUP BY Situacao
ORDER BY Situacao;
SQL

  if sh -c "$mysql_command < '$sql_file'" > "$out_file" 2> "$err_file"; then
    total_linhas=0
    total_pedidos=0
    entrada_linhas=0
    pendente_linhas=0
    while IFS="$(printf '\t')" read -r situacao linhas pedidos qtde_ped qtde_nota; do
      [ -n "${situacao:-}" ] || continue
      linhas="${linhas:-0}"
      pedidos="${pedidos:-0}"
      total_linhas=$((total_linhas + linhas))
      total_pedidos=$((total_pedidos + pedidos))
      if [ "$situacao" = "Entrada realizada" ]; then
        entrada_linhas=$linhas
      elif [ "$situacao" = "Pendente Entrada" ]; then
        pendente_linhas=$linhas
      fi
    done < "$out_file"
    details="MySQL OK. Linhas: $total_linhas. Pedidos: $total_pedidos. Entrada realizada: $entrada_linhas. Pendente Entrada: $pendente_linhas."
    status="ok"
    actual_at="$now"
    count="$total_linhas"
  else
    details="Erro ao executar consulta MySQL: $(cat "$err_file")"
    status="erro"
    actual_at=""
    count=0
  fi

  rm -f "$sql_file" "$out_file" "$err_file"
  details_json="$(printf '%s' "$details" | json_escape)"
  source_json="$(printf '%s' "$mysql_command" | json_escape)"

  cat <<JSON
    "checagem_0805": {
      "targetTime": "08:05",
      "status": "$status",
      "actualAt": "$actual_at",
      "count": $count,
      "source": "$source_json",
      "details": "$details_json"
    }
JSON
}

if [ -n "$original_pedido_file" ] && [ -n "$original_item_file" ]; then
  original_event="$(pair_event_from_files \
    "arquivo_original" \
    "07:55" \
    "$original_pedido_file" \
    "$original_item_file" \
    "$pedido_suffix" \
    "$item_suffix" \
    "Arquivos originais sem imp")"
else
  original_event="$(pair_event_from_files \
    "arquivo_original" \
    "07:55" \
    "$imp_pedido_file" \
    "$imp_item_file" \
    "imp.*.$pedido_suffix" \
    "imp.*.$item_suffix" \
    "Arquivos originais sem imp" \
    "arquivos importados imp" \
    "ok" \
    "imp")"
fi

imp_event="$(pair_event_from_files \
  "arquivo_chegada" \
  "08:10" \
  "$imp_pedido_file" \
  "$imp_item_file" \
  "imp.*.$pedido_suffix" \
  "imp.*.$item_suffix" \
  "Arquivos importados com imp" \
  "" \
  "" \
  "imp")"

relex_export_pedido_file="$(find_first_in_dir "$export_dir" "$relex_pedido_pattern" || true)"
relex_export_item_file="$(find_first_in_dir "$export_dir" "$relex_item_pattern" || true)"
relex_processed_pedido_file="$(find_first_in_dir "$processed_dir" "$relex_pedido_pattern" || true)"
relex_processed_item_file="$(find_first_in_dir "$processed_dir" "$relex_item_pattern" || true)"

if [ -n "$relex_export_pedido_file" ] && [ -n "$relex_export_item_file" ]; then
  relex_event="$(pair_event_from_files_with_source \
    "envio_relex" \
    "09:30" \
    "$relex_export_pedido_file" \
    "$relex_export_item_file" \
    "$relex_pedido_pattern" \
    "$relex_item_pattern" \
    "Arquivo RELEX gerado" \
    "$export_dir" \
    "ok")"
else
  relex_event="$(pair_event_from_files_with_source \
    "envio_relex" \
    "09:30" \
    "$relex_processed_pedido_file" \
    "$relex_processed_item_file" \
    "$relex_pedido_pattern" \
    "$relex_item_pattern" \
    "Arquivo RELEX gerado por evidencia em processados" \
    "$processed_dir" \
    "ok" \
    "mtime")"
fi

relex_processed_event="$(pair_event_from_files_with_source \
  "relex_processados" \
  "09:35" \
  "$relex_processed_pedido_file" \
  "$relex_processed_item_file" \
  "$relex_pedido_pattern" \
  "$relex_item_pattern" \
  "RELEX processado" \
  "$processed_dir" \
  "ok" \
  "ctime")"

cat <<JSON
{
  "collector": "pedidos_monitor_json.remote.sh",
  "updatedAt": "$now",
  "events": {
$original_event,
$imp_event,
$relex_event,
$relex_processed_event
  }
}
JSON
