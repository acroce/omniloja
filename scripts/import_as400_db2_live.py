#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import subprocess
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "outputs/devolucao_central.sqlite"
DEFAULT_JAR = ROOT / "tmp/jt400-11.2.jar"
DEFAULT_JAVA_CP = f"{ROOT / 'tmp'}:{DEFAULT_JAR}"
DEFAULT_JAVA_CLASS = "RunAs400Query"
DEFAULT_HOST = "10.105.186.1"
DEFAULT_USER = "AMC018BR"
DEFAULT_PASS = os.environ.get("AS400_PASSWORD", "")
DEFAULT_START = "2026-06-01"
DEFAULT_END = "2026-06-17"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Importa devolucoes do AS400 DB2 vivo para a base SQLite central."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--jar", default=str(DEFAULT_JAR))
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASS)
    parser.add_argument("--start-date", default=DEFAULT_START)
    parser.add_argument("--end-date", default=DEFAULT_END)
    parser.add_argument("--source-label", default="DB2_LIVE")
    return parser.parse_args()


def normalize_note(note: int | str | None) -> int | None:
    if note in (None, ""):
        return None
    text = str(note).strip()
    if not text:
        return None
    value = int(float(text))
    if len(text) > 4 and text[:2] in {"99", "98", "97", "96", "95", "94", "93", "92", "91", "90"}:
        return int(text[2:])
    return value


def build_query(start_date: str, end_date: str) -> str:
    return f"""
SELECT
    H.DTCTIE AS LOJA,
    H.DTCND AS NOTA,
    H.DTCA#O AS ANO,
    H.DTCMES AS MES,
    H.DTCDIA AS DIA,
    VARCHAR_FORMAT(
        DATE(
            DIGITS(H.DTCA#O) || '-' ||
            RIGHT('00' || DIGITS(H.DTCMES), 2) || '-' ||
            RIGHT('00' || DIGITS(H.DTCDIA), 2)
        ),
        'YYYY-MM-DD'
    ) AS DATA_NF,
    H.DTCFCH AS FECHA_DEVOL,
    H.DTCFCR AS FECHA_RECEP,
    L.DTLART AS PRODUTO,
    L.DTLMOT AS CAUSA,
    L.DTLTIP AS TIPO_QTD,
    L.DTLCAI AS QTD_UNIDADE,
    L.DTLCAN AS QTD_KILO
FROM ALMA.ALDVTC H
INNER JOIN ALMA.ALDVTL L
    ON L.DTLALM = H.DTCALM
   AND L.DTLTIE = H.DTCTIE
   AND L.DTLCON = H.DTCCON
   AND L.DTLND = H.DTCND
WHERE DATE(
        DIGITS(H.DTCA#O) || '-' ||
        RIGHT('00' || DIGITS(H.DTCMES), 2) || '-' ||
        RIGHT('00' || DIGITS(H.DTCDIA), 2)
      ) BETWEEN DATE('{start_date}') AND DATE('{end_date}')
ORDER BY H.DTCA#O, H.DTCMES, H.DTCDIA, H.DTCTIE, H.DTCND, L.DTLART
""".strip()


def run_query(args: argparse.Namespace, query: str) -> str:
    cmd = [
        "java",
        "-cp",
        DEFAULT_JAVA_CP,
        DEFAULT_JAVA_CLASS,
        args.host,
        args.user,
        args.password,
        query,
    ]
    result = subprocess.run(cmd, check=True, text=True, capture_output=True)
    return result.stdout


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS as400_db2_live")
    conn.execute(
        """
        CREATE TABLE as400_db2_live (
            source_label TEXT,
            loja INTEGER NOT NULL,
            nota INTEGER NOT NULL,
            nota_normalizada INTEGER NOT NULL,
            data_nf TEXT,
            produto INTEGER NOT NULL,
            causa TEXT,
            quantidade REAL,
            ano INTEGER,
            mes INTEGER,
            dia INTEGER,
            fecha_devol TEXT,
            fecha_recep TEXT,
            tipo_qtd TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX idx_as400_db2_live_item ON as400_db2_live (loja, nota_normalizada, produto)"
    )


def parse_rows(raw_output: str, source_label: str) -> list[tuple]:
    lines = [line for line in raw_output.splitlines() if line.strip()]
    if not lines:
        return []
    if lines[-1].startswith("--ROWS="):
        lines = lines[:-1]
    csv_text = "\n".join(lines)
    reader = csv.DictReader(StringIO(csv_text), delimiter=";")
    rows: list[tuple] = []
    for row in reader:
        nota = int(row["NOTA"])
        tipo_qtd = (row.get("TIPO_QTD") or "").strip()
        qtd_unidade = row.get("QTD_UNIDADE")
        qtd_kilo = row.get("QTD_KILO")
        quantidade = None
        if tipo_qtd == "1":
            quantidade = float(qtd_unidade) if qtd_unidade not in (None, "") else None
        else:
            quantidade = float(qtd_kilo) if qtd_kilo not in (None, "") else None
        rows.append(
            (
                source_label,
                int(row["LOJA"]),
                nota,
                normalize_note(nota),
                row.get("DATA_NF"),
                int(row["PRODUTO"]),
                (row.get("CAUSA") or "").strip(),
                quantidade,
                int(row["ANO"]),
                int(row["MES"]),
                int(row["DIA"]),
                row.get("FECHA_DEVOL"),
                row.get("FECHA_RECEP"),
                tipo_qtd,
            )
        )
    return rows


def insert_rows(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    conn.executemany(
        """
        INSERT INTO as400_db2_live (
            source_label, loja, nota, nota_normalizada, data_nf, produto, causa,
            quantidade, ano, mes, dia, fecha_devol, fecha_recep, tipo_qtd
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def main() -> None:
    args = parse_args()
    query = build_query(args.start_date, args.end_date)
    raw_output = run_query(args, query)
    rows = parse_rows(raw_output, args.source_label)
    if not rows:
        raise SystemExit("Nenhuma linha retornada do AS400 DB2 vivo.")
    conn = sqlite3.connect(args.db)
    try:
        ensure_table(conn)
        insert_rows(conn, rows)
        conn.commit()
    finally:
        conn.close()
    print(f"Importadas {len(rows)} linhas para as400_db2_live em {args.db}")


if __name__ == "__main__":
    main()
