#!/usr/bin/env python3
import argparse
import csv
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileRow:
    source_label: str
    folder_date: str
    file_name: str
    nro_loja: int
    nro_nf: int
    data_nf: str
    codigo_interno: int
    qtd_devolvida: float | None
    causa_devolucao: str | None
    tipo_unidade_venda: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Importa arquivos CSV de devolucao a partir de uma pasta para o SQLite local."
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        help="Pasta raiz com subpastas/arquivos CSV de devolucao.",
    )
    parser.add_argument(
        "--db",
        default="outputs/devolucao_auditoria.sqlite",
        help="Caminho do banco SQLite.",
    )
    parser.add_argument(
        "--source-label",
        help="Rotulo para a coluna source_zip. Default: nome da pasta raiz.",
    )
    return parser.parse_args()


def parse_csv_rows(root_dir: Path, source_label: str) -> list[FileRow]:
    rows: list[FileRow] = []
    for csv_path in sorted(root_dir.rglob("*.csv")):
        relative = csv_path.relative_to(root_dir)
        folder_date = ""
        match = re.search(r"enviados_(\d{8})", str(relative))
        if match:
            folder_date = match.group(1)

        with csv_path.open("r", encoding="latin1", newline="") as fp:
            reader = csv.DictReader(fp, delimiter=";")
            for raw in reader:
                try:
                    rows.append(
                        FileRow(
                            source_label=source_label,
                            folder_date=folder_date,
                            file_name=os.path.basename(csv_path),
                            nro_loja=int(raw["nro_loja"]),
                            nro_nf=int(raw["nro_nf"]),
                            data_nf=str(raw["data_nf"]),
                            codigo_interno=int(raw["codigo_interno"]),
                            qtd_devolvida=float(raw["qtd_devolvida"])
                            if raw.get("qtd_devolvida") not in ("", None)
                            else None,
                            causa_devolucao=raw.get("causa_devolucao") or None,
                            tipo_unidade_venda=raw.get("tipo_unidade_venda") or None,
                        )
                    )
                except (KeyError, ValueError):
                    continue
    return rows


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS arquivos_devolucao (
            source_zip TEXT NOT NULL,
            folder_date TEXT NOT NULL,
            file_name TEXT NOT NULL,
            nro_loja INTEGER NOT NULL,
            nro_nf INTEGER NOT NULL,
            data_nf TEXT NOT NULL,
            codigo_interno INTEGER NOT NULL,
            qtd_devolvida REAL,
            causa_devolucao TEXT,
            tipo_unidade_venda TEXT
        )
        """
    )


def import_rows(conn: sqlite3.Connection, rows: list[FileRow]) -> tuple[int, int]:
    inserted = 0
    skipped = 0
    for row in rows:
        exists = conn.execute(
            """
            SELECT 1
            FROM arquivos_devolucao
            WHERE nro_loja = ?
              AND nro_nf = ?
              AND data_nf = ?
              AND codigo_interno = ?
              AND IFNULL(causa_devolucao, '') = IFNULL(?, '')
              AND IFNULL(tipo_unidade_venda, '') = IFNULL(?, '')
              AND (
                    (qtd_devolvida IS NULL AND ? IS NULL)
                 OR qtd_devolvida = ?
              )
            LIMIT 1
            """,
            (
                row.nro_loja,
                row.nro_nf,
                row.data_nf,
                row.codigo_interno,
                row.causa_devolucao,
                row.tipo_unidade_venda,
                row.qtd_devolvida,
                row.qtd_devolvida,
            ),
        ).fetchone()
        if exists:
            skipped += 1
            continue

        conn.execute(
            """
            INSERT INTO arquivos_devolucao (
                source_zip, folder_date, file_name, nro_loja, nro_nf, data_nf,
                codigo_interno, qtd_devolvida, causa_devolucao, tipo_unidade_venda
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.source_label,
                row.folder_date,
                row.file_name,
                row.nro_loja,
                row.nro_nf,
                row.data_nf,
                row.codigo_interno,
                row.qtd_devolvida,
                row.causa_devolucao,
                row.tipo_unidade_venda,
            ),
        )
        inserted += 1

    return inserted, skipped


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input_dir).expanduser().resolve()
    db_path = Path(args.db).expanduser().resolve()
    source_label = args.source_label or input_dir.name

    rows = parse_csv_rows(input_dir, source_label)

    with sqlite3.connect(db_path) as conn:
        ensure_table(conn)
        inserted, skipped = import_rows(conn, rows)
        total = conn.execute("SELECT COUNT(*) FROM arquivos_devolucao").fetchone()[0]
        conn.commit()

    print(f"Pasta importada: {input_dir}")
    print(f"Banco SQLite: {db_path}")
    print(f"Linhas lidas: {len(rows)}")
    print(f"Linhas inseridas: {inserted}")
    print(f"Linhas puladas por duplicidade: {skipped}")
    print(f"Total em arquivos_devolucao: {total}")


if __name__ == "__main__":
    main()
