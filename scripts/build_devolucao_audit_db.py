#!/usr/bin/env python3
import argparse
import csv
import io
import os
import re
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pymysql


@dataclass(frozen=True)
class FileRow:
    source_zip: str
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
        description="Monta uma base SQLite para auditar devolucoes dos arquivos ZIP contra o Pleno."
    )
    parser.add_argument(
        "--zip",
        dest="zip_paths",
        action="append",
        required=True,
        help="Caminho de um ZIP com arquivos de devolucao. Pode repetir a flag.",
    )
    parser.add_argument(
        "--output",
        default="outputs/devolucao_auditoria.sqlite",
        help="Caminho do arquivo SQLite de saida.",
    )
    return parser.parse_args()


def read_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip("'\"")
    return data


def parse_zip_rows(zip_path: Path) -> tuple[list[FileRow], set[date]]:
    rows: list[FileRow] = []
    folder_dates: set[date] = set()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.namelist():
            folder_match = re.search(r"enviados_(\d{8})/", member)
            if folder_match:
                folder_dates.add(datetime.strptime(folder_match.group(1), "%Y%m%d").date())
            if not member.lower().endswith(".csv"):
                continue
            content = archive.read(member).decode("latin1", errors="replace").splitlines()
            reader = csv.DictReader(content, delimiter=";")
            folder_date = folder_match.group(1) if folder_match else None
            for raw in reader:
                try:
                    rows.append(
                        FileRow(
                            source_zip=zip_path.name,
                            folder_date=folder_date or "",
                            file_name=os.path.basename(member),
                            nro_loja=int(raw["nro_loja"]),
                            nro_nf=int(raw["nro_nf"]),
                            data_nf=str(raw["data_nf"]),
                            codigo_interno=int(raw["codigo_interno"]),
                            qtd_devolvida=float(raw["qtd_devolvida"]) if raw.get("qtd_devolvida") not in ("", None) else None,
                            causa_devolucao=raw.get("causa_devolucao") or None,
                            tipo_unidade_venda=raw.get("tipo_unidade_venda") or None,
                        )
                    )
                except (KeyError, ValueError):
                    continue
    return rows, folder_dates


def connect_mysql(env: dict[str, str]):
    return pymysql.connect(
        host=env.get("DB_HOST", env.get("MYSQL_HOST", "127.0.0.1")),
        port=int(env.get("DB_PORT", env.get("MYSQL_PORT", "3306"))),
        user=env.get("DB_USERNAME", env.get("DB_USER", env.get("MYSQL_USER", "root"))),
        password=env.get("DB_PASSWORD", env.get("MYSQL_PASSWORD", "")),
        database=env.get("DB_DATABASE", env.get("MYSQL_DATABASE", "pleno")),
        charset="latin1",
    )


def fetch_pleno_rows(env: dict[str, str], start_date: date, end_date: date) -> list[tuple]:
    query = """
        SELECT
            data_devolucao,
            loja,
            codigo_produto,
            nro_nf,
            data_nf,
            nro_pedido,
            motivo,
            qtd_devolvida,
            tipo_unidade_venda,
            valor_devolvido
        FROM view_dia_devolucao_cd
        WHERE data_devolucao BETWEEN %s AND %s
        ORDER BY data_devolucao, loja, nro_nf, codigo_produto
    """
    with connect_mysql(env) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (start_date, end_date))
            return list(cur.fetchall())


def init_sqlite(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS arquivos_devolucao;
        DROP TABLE IF EXISTS pleno_devolucao_cd;
        DROP TABLE IF EXISTS apenas_no_pleno;
        DROP TABLE IF EXISTS apenas_no_arquivo;
        DROP TABLE IF EXISTS auditoria_resumo;

        CREATE TABLE arquivos_devolucao (
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
        );

        CREATE TABLE pleno_devolucao_cd (
            data_devolucao TEXT NOT NULL,
            loja INTEGER NOT NULL,
            codigo_produto INTEGER NOT NULL,
            nro_nf INTEGER NOT NULL,
            data_nf TEXT NOT NULL,
            nro_pedido INTEGER,
            motivo TEXT,
            qtd_devolvida REAL,
            tipo_unidade_venda TEXT,
            valor_devolvido REAL
        );

        CREATE INDEX idx_arquivos_chave
            ON arquivos_devolucao (nro_loja, nro_nf, data_nf, codigo_interno);
        CREATE INDEX idx_pleno_chave
            ON pleno_devolucao_cd (loja, nro_nf, data_nf, codigo_produto);
        """
    )


def load_sqlite(
    conn: sqlite3.Connection,
    file_rows: list[FileRow],
    pleno_rows: list[tuple],
) -> None:
    conn.executemany(
        """
        INSERT INTO arquivos_devolucao (
            source_zip, folder_date, file_name, nro_loja, nro_nf, data_nf,
            codigo_interno, qtd_devolvida, causa_devolucao, tipo_unidade_venda
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row.source_zip,
                row.folder_date,
                row.file_name,
                row.nro_loja,
                row.nro_nf,
                row.data_nf,
                row.codigo_interno,
                row.qtd_devolvida,
                row.causa_devolucao,
                row.tipo_unidade_venda,
            )
            for row in file_rows
        ],
    )
    conn.executemany(
        """
        INSERT INTO pleno_devolucao_cd (
            data_devolucao, loja, codigo_produto, nro_nf, data_nf,
            nro_pedido, motivo, qtd_devolvida, tipo_unidade_venda, valor_devolvido
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
                row[1],
                row[2],
                row[3],
                row[4].isoformat() if hasattr(row[4], "isoformat") else str(row[4]),
                row[5],
                row[6],
                float(row[7]) if row[7] is not None else None,
                row[8],
                float(row[9]) if row[9] is not None else None,
            )
            for row in pleno_rows
        ],
    )


def build_comparison_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE apenas_no_pleno AS
        SELECT
            p.*
        FROM pleno_devolucao_cd p
        LEFT JOIN arquivos_devolucao a
            ON a.nro_loja = p.loja
           AND a.nro_nf = p.nro_nf
           AND a.data_nf = p.data_nf
           AND a.codigo_interno = p.codigo_produto
        WHERE a.nro_loja IS NULL;

        CREATE TABLE apenas_no_arquivo AS
        SELECT
            a.*
        FROM arquivos_devolucao a
        LEFT JOIN pleno_devolucao_cd p
            ON p.loja = a.nro_loja
           AND p.nro_nf = a.nro_nf
           AND p.data_nf = a.data_nf
           AND p.codigo_produto = a.codigo_interno
        WHERE p.loja IS NULL;

        CREATE TABLE auditoria_resumo AS
        SELECT 'arquivos_devolucao' AS origem, COUNT(*) AS total FROM arquivos_devolucao
        UNION ALL
        SELECT 'pleno_devolucao_cd' AS origem, COUNT(*) AS total FROM pleno_devolucao_cd
        UNION ALL
        SELECT 'apenas_no_pleno' AS origem, COUNT(*) AS total FROM apenas_no_pleno
        UNION ALL
        SELECT 'apenas_no_arquivo' AS origem, COUNT(*) AS total FROM apenas_no_arquivo;

        CREATE INDEX idx_apenas_no_pleno
            ON apenas_no_pleno (loja, nro_nf, data_nf, codigo_produto);
        CREATE INDEX idx_apenas_no_arquivo
            ON apenas_no_arquivo (nro_loja, nro_nf, data_nf, codigo_interno);
        """
    )


def write_metadata(conn: sqlite3.Connection, zip_paths: list[Path], start_date: date, end_date: date) -> None:
    conn.execute("DROP TABLE IF EXISTS metadados")
    conn.execute("CREATE TABLE metadados (chave TEXT PRIMARY KEY, valor TEXT NOT NULL)")
    values = [
        ("periodo_inicial", start_date.isoformat()),
        ("periodo_final", end_date.isoformat()),
        ("zip_origens", ", ".join(path.name for path in zip_paths)),
        ("gerado_em", datetime.now().isoformat(timespec="seconds")),
    ]
    conn.executemany("INSERT INTO metadados (chave, valor) VALUES (?, ?)", values)


def main() -> None:
    args = parse_args()
    workspace_root = Path(__file__).resolve().parent.parent
    env = read_env(workspace_root / ".env")

    zip_paths = [Path(path) for path in args.zip_paths]
    file_rows: list[FileRow] = []
    folder_dates: set[date] = set()
    for zip_path in zip_paths:
        rows, dates = parse_zip_rows(zip_path)
        file_rows.extend(rows)
        folder_dates.update(dates)

    if not folder_dates:
        raise SystemExit("Nenhuma data encontrada nas pastas dos ZIPs.")

    start_date = min(folder_dates)
    end_date = max(folder_dates)
    pleno_rows = fetch_pleno_rows(env, start_date, end_date)

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = workspace_root / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(output_path)
    try:
        init_sqlite(conn)
        load_sqlite(conn, file_rows, pleno_rows)
        build_comparison_tables(conn)
        write_metadata(conn, zip_paths, start_date, end_date)
        conn.commit()
    finally:
        conn.close()

    print(f"SQLite gerado em: {output_path}")
    print(f"Periodo: {start_date} a {end_date}")
    print(f"Linhas arquivos: {len(file_rows)}")
    print(f"Linhas Pleno: {len(pleno_rows)}")


if __name__ == "__main__":
    main()
