#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, ".python_packages")


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "outputs" / "pleno_stock_snapshots"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Exporta um retrato do estoque atual do Pleno para lojas configuradas."
    )
    parser.add_argument("--lojas", help="Lista de lojas separadas por virgula.")
    parser.add_argument(
        "--label",
        default="snapshot",
        help="Rotulo da coleta, exemplo: 0600, 1030, pos_inventario.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Diretorio base de saida. Padrao: {DEFAULT_OUT_DIR}",
    )
    return parser.parse_args()


def parse_lojas(value: str | None) -> list[int]:
    if not value:
        return []
    lojas = []
    for item in value.split(","):
        item = item.strip()
        if item:
            lojas.append(int(item))
    return lojas


def load_env() -> dict[str, str]:
    env = dict(os.environ)
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            env[key] = value.strip().strip('"').strip("'")
    return env


def normalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return value


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def fetch_snapshot(conn: Any, lojas: list[int]) -> list[dict[str, Any]]:
    params: list[Any] = []
    loja_sql = ""
    if lojas:
        params.extend(lojas)
        loja_sql = "AND f.cfg06_numero IN (" + ", ".join(["%s"] * len(lojas)) + ")"

    sql = f"""
        SELECT
            f.cfg06_numero AS loja,
            f.cfg06_nome AS nome_loja,
            m.mcd01_codint AS sku,
            LEFT(COALESCE(m.mcd01_descricao_curta, m.mcd01_descricao), 120) AS descricao,
            ROUND(e.est06_qtd, 3) AS qtd_atual,
            e.est06_data AS data_saldo,
            ROUND(e.est06_vlrcusto_medio, 4) AS custo_medio,
            ROUND(e.est06_qtd * e.est06_vlrcusto_medio, 2) AS valor_custo,
            e.mcd03_mercadoria_filial_id AS mercadoria_filial_id
        FROM est06_estoque_atual e
        JOIN mcd03_mercadoria_filial mf ON mf.mcd03_id = e.mcd03_mercadoria_filial_id
        JOIN cfg06_filial f ON f.cfg06_id = mf.cfg06_filial_id
        JOIN mcd01_mercadoria m ON m.mcd01_id = mf.mcd01_mercadoria_id
        WHERE 1 = 1
          {loja_sql}
        ORDER BY f.cfg06_numero, m.mcd01_codint
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [{key: normalize(value) for key, value in row.items()} for row in cur.fetchall()]


def main() -> None:
    args = parse_args()
    import pymysql

    lojas = parse_lojas(args.lojas)
    env = load_env()
    collected_at = datetime.now()
    stamp = collected_at.strftime("%Y-%m-%d_%H%M%S")
    safe_label = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in args.label)
    run_name = f"{stamp}_{safe_label}"
    if lojas:
        run_name = f"{run_name}_lojas_{'-'.join(map(str, lojas))}"
    out_dir = args.out_dir / run_name
    out_dir.mkdir(parents=True, exist_ok=True)

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
        rows = fetch_snapshot(conn, lojas)
    finally:
        conn.close()

    csv_path = out_dir / "estoque_atual_snapshot.csv"
    write_csv(csv_path, rows)
    manifest = {
        "type": "stock_snapshot",
        "generated_at": collected_at.isoformat(sep=" ", timespec="seconds"),
        "label": args.label,
        "lojas": lojas or "todas",
        "files": {
            "estoque_atual_snapshot": {
                "path": str(csv_path),
                "rows": len(rows),
            }
        },
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"estoque_atual_snapshot: {len(rows)} linha(s)")
    print(f"manifest: {manifest_path}")


if __name__ == "__main__":
    main()
