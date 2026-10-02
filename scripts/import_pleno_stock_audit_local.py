#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import tarfile
import tempfile
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "outputs" / "pleno_stock_audit.sqlite"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Importa pacote/pasta de auditoria Pleno para SQLite local."
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Pasta gerada pelo servidor ou pacote .tar.gz.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"SQLite de destino. Padrao: {DEFAULT_DB}",
    )
    parser.add_argument(
        "--replace-run",
        action="store_true",
        help="Remove dados da mesma carga antes de importar novamente.",
    )
    return parser.parse_args()


def safe_table_name(path: Path) -> str:
    name = path.stem.lower()
    return "".join(ch if ch.isalnum() else "_" for ch in name).strip("_")


def extract_if_needed(source: Path) -> tuple[Path, tempfile.TemporaryDirectory[str] | None]:
    if source.is_dir():
        return source, None
    if source.suffixes[-2:] != [".tar", ".gz"]:
        raise SystemExit("A origem deve ser uma pasta ou arquivo .tar.gz")

    temp = tempfile.TemporaryDirectory(prefix="pleno_stock_audit_")
    temp_path = Path(temp.name)
    with tarfile.open(source, "r:gz") as archive:
        archive.extractall(temp_path)

    dirs = [path for path in temp_path.iterdir() if path.is_dir()]
    if len(dirs) != 1:
        raise SystemExit("Pacote .tar.gz deveria conter exatamente uma pasta de carga")
    return dirs[0], temp


def csv_files(run_dir: Path) -> Iterable[Path]:
    for path in sorted(run_dir.glob("*.csv")):
        if path.name.startswith("."):
            continue
        yield path


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if path.stat().st_size == 0:
        return [], []
    with path.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        rows = [dict(row) for row in reader]
        return list(reader.fieldnames or []), rows


def ensure_table(conn: sqlite3.Connection, table: str, columns: list[str]) -> None:
    quoted_cols = ", ".join([f'"{col}" TEXT' for col in columns])
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS "{table}" (
            run_id TEXT NOT NULL,
            imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            {quoted_cols}
        )
        """
    )
    conn.execute(f'CREATE INDEX IF NOT EXISTS "idx_{table}_run" ON "{table}" (run_id)')
    existing = {
        row[1]
        for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    }
    for column in columns:
        if column not in existing:
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" TEXT')


def import_csv(conn: sqlite3.Connection, run_id: str, path: Path, replace_run: bool) -> int:
    table = safe_table_name(path)
    columns, rows = read_rows(path)
    if not columns:
        return 0

    ensure_table(conn, table, columns)
    if replace_run:
        conn.execute(f'DELETE FROM "{table}" WHERE run_id = ?', (run_id,))

    placeholders = ", ".join(["?"] * (len(columns) + 1))
    column_sql = ", ".join(['"run_id"', *[f'"{col}"' for col in columns]])
    sql = f'INSERT INTO "{table}" ({column_sql}) VALUES ({placeholders})'
    values = [[run_id, *[row.get(col, "") for col in columns]] for row in rows]
    conn.executemany(sql, values)
    return len(rows)


def load_manifest(run_dir: Path) -> dict:
    path = run_dir / "manifest.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def import_manifest(
    conn: sqlite3.Connection,
    run_id: str,
    source: Path,
    run_dir: Path,
    manifest: dict,
    replace_run: bool,
) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_runs (
            run_id TEXT PRIMARY KEY,
            run_type TEXT,
            source_path TEXT NOT NULL,
            run_dir TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            label TEXT,
            lojas TEXT,
            generated_at TEXT,
            imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            manifest_json TEXT
        )
        """
    )
    existing = {
        row[1]
        for row in conn.execute('PRAGMA table_info("audit_runs")').fetchall()
    }
    for column in ("run_type", "label"):
        if column not in existing:
            conn.execute(f'ALTER TABLE audit_runs ADD COLUMN "{column}" TEXT')
    if replace_run:
        conn.execute("DELETE FROM audit_runs WHERE run_id = ?", (run_id,))
    conn.execute(
        """
        INSERT OR REPLACE INTO audit_runs (
            run_id, run_type, source_path, run_dir, start_date, end_date, label, lojas, generated_at, manifest_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            manifest.get("type", "daily_audit"),
            str(source),
            str(run_dir),
            manifest.get("start_date"),
            manifest.get("end_date"),
            manifest.get("label"),
            json.dumps(manifest.get("lojas"), ensure_ascii=False),
            manifest.get("generated_at"),
            json.dumps(manifest, ensure_ascii=False),
        ),
    )


def create_views(conn: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    for view_name in (
        "vw_auditoria_divergencias",
        "vw_movimentos_sem_causa",
        "vw_snapshots_estoque",
    ):
        conn.execute(f'DROP VIEW IF EXISTS "{view_name}"')

    if "conciliacao_sku" in tables:
        conciliacao_columns = {
            row[1]
            for row in conn.execute('PRAGMA table_info("conciliacao_sku")').fetchall()
        }

        def view_column(name: str) -> str:
            if name in conciliacao_columns:
                return name
            return f"NULL AS {name}"

        view_columns = [
            "run_id",
            "loja",
            "nome_loja",
            "data_movimento",
            "sku",
            "descricao",
            "qtd_inicio",
            "valor_inicio_custo",
            "qtd_movimento",
            "valor_movimento_custo",
            "qtd_fim_esperado",
            "valor_fim_esperado_custo",
            "qtd_fim_pleno",
            "valor_fim_pleno_custo",
            "divergencia_qtd",
            "divergencia_valor_custo",
            "qtd_vendida_cupom",
            "valor_vendido_cupom",
            "qtd_venda_movimento",
            "valor_venda_movimento_custo",
            "qtd_sem_causa_movimento",
            "valor_sem_causa_movimento",
            "qtd_nf_entrada_movimento",
            "valor_nf_entrada_movimento",
            "qtd_inventario_movimento",
            "valor_inventario_movimento",
        ]
        select_columns = ",\n                ".join(
            view_column(column) for column in view_columns
        )
        conn.execute(
            f"""
            CREATE VIEW vw_auditoria_divergencias AS
            SELECT
                {select_columns}
            FROM conciliacao_sku
            WHERE CAST(IFNULL(divergencia_qtd, '0') AS REAL) <> 0
            """
        )
    if "movimentos_estoque" in tables:
        conn.execute(
            """
            CREATE VIEW vw_movimentos_sem_causa AS
            SELECT *
            FROM movimentos_estoque
            WHERE origem = 'SEM_CAUSA'
            """
        )
    if "estoque_atual_snapshot" in tables:
        conn.execute(
            """
            CREATE VIEW vw_snapshots_estoque AS
            SELECT
                s.run_id,
                r.generated_at,
                r.label,
                s.loja,
                s.nome_loja,
                s.sku,
                s.descricao,
                s.qtd_atual,
                s.data_saldo,
                s.custo_medio,
                s.valor_custo
            FROM estoque_atual_snapshot s
            JOIN audit_runs r ON r.run_id = s.run_id
            """
        )


def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    if not source.exists():
        raise SystemExit(f"Origem nao encontrada: {source}")

    run_dir, temp = extract_if_needed(source)
    run_id = run_dir.name
    args.db.parent.mkdir(parents=True, exist_ok=True)

    try:
        manifest = load_manifest(run_dir)
        with sqlite3.connect(args.db) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            import_manifest(conn, run_id, source, run_dir, manifest, args.replace_run)
            counts = {}
            for path in csv_files(run_dir):
                counts[path.name] = import_csv(conn, run_id, path, args.replace_run)
            create_views(conn)
            conn.commit()
    finally:
        if temp is not None:
            temp.cleanup()

    print(f"SQLite: {args.db}")
    print(f"Carga: {run_id}")
    for name, count in counts.items():
        print(f"{name}: {count} linha(s)")


if __name__ == "__main__":
    main()
