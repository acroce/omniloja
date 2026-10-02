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
DEFAULT_JAVA_CP = f"{ROOT / 'tmp'}:{ROOT / 'tmp/jt400-11.2.jar'}"
DEFAULT_HOST = "10.105.186.1"
DEFAULT_USER = "AMC018BR"
DEFAULT_PASS = os.environ.get("AS400_PASSWORD", "")
DEFAULT_YEAR = 2026
DEFAULT_MONTH = 6
DEFAULT_TD128_PREFIX = "139000%"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Importa erros vivos do AS400 DB2 para a base SQLite central."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASS)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--month", type=int, default=DEFAULT_MONTH)
    parser.add_argument("--td128-like", default=DEFAULT_TD128_PREFIX)
    parser.add_argument("--source-label", default="DB2_LIVE")
    parser.add_argument("--append", action="store_true")
    return parser.parse_args()


def build_query(year: int, month: int, td128_like: str) -> str:
    return f"""
SELECT
    A#O4,
    MES,
    DIA,
    TD128,
    SUBSTRING(TD128,  1,  2) AS CodigoTransacao,
    SUBSTRING(TD128,  3,  1) AS CodigoVersaoLoja,
    SUBSTRING(TD128,  4,  5) AS CodigoLoja,
    SUBSTRING(TD128,  9,  8) AS DataNota,
    SUBSTRING(TD128, 17,  8) AS NumeroNota,
    SUBSTRING(TD128, 25,  1) AS TipoDevolucao,
    SUBSTRING(TD128, 26,  5) AS CodigoComplementario,
    SUBSTRING(TD128, 31,  1) AS StatusImpressaoRemito,
    SUBSTRING(TD128, 32,  4) AS NumeroTPVFiscal,
    SUBSTRING(TD128, 36,  8) AS NumeroRemitoInterno,
    SUBSTRING(TD128, 44,  6) AS Art1_CodigoArtigo,
    SUBSTRING(TD128, 50,  1) AS Art1_TipoTratamento,
    SUBSTRING(TD128, 51,  7) AS Art1_QtdUnidades,
    SUBSTRING(TD128, 58,  7) AS Art1_QtdKilos,
    SUBSTRING(TD128, 65,  2) AS Art1_CausaDevolucao,
    SUBSTRING(TD128, 67,  6) AS Art2_CodigoArtigo,
    SUBSTRING(TD128, 73,  1) AS Art2_TipoTratamento,
    SUBSTRING(TD128, 74,  7) AS Art2_QtdUnidades,
    SUBSTRING(TD128, 81,  7) AS Art2_QtdKilos,
    SUBSTRING(TD128, 88,  2) AS Art2_CausaDevolucao,
    SUBSTRING(TD128, 90,  6) AS Art3_CodigoArtigo,
    SUBSTRING(TD128, 96,  1) AS Art3_TipoTratamento,
    SUBSTRING(TD128, 97,  7) AS Art3_QtdUnidades,
    SUBSTRING(TD128,104,  7) AS Art3_QtdKilos,
    SUBSTRING(TD128,111,  2) AS Art3_CausaDevolucao,
    SUBSTRING(TD128,113, 28) AS CampoLivre,
    TDERR
FROM nixa.NXERRh
WHERE "A#O4" = {year}
  AND MES = {month}
  AND TD128 LIKE '{td128_like}'
ORDER BY DIA, CodigoLoja, NumeroNota
""".strip()


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


def run_query(args: argparse.Namespace, query: str) -> str:
    cmd = [
        "java",
        "-cp",
        DEFAULT_JAVA_CP,
        "RunAs400Query",
        args.host,
        args.user,
        args.password,
        query,
    ]
    result = subprocess.run(cmd, check=True, text=True, capture_output=True)
    return result.stdout


def ensure_table(conn: sqlite3.Connection, append: bool) -> None:
    if not append:
        conn.execute("DROP TABLE IF EXISTS as400_erros_db2_live")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS as400_erros_db2_live (
            source_label TEXT,
            ano INTEGER,
            mes INTEGER,
            dia INTEGER,
            loja INTEGER NOT NULL,
            data_nota TEXT,
            numero_nota INTEGER,
            numero_nota_original INTEGER,
            codigo_produto INTEGER NOT NULL,
            causa_devolucao TEXT,
            erro_as400 TEXT,
            codigo_transacao TEXT,
            tipo_devolucao TEXT,
            numero_remito_interno TEXT,
            origem_artigo TEXT,
            td128 TEXT,
            campo_livre TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_as400_erros_db2_live_item ON as400_erros_db2_live (loja, numero_nota_original, codigo_produto)"
    )


def format_data_nota(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    if len(raw) != 8:
        return raw
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"


def parse_rows(raw_output: str, source_label: str) -> list[tuple]:
    lines = [line for line in raw_output.splitlines() if line.strip()]
    if not lines:
        return []
    if lines[-1].startswith("--ROWS="):
        lines = lines[:-1]
    reader = csv.DictReader(StringIO("\n".join(lines)), delimiter=";")
    rows: list[tuple] = []
    for row in reader:
        numero_nota = int(row["NUMERONOTA"])
        common = {
            "source_label": source_label,
            "ano": int(row["A#O4"]),
            "mes": int(row["MES"]),
            "dia": int(row["DIA"]),
            "loja": int(row["CODIGOLOJA"]),
            "data_nota": format_data_nota(row["DATANOTA"]),
            "numero_nota": numero_nota,
            "numero_nota_original": normalize_note(numero_nota),
            "erro_as400": (row.get("TDERR") or "").strip(),
            "codigo_transacao": (row.get("CODIGOTRANSACAO") or "").strip(),
            "tipo_devolucao": (row.get("TIPODEVOLUCAO") or "").strip(),
            "numero_remito_interno": (row.get("NUMEROREMITOINTERNO") or "").strip(),
            "td128": row.get("TD128"),
            "campo_livre": row.get("CAMPOLIVRE"),
        }
        for idx in (1, 2, 3):
            codigo = (row.get(f"ART{idx}_CODIGOARTIGO") or "").strip()
            if not codigo or codigo == "999999":
                continue
            causa = (row.get(f"ART{idx}_CAUSADEVOLUCAO") or "").strip()
            rows.append(
                (
                    common["source_label"],
                    common["ano"],
                    common["mes"],
                    common["dia"],
                    common["loja"],
                    common["data_nota"],
                    common["numero_nota"],
                    common["numero_nota_original"],
                    int(codigo),
                    causa,
                    common["erro_as400"],
                    common["codigo_transacao"],
                    common["tipo_devolucao"],
                    common["numero_remito_interno"],
                    f"art{idx}",
                    common["td128"],
                    common["campo_livre"],
                )
            )
    return rows


def insert_rows(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    conn.executemany(
        """
        INSERT INTO as400_erros_db2_live (
            source_label, ano, mes, dia, loja, data_nota, numero_nota,
            numero_nota_original, codigo_produto, causa_devolucao, erro_as400,
            codigo_transacao, tipo_devolucao, numero_remito_interno, origem_artigo,
            td128, campo_livre
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def main() -> None:
    args = parse_args()
    query = build_query(args.year, args.month, args.td128_like)
    raw_output = run_query(args, query)
    rows = parse_rows(raw_output, args.source_label)
    if not rows:
        raise SystemExit("Nenhuma linha de erro retornada do AS400 DB2 vivo.")
    with sqlite3.connect(args.db) as conn:
        ensure_table(conn, args.append)
        insert_rows(conn, rows)
        conn.commit()
    print(f"Importadas {len(rows)} linhas para as400_erros_db2_live em {args.db}")


if __name__ == "__main__":
    main()
