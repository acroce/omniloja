#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import subprocess
from io import StringIO
from pathlib import Path

from build_devolucao_central_db import build_pleno_status


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "outputs/devolucao_central.sqlite"
DEFAULT_JAR = ROOT / "tmp/jt400-11.2.jar"
DEFAULT_JAVA_CP = f"{ROOT / 'tmp'}:{DEFAULT_JAR}"
DEFAULT_JAVA_CLASS = "RunAs400Query"
DEFAULT_HOST = "10.105.186.1"
DEFAULT_USER = "AMC018BR"
DEFAULT_PASS = os.environ.get("AS400_PASSWORD", "")
DEFAULT_TABLE = "as400_db2_live"
DEFAULT_CHUNK_SIZE = 400


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Busca no AS400 todas as devolucoes correspondentes as notas do Pleno, "
            "sem filtro de data e considerando variacoes prefixadas 99/98/.../90."
        )
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--jar", default=str(DEFAULT_JAR))
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASS)
    parser.add_argument("--table-name", default=DEFAULT_TABLE)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
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


def note_variants(note: int) -> list[int]:
    variants = {int(note)}
    for prefix in range(99, 89, -1):
        variants.add(int(f"{prefix}{int(note):04d}"))
    return sorted(variants)


def fetch_pleno_notes(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute(
        """
        SELECT DISTINCT nro_nf
        FROM pleno
        WHERE nro_nf IS NOT NULL
          AND nro_nf > 0
        ORDER BY nro_nf
        """
    ).fetchall()
    return [int(row[0]) for row in rows]


def build_candidate_notes(pleno_notes: list[int]) -> list[int]:
    candidates: set[int] = set()
    for note in pleno_notes:
        candidates.update(note_variants(note))
    return sorted(candidates)


def chunked(values: list[int], size: int) -> list[list[int]]:
    return [values[idx : idx + size] for idx in range(0, len(values), size)]


def build_query(notes: list[int]) -> str:
    note_list = ",".join(str(note) for note in notes)
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
WHERE H.DTCND IN ({note_list})
ORDER BY H.DTCND, H.DTCTIE, L.DTLART
""".strip()


def run_query(args: argparse.Namespace, query: str) -> str:
    java_cp = f"{ROOT / 'tmp'}:{Path(args.jar).expanduser().resolve()}"
    cmd = [
        "java",
        "-cp",
        java_cp,
        DEFAULT_JAVA_CLASS,
        args.host,
        args.user,
        args.password,
        query,
    ]
    try:
        result = subprocess.run(cmd, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "Falha ao consultar o AS400.\n"
            f"stdout:\n{exc.stdout}\n"
            f"stderr:\n{exc.stderr}"
        ) from exc
    return result.stdout


def ensure_table(conn: sqlite3.Connection, table_name: str) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    conn.execute(
        f"""
        CREATE TABLE {table_name} (
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
        f"CREATE INDEX idx_{table_name}_item ON {table_name} (loja, nota_normalizada, produto)"
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


def insert_rows(conn: sqlite3.Connection, table_name: str, rows: list[tuple]) -> None:
    conn.executemany(
        f"""
        INSERT INTO {table_name} (
            source_label, loja, nota, nota_normalizada, data_nf, produto, causa,
            quantidade, ano, mes, dia, fecha_devol, fecha_recep, tipo_qtd
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def main() -> None:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()

    with sqlite3.connect(db_path) as conn:
        pleno_notes = fetch_pleno_notes(conn)
        candidate_notes = build_candidate_notes(pleno_notes)
        ensure_table(conn, args.table_name)

        total_rows = 0
        total_chunks = 0
        chunks = chunked(candidate_notes, max(1, args.chunk_size))
        total_chunks_planned = len(chunks)
        for chunk in chunks:
            total_chunks += 1
            raw_output = run_query(args, build_query(chunk))
            rows = parse_rows(raw_output, "DB2_NOTAS_PLENO_SEM_DATA")
            if rows:
                insert_rows(conn, args.table_name, rows)
                total_rows += len(rows)
            if total_chunks == 1 or total_chunks % 10 == 0 or total_chunks == total_chunks_planned:
                print(
                    f"chunk {total_chunks}/{total_chunks_planned} concluido | "
                    f"notas_consultadas={len(chunk)} | linhas_acumuladas={total_rows}",
                    flush=True,
                )

        build_pleno_status(conn)
        conn.commit()

    print(f"Base: {db_path}")
    print(f"Notas distintas do Pleno: {len(pleno_notes)}")
    print(f"Notas candidatas AS400: {len(candidate_notes)}")
    print(f"Chunks executados: {total_chunks}")
    print(f"Linhas importadas para {args.table_name}: {total_rows}")
    print("pleno_status recalculado com lookup sem data e com variacoes de nota.")


if __name__ == "__main__":
    main()
