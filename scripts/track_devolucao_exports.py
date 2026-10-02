#!/usr/bin/env python3
import argparse
import csv
import sqlite3
from datetime import datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Controla o status local das devolucoes exportadas para o AS400."
    )
    parser.add_argument(
        "--db",
        default="outputs/devolucao_auditoria.sqlite",
        help="Caminho do banco SQLite.",
    )
    parser.add_argument(
        "--mark-file",
        help="CSV consolidado ou individual para marcar como exportado.",
    )
    parser.add_argument(
        "--sync-concluded",
        action="store_true",
        help="Marca como concluido o que ja apareceu no AS400 importado.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Exibe um resumo por status apos o processamento.",
    )
    return parser.parse_args()


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS devolucao_export_lote (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL UNIQUE,
            exported_at TEXT NOT NULL,
            total_items INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS devolucao_export_item (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lote_id INTEGER NOT NULL,
            nro_loja INTEGER NOT NULL,
            nro_nf_gerado INTEGER NOT NULL,
            nro_nf_original INTEGER NOT NULL,
            data_nf TEXT NOT NULL,
            codigo_interno INTEGER NOT NULL,
            causa_devolucao TEXT NOT NULL,
            qtd_devolvida TEXT,
            tipo_unidade_venda TEXT,
            status TEXT NOT NULL DEFAULT 'EXPORTADO',
            exported_at TEXT NOT NULL,
            concluded_at TEXT,
            FOREIGN KEY (lote_id) REFERENCES devolucao_export_lote(id),
            UNIQUE (nro_loja, nro_nf_gerado, data_nf, codigo_interno, causa_devolucao)
        );

        CREATE INDEX IF NOT EXISTS idx_devolucao_export_item_status
            ON devolucao_export_item (status, nro_loja, nro_nf_gerado, data_nf);

        CREATE INDEX IF NOT EXISTS idx_devolucao_export_item_match
            ON devolucao_export_item (nro_loja, nro_nf_gerado, data_nf, codigo_interno, causa_devolucao);

        DROP VIEW IF EXISTS devolucao_export_status_resumo;
        CREATE VIEW devolucao_export_status_resumo AS
        SELECT
            status,
            COUNT(*) AS total_itens
        FROM devolucao_export_item
        GROUP BY status;

        DROP VIEW IF EXISTS devolucao_export_status_detalhe;
        CREATE VIEW devolucao_export_status_detalhe AS
        SELECT
            e.id,
            l.file_name,
            l.file_path,
            l.exported_at AS lote_exportado_em,
            e.nro_loja,
            e.nro_nf_gerado,
            e.nro_nf_original,
            CASE
                WHEN e.nro_nf_original > 1000 THEN 'MASTER'
                ELSE 'LOJA'
            END AS classificacao_nota,
            e.data_nf,
            e.codigo_interno,
            e.causa_devolucao,
            e.qtd_devolvida,
            e.tipo_unidade_venda,
            e.status,
            e.exported_at,
            e.concluded_at
        FROM devolucao_export_item e
        INNER JOIN devolucao_export_lote l
            ON l.id = e.lote_id;
        """
    )


def derive_original_note(nro_nf_gerado: int) -> int:
    text = str(nro_nf_gerado)
    if len(text) > 4:
        prefix = int(text[:2])
        if 90 <= prefix <= 99:
            return int(text[2:])
    return nro_nf_gerado


def mark_exported(conn: sqlite3.Connection, csv_path: Path) -> tuple[int, int]:
    exported_at = datetime.now().isoformat(timespec="seconds")
    lote = conn.execute(
        """
        INSERT INTO devolucao_export_lote (file_name, file_path, exported_at, total_items)
        VALUES (?, ?, ?, 0)
        ON CONFLICT(file_path) DO UPDATE SET
            file_name = excluded.file_name,
            exported_at = excluded.exported_at
        RETURNING id
        """,
        (csv_path.name, str(csv_path), exported_at),
    ).fetchone()
    lote_id = int(lote[0])

    inserted = 0
    skipped = 0
    with csv_path.open("r", encoding="latin1", newline="") as fp:
        reader = csv.DictReader(fp, delimiter=";")
        for raw in reader:
            nro_loja = int(raw["nro_loja"])
            nro_nf_gerado = int(raw["nro_nf"])
            data_nf = str(raw["data_nf"])
            codigo_interno = int(raw["codigo_interno"])
            causa = str(raw.get("causa_devolucao") or "")
            qtd = str(raw.get("qtd_devolvida") or "")
            unidade = str(raw.get("tipo_unidade_venda") or "")
            nro_nf_original = derive_original_note(nro_nf_gerado)
            before = conn.total_changes
            conn.execute(
                """
                INSERT OR IGNORE INTO devolucao_export_item (
                    lote_id, nro_loja, nro_nf_gerado, nro_nf_original, data_nf,
                    codigo_interno, causa_devolucao, qtd_devolvida,
                    tipo_unidade_venda, status, exported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'EXPORTADO', ?)
                """,
                (
                    lote_id,
                    nro_loja,
                    nro_nf_gerado,
                    nro_nf_original,
                    data_nf,
                    codigo_interno,
                    causa,
                    qtd,
                    unidade,
                    exported_at,
                ),
            )
            if conn.total_changes > before:
                inserted += 1
            else:
                skipped += 1

    conn.execute(
        """
        UPDATE devolucao_export_lote
        SET total_items = (
            SELECT COUNT(*)
            FROM devolucao_export_item
            WHERE lote_id = ?
        )
        WHERE id = ?
        """,
        (lote_id, lote_id),
    )
    return inserted, skipped


def sync_concluded(conn: sqlite3.Connection) -> int:
    before = conn.total_changes
    conn.execute(
        """
        UPDATE devolucao_export_item AS e
        SET status = 'CONCLUIDO',
            concluded_at = COALESCE(concluded_at, datetime('now'))
        WHERE status <> 'CONCLUIDO'
          AND EXISTS (
              SELECT 1
              FROM as400_qlik_confirmado a
              WHERE a.loja = e.nro_loja
                AND a.nr_devolucao = e.nro_nf_gerado
                AND a.data_nf = e.data_nf
                AND a.cd_artigo = e.codigo_interno
                AND IFNULL(a.causa_devolucao, '') = IFNULL(e.causa_devolucao, '')
          )
        """
    )
    return conn.total_changes - before


def print_summary(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT status, total_itens
        FROM devolucao_export_status_resumo
        ORDER BY status
        """
    ).fetchall()
    if not rows:
        print("Nenhum item controlado ainda.")
        return
    for status, total in rows:
        print(f"{status}: {total}")


def main() -> None:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()
    mark_path = Path(args.mark_file).expanduser().resolve() if args.mark_file else None

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)

        if mark_path:
            inserted, skipped = mark_exported(conn, mark_path)
            print(f"Arquivo marcado como exportado: {mark_path}")
            print(f"Itens inseridos no controle: {inserted}")
            print(f"Itens ja existentes no controle: {skipped}")

        if args.sync_concluded:
            updated = sync_concluded(conn)
            print(f"Itens marcados como concluidos: {updated}")

        if args.summary:
            print_summary(conn)

        conn.commit()


if __name__ == "__main__":
    main()
