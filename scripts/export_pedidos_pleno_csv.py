#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".python_packages"))
DEFAULT_OUT_DIR = ROOT / "outputs" / "pedidos_pleno"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Exporta pedidos de transferencia do Pleno em CSV: loja, artigo, quantidade pedida."
    )
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="Data dos pedidos no formato YYYY-MM-DD. Padrao: hoje.",
    )
    parser.add_argument(
        "--lojas",
        help="Lista de lojas separadas por virgula. Se omitido, exporta todas as lojas concluidas na data.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Diretorio de saida. Padrao: {DEFAULT_OUT_DIR}",
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


def parse_lojas(value: str | None) -> list[int]:
    if not value:
        return []
    lojas = []
    for item in value.replace(";", ",").split(","):
        item = item.strip()
        if item:
            lojas.append(int(item))
    return lojas


def normalize_quantity(value: Any) -> Any:
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=["loja", "artigo", "quantidade"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    lojas = parse_lojas(args.lojas)
    env = load_env()

    import pymysql

    loja_sql = ""
    params: list[Any] = [f"{args.date} 00:00:00", f"{args.date} 23:59:59"]
    if lojas:
        placeholders = ", ".join(["%s"] * len(lojas))
        loja_sql = f"AND f_destino.cfg06_numero IN ({placeholders})"
        params.extend(lojas)

    sql = f"""
        SELECT
            f_destino.cfg06_numero AS loja,
            m.mcd01_codint AS artigo,
            ROUND(SUM(i.com19_qtd_confirmada), 3) AS quantidade
        FROM com16_pretransferencia p
        JOIN com19_pretransferencia_item i
            ON i.com16_pretransferencia_id = p.com16_id
        JOIN cfg06_filial f_destino
            ON f_destino.cfg06_id = p.cfg06_filial_dest_id
        JOIN mcd01_mercadoria m
            ON m.mcd01_id = i.mcd01_mercadoria_id
        WHERE p.com16_dthr_importacao_trd BETWEEN %s AND %s
          AND p.dom83_tipo_pedtransf_id = 2
          AND p.com16_dthr_cancelado IS NULL
          {loja_sql}
        GROUP BY f_destino.cfg06_numero, m.mcd01_codint
        HAVING ABS(SUM(i.com19_qtd_confirmada)) > 0.0001
        ORDER BY f_destino.cfg06_numero, m.mcd01_codint
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
            rows = [
                {
                    "loja": row["loja"],
                    "artigo": row["artigo"],
                    "quantidade": normalize_quantity(row["quantidade"]),
                }
                for row in cur.fetchall()
            ]
    finally:
        conn.close()

    lojas_stamp = "-".join(str(loja) for loja in lojas) if lojas else "todas_concluidas"
    out_path = args.out_dir / f"pedidos_pleno_{args.date}_lojas_{lojas_stamp}.csv"
    write_csv(out_path, rows)
    print(f"{len(rows)} linha(s): {out_path}")


if __name__ == "__main__":
    main()
