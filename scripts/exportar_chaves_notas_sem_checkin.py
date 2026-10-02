#!/usr/bin/env python3
"""Exporta as chaves NF-e das transferencias do CD ainda sem check-in."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"').strip("'")
    return values


def value(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return "" if value is None else str(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--origin-store", type=int, default=704)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    env = load_env()
    sys.path.insert(0, str(ROOT / ".python_packages"))
    import pymysql

    conn = pymysql.connect(
        host=env["MYSQL_HOST"], port=int(env.get("MYSQL_PORT", "3306")),
        user=env["MYSQL_USER"], password=env["MYSQL_PASSWORD"],
        database=env["MYSQL_DATABASE"], charset="latin1",
        cursorclass=pymysql.cursors.DictCursor,
    )
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT
                    nf.fis01_nronf AS nota_fiscal,
                    nf.fis01_serienf AS serie,
                    nf.fis01_nfe_chave AS chave_nfe,
                    nf.fis01_data_emissao AS data_emissao,
                    nf.fis01_data_entrada_saida AS data_entrada_saida,
                    f_destino.cfg06_numero AS loja_destino,
                    f_destino.cfg06_nome AS nome_loja_destino
                FROM fis01_notafiscal nf
                LEFT JOIN pes04_pessoa p_origem ON p_origem.pes04_id = nf.pes04_pessoa_emit
                LEFT JOIN pes03_estabelecimento origem ON origem.pes03_id = p_origem.pes03_estabelecimento_id
                LEFT JOIN cfg06_filial f_origem ON f_origem.pes03_estabelecimento_id = origem.pes03_id
                LEFT JOIN pes04_pessoa p_destino ON p_destino.pes04_id = nf.pes04_pessoa_dest
                LEFT JOIN pes03_estabelecimento destino ON destino.pes03_id = p_destino.pes03_estabelecimento_id
                LEFT JOIN cfg06_filial f_destino ON f_destino.pes03_estabelecimento_id = destino.pes03_id
                WHERE nf.fis01_entrada_saida = 'S'
                  AND COALESCE(nf.fis01_flgcancelada, 0) = 0
                  AND f_origem.cfg06_numero = %s
                  AND f_destino.cfg06_numero < 3000
                  AND nf.adm05_usuario_checkin_id IS NULL
                  AND (
                      (nf.fis01_data_emissao >= %s AND nf.fis01_data_emissao <= %s)
                      OR (nf.fis01_data_entrada_saida >= %s AND nf.fis01_data_entrada_saida <= %s)
                  )
                ORDER BY nf.fis01_data_emissao, nf.fis01_nronf, f_destino.cfg06_numero
                """,
                [args.origin_store, args.start_date, args.end_date, args.start_date, args.end_date],
            )
            rows = [{key: value(item) for key, item in row.items()} for row in cur.fetchall()]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"chaves_nfe_sem_checkin_{args.start_date.replace('-', '')}_{args.end_date.replace('-', '')}"
    detail_path = args.out_dir / f"{stem}.csv"
    keys_path = args.out_dir / f"{stem}.txt"
    missing_path = args.out_dir / f"{stem}_sem_chave.csv"
    fields = ["nota_fiscal", "serie", "chave_nfe", "data_emissao", "data_entrada_saida", "loja_destino", "nome_loja_destino"]

    with detail_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    keys = [row["chave_nfe"].strip() for row in rows if row["chave_nfe"].strip()]
    keys_path.write_text("\n".join(keys) + ("\n" if keys else ""), encoding="utf-8")

    without_key = [row for row in rows if not row["chave_nfe"].strip()]
    with missing_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
        writer.writeheader()
        writer.writerows(without_key)

    print(f"notas={len(rows)} chaves={len(keys)} sem_chave={len(without_key)}")
    print(detail_path)
    print(keys_path)
    print(missing_path)


if __name__ == "__main__":
    main()
