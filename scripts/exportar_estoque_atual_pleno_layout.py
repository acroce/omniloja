#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "recebidos_servidor"
DEFAULT_LOJAS_FILE = ROOT / "config" / "pleno_stock_audit_lojas.txt"
HEADER = [
    "nro_loja",
    "codigo_interno",
    "valor_estoque",
    "valor_imposto_estoque",
    "unidade_medida",
    "qtd_estoque",
    "quilos_estoque",
    "volumes_estoque",
    "data",
    "qtd_pedido_pendente",
    "data_carga",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Exporta estoque oficial atual do Pleno no layout estoque_YYYYMMDDHHMMSS.csv."
    )
    parser.add_argument("--all-lojas", action="store_true", help="Exporta todas as lojas encontradas na view.")
    parser.add_argument("--lojas", default="", help="Lojas separadas por virgula. Se omitido, usa --lojas-file.")
    parser.add_argument("--lojas-file", type=Path, default=DEFAULT_LOJAS_FILE)
    parser.add_argument("--out-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--workers", type=int, default=8)
    return parser.parse_args()


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def decimal_value(value: object) -> Decimal:
    return Decimal(str(value or "0"))


def format_quantity(value: object) -> str:
    number = decimal_value(value).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return format(number, "f").rstrip("0").rstrip(".") or "0"


def format_money(value: object) -> str:
    return format(decimal_value(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")


def parse_stores(value: str) -> list[int]:
    stores: set[int] = set()
    for item in value.replace("\n", ",").replace(" ", ",").split(","):
        item = item.strip()
        if not item or item.startswith("#"):
            continue
        stores.add(int(item))
    return sorted(stores)


def configured_stores(lojas: str, lojas_file: Path) -> list[int]:
    if lojas.strip():
        return parse_stores(lojas)
    if not lojas_file.exists():
        raise SystemExit(f"Arquivo de lojas nao encontrado: {lojas_file}")
    cleaned_lines = []
    for line in lojas_file.read_text(encoding="utf-8").splitlines():
        cleaned = line.split("#", 1)[0].strip()
        if cleaned:
            cleaned_lines.append(cleaned)
    stores = parse_stores(",".join(cleaned_lines))
    if not stores:
        raise SystemExit(f"Nenhuma loja configurada em {lojas_file}")
    return stores


def fetch_all_store_numbers(env: dict[str, str]) -> list[int]:
    import pymysql

    conn = pymysql.connect(
        host=env["MYSQL_HOST"],
        port=int(env.get("MYSQL_PORT", "3306")),
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        database=env["MYSQL_DATABASE"],
        charset="latin1",
        connect_timeout=20,
        read_timeout=120,
        write_timeout=120,
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                    SELECT cfg06_numero AS nro_loja
                    FROM cfg06_filial
                    WHERE cfg06_numero IS NOT NULL
                    ORDER BY cfg06_numero
                """
            )
            return [int(row["nro_loja"]) for row in cur.fetchall()]
    finally:
        conn.close()


def fetch_store(env: dict[str, str], store: int) -> list[dict[str, object]]:
    import pymysql

    for attempt in range(3):
        conn = None
        cur = None
        try:
            conn = pymysql.connect(
                host=env["MYSQL_HOST"],
                port=int(env.get("MYSQL_PORT", "3306")),
                user=env["MYSQL_USER"],
                password=env["MYSQL_PASSWORD"],
                database=env["MYSQL_DATABASE"],
                charset="latin1",
                connect_timeout=20,
                read_timeout=120,
                write_timeout=120,
                cursorclass=pymysql.cursors.SSDictCursor,
            )
            cur = conn.cursor()
            cur.execute(
                """
                    SELECT
                        nro_loja,
                        cod_mercadoria,
                        valor_estoque,
                        valor_imposto_estoque,
                        unidade_medida,
                        qtd_estoque,
                        data_estoque,
                        qtd_pedido_pendente,
                        data_carga
                    FROM view_dia_estoque_loja
                    WHERE nro_loja = %s
                """,
                (store,),
            )
            rows = []
            for row in cur:
                quantity = format_quantity(row["qtd_estoque"])
                rows.append(
                    {
                        "nro_loja": row["nro_loja"],
                        "codigo_interno": row["cod_mercadoria"],
                        "valor_estoque": format_money(row["valor_estoque"]),
                        "valor_imposto_estoque": row["valor_imposto_estoque"] or "",
                        "unidade_medida": row["unidade_medida"] or "",
                        "qtd_estoque": quantity,
                        "quilos_estoque": quantity,
                        "volumes_estoque": quantity,
                        "data": row["data_estoque"] or "",
                        "qtd_pedido_pendente": format_quantity(row["qtd_pedido_pendente"]),
                        "data_carga": row["data_carga"] or "",
                    }
                )
            return rows
        except (pymysql.err.OperationalError, AttributeError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
        finally:
            if cur is not None:
                try:
                    cur.close()
                except Exception:
                    pass
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    raise RuntimeError(f"Nao foi possivel extrair a loja {store}")


def main() -> None:
    args = parse_args()
    sys.path.insert(0, str(ROOT / ".python_packages"))
    import pymysql

    env = load_env()
    created_at = datetime.now()
    stamp = created_at.strftime("%Y%m%d%H%M%S")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.out_dir / f"estoque_{stamp}.csv"
    manifest_path = args.out_dir / f"manifest_estoque_{stamp}.json"

    rows_written = 0
    stores = fetch_all_store_numbers(env) if args.all_lojas else configured_stores(args.lojas, args.lojas_file)
    if not stores:
        raise SystemExit("Nenhuma loja encontrada para exportar.")
    with output_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=HEADER, delimiter=";")
        writer.writeheader()
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            futures = [executor.submit(fetch_store, env, store) for store in stores]
            for future in as_completed(futures):
                rows = future.result()
                writer.writerows(rows)
                rows_written += len(rows)

    manifest_path.write_text(
        json.dumps(
            {
                "generated_at": created_at.isoformat(sep=" ", timespec="seconds"),
                "source": "view_dia_estoque_loja",
                "stores": stores,
                "rows": rows_written,
                "file": str(output_path),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"arquivo: {output_path}")
    print(f"linhas: {rows_written}")
    print(f"manifest: {manifest_path}")


if __name__ == "__main__":
    main()
