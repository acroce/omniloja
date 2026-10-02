#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".python_packages"))

DEFAULT_OUT_DIR = ROOT / "outputs" / "pedidos_hoje_pleno"
ORDER_COLUMNS = (
    "NUMERO_PEDIDO",
    "PEDIDO",
    "NRO_PEDIDO",
    "NUM_PEDIDO",
    "COM16_NRO_PEDTRANSF_TRD",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Consulta no Pleno os pedidos feitos na data e filtra arquivos CSV, "
            "mantendo apenas as linhas desses pedidos."
        )
    )
    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="Arquivos CSV/TXT a filtrar. Os originais nao sao alterados.",
    )
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Data dos pedidos no formato YYYY-MM-DD. Padrao: hoje.",
    )
    parser.add_argument(
        "--tipo-pedido",
        type=int,
        help="Filtra tambem pelo dom83_tipo_pedtransf_id. Se omitido, aceita todos os tipos.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Diretorio base de saida. Padrao: {DEFAULT_OUT_DIR}",
    )
    parser.add_argument(
        "--order-column",
        help=(
            "Nome da coluna do numero do pedido. Se omitido, tenta detectar: "
            + ", ".join(ORDER_COLUMNS)
        ),
    )
    return parser.parse_args()


def load_env() -> dict[str, str]:
    env_path = ROOT / ".env"
    if not env_path.exists():
        raise SystemExit(f"Arquivo .env nao encontrado em {env_path}")
    env: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        env[key] = value.strip().strip('"').strip("'")
    return env


def clean_order(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        value = int(value) if value == value.to_integral_value() else value
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def query_pedidos_pleno(env: dict[str, str], day: str, tipo_pedido: int | None) -> list[dict[str, Any]]:
    import pymysql

    params: list[Any] = [f"{day} 00:00:00", f"{day} 23:59:59"]
    tipo_sql = ""
    if tipo_pedido is not None:
        tipo_sql = "AND p.dom83_tipo_pedtransf_id = %s"
        params.append(tipo_pedido)

    sql = f"""
        SELECT
            CAST(p.com16_nro_pedtransf_trd AS CHAR) AS pedido,
            p.dom83_tipo_pedtransf_id AS tipo_pedido,
            f.cfg06_numero AS loja,
            p.com16_dthr AS data_pedido,
            p.com16_dthr_cancelado AS data_cancelado,
            COUNT(i.com19_id) AS itens,
            COALESCE(SUM(i.com19_qtd), 0) AS qtd_pedida,
            COALESCE(SUM(i.com19_qtd_confirmada), 0) AS qtd_confirmada
        FROM pleno.com16_pretransferencia p
        LEFT JOIN pleno.com19_pretransferencia_item i
            ON i.com16_pretransferencia_id = p.com16_id
        LEFT JOIN pleno.cfg06_filial f
            ON f.cfg06_id = p.cfg06_filial_dest_id
        WHERE p.com16_dthr BETWEEN %s AND %s
          AND p.com16_nro_pedtransf_trd IS NOT NULL
          {tipo_sql}
        GROUP BY
            p.com16_nro_pedtransf_trd,
            p.dom83_tipo_pedtransf_id,
            f.cfg06_numero,
            p.com16_dthr,
            p.com16_dthr_cancelado
        ORDER BY p.com16_dthr, p.com16_nro_pedtransf_trd
    """

    conn = pymysql.connect(
        host=env["MYSQL_HOST"],
        port=int(env["MYSQL_PORT"]),
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        database=env["MYSQL_DATABASE"],
        charset="latin1",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = list(cur.fetchall())
    finally:
        conn.close()

    for row in rows:
        row["pedido"] = clean_order(row.get("pedido"))
        for key in ("data_pedido", "data_cancelado"):
            if row.get(key) is not None:
                row[key] = str(row[key])
        for key in ("qtd_pedida", "qtd_confirmada"):
            if isinstance(row.get(key), Decimal):
                row[key] = float(row[key])
    return rows


def detect_dialect(path: Path) -> csv.Dialect:
    sample = path.read_text(encoding="utf-8-sig", errors="replace")[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,|\t")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"
        return dialect


def choose_order_column(fieldnames: list[str], requested: str | None) -> str:
    if requested:
        if requested not in fieldnames:
            raise SystemExit(f"Coluna {requested!r} nao encontrada. Colunas: {fieldnames}")
        return requested

    upper_to_original = {name.upper().strip(): name for name in fieldnames}
    for candidate in ORDER_COLUMNS:
        if candidate in upper_to_original:
            return upper_to_original[candidate]
    raise SystemExit(
        "Nao encontrei coluna de pedido. Informe --order-column. "
        f"Colunas disponiveis: {fieldnames}"
    )


def filter_csv(
    source: Path,
    target: Path,
    pedidos_validos: set[str],
    requested_order_column: str | None,
) -> dict[str, Any]:
    dialect = detect_dialect(source)
    target.parent.mkdir(parents=True, exist_ok=True)

    with source.open("r", encoding="utf-8-sig", errors="replace", newline="") as inp:
        reader = csv.DictReader(inp, dialect=dialect)
        if not reader.fieldnames:
            raise SystemExit(f"Arquivo sem cabecalho: {source}")
        order_column = choose_order_column(reader.fieldnames, requested_order_column)
        rows = [row for row in reader if clean_order(row.get(order_column)) in pedidos_validos]

    with target.open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=reader.fieldnames, dialect=dialect)
        writer.writeheader()
        writer.writerows(rows)

    return {
        "arquivo": str(source),
        "saida": str(target),
        "colunaPedido": order_column,
        "linhasMantidas": len(rows),
    }


def write_pedidos_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "pedido",
        "tipo_pedido",
        "loja",
        "data_pedido",
        "data_cancelado",
        "itens",
        "qtd_pedida",
        "qtd_confirmada",
    ]
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    datetime.strptime(args.date, "%Y-%m-%d")
    env = load_env()

    pedidos = query_pedidos_pleno(env, args.date, args.tipo_pedido)
    pedidos_validos = {row["pedido"] for row in pedidos if row.get("pedido")}
    if not pedidos_validos:
        tipo_msg = f" tipo {args.tipo_pedido}" if args.tipo_pedido is not None else ""
        raise SystemExit(f"Nenhum pedido{tipo_msg} encontrado no Pleno em {args.date}.")

    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.out_dir / f"{args.date}_{run_stamp}"
    write_pedidos_csv(out_dir / "pedidos_pleno_consultados.csv", pedidos)

    relatorio: dict[str, Any] = {
        "geradoEm": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataPedidos": args.date,
        "tipoPedido": args.tipo_pedido,
        "totalPedidosPleno": len(pedidos_validos),
        "arquivos": [],
    }
    for source in args.files:
        if not source.exists():
            raise SystemExit(f"Arquivo nao encontrado: {source}")
        target = out_dir / source.name
        relatorio["arquivos"].append(
            filter_csv(source, target, pedidos_validos, args.order_column)
        )

    report_path = out_dir / "relatorio_filtro_pedidos_hoje.json"
    report_path.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Pedidos no Pleno: {len(pedidos_validos)}")
    print(f"Saida: {out_dir}")
    for item in relatorio["arquivos"]:
        print(f"{Path(item['saida']).name}: {item['linhasMantidas']} linha(s)")


if __name__ == "__main__":
    main()
