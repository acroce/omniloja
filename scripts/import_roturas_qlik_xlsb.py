#!/usr/bin/env python3
import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pymysql
from pyxlsb import open_workbook


EXCEL_EPOCH = datetime(1899, 12, 30)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Importa o xlsb do QlikView para o SQLite e cria tabelas de comparacao com o Pleno."
    )
    parser.add_argument(
        "--input",
        default="/Users/alexandrematheuscrose/Downloads/Roturas - Qlikview.xlsb",
        help="Caminho do arquivo xlsb.",
    )
    parser.add_argument(
        "--db",
        default="outputs/devolucao_auditoria.sqlite",
        help="Caminho do banco SQLite.",
    )
    parser.add_argument(
        "--sheet",
        default="",
        help="Aba especifica do xlsb. Se vazio, importa todas as abas.",
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


def connect_mysql(env: dict[str, str]):
    return pymysql.connect(
        host=env.get("DB_HOST", env.get("MYSQL_HOST", "127.0.0.1")),
        port=int(env.get("DB_PORT", env.get("MYSQL_PORT", "3306"))),
        user=env.get("DB_USERNAME", env.get("DB_USER", env.get("MYSQL_USER", "root"))),
        password=env.get("DB_PASSWORD", env.get("MYSQL_PASSWORD", "")),
        database=env.get("DB_DATABASE", env.get("MYSQL_DATABASE", "pleno")),
        charset="latin1",
    )


def fetch_filial_cutover(env: dict[str, str]) -> list[tuple[int, str | None]]:
    query = """
        SELECT
            cfg06_numero AS loja,
            CASE
                WHEN cfg06_data_inicio_operacao IS NULL THEN NULL
                ELSE DATE_FORMAT(cfg06_data_inicio_operacao, '%Y-%m-%d')
            END AS data_inicio_operacao
        FROM cfg06_filial
        WHERE cfg06_numero IS NOT NULL
        ORDER BY cfg06_numero
    """
    with connect_mysql(env) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            return [(int(row[0]), row[1]) for row in cur.fetchall()]


def excel_serial_to_date(value) -> str | None:
    if value in (None, ""):
        return None
    return (EXCEL_EPOCH + timedelta(days=float(value))).date().isoformat()


def normalize_cause(value) -> str:
    if value in (None, ""):
        return ""
    try:
        numeric = float(value)
        if numeric.is_integer():
            return str(int(numeric))
    except Exception:
        pass
    return str(value).strip()


def normalize_text(value):
    if value in (None, ""):
        return None
    return str(value).strip()


def normalize_int(value):
    if value in (None, ""):
        return None
    return int(float(value))


def normalize_float(value):
    if value in (None, ""):
        return None
    return float(value)


def iter_sheet_rows(path: Path, sheet_name: str):
    with open_workbook(path) as wb:
        with wb.get_sheet(sheet_name) as sheet:
            rows = sheet.rows()
            header = [cell.v for cell in next(rows)]
            header_map = {str(name).strip(): idx for idx, name in enumerate(header)}

            def cell(row, name):
                idx = header_map[name]
                return row[idx].v if idx < len(row) else None

            def cell_optional(row, name, default=None):
                idx = header_map.get(name)
                if idx is None or idx >= len(row):
                    return default
                return row[idx].v

            for row in rows:
                dt_gravacao = cell_optional(row, "Dt Gravação")
                dt_transmissao = cell_optional(row, "Dt Transmissão")
                dt_confirmacao = cell_optional(row, "Dt Confirmação")
                status_aba = normalize_text(cell_optional(row, "Status")) or normalize_text(sheet_name)
                yield (
                    status_aba,
                    normalize_int(cell(row, "Armazem")),
                    normalize_int(cell(row, "Loja")),
                    normalize_text(cell(row, "GO")),
                    normalize_text(cell(row, "GA")),
                    normalize_float(dt_gravacao),
                    normalize_float(dt_transmissao),
                    normalize_float(dt_confirmacao),
                    excel_serial_to_date(dt_gravacao),
                    excel_serial_to_date(dt_transmissao),
                    excel_serial_to_date(dt_confirmacao),
                    normalize_int(cell(row, "Nr Devolução")),
                    normalize_text(cell(row, "Destino Mercadoria")),
                    normalize_int(cell(row, "Cd Artigo")),
                    normalize_text(cell(row, "Artigo Desc")),
                    normalize_text(cell(row, "Motivo Devolução")),
                    normalize_cause(cell(row, "Motivo Devolução")),
                    normalize_float(cell(row, "Qtd Enviada")),
                    normalize_float(cell(row, "Qtd Confirmada")),
                    normalize_float(cell(row, "Preço PVP")),
                    normalize_float(cell(row, "Importe Preço Venda R$")),
                    normalize_float(cell(row, "Importe Preço Custo R$")),
                    normalize_float(cell(row, "Custo por Enviado")),
                    normalize_float(cell(row, "Custo por Confirmado")),
                )


def iter_rows(path: Path, selected_sheet: str):
    with open_workbook(path) as wb:
        sheet_names = list(wb.sheets)
    if selected_sheet:
        sheet_names = [selected_sheet]
    for sheet_name in sheet_names:
        yield from iter_sheet_rows(path, sheet_name)


def init_sqlite(conn: sqlite3.Connection) -> None:
    for stmt in (
        "DROP VIEW IF EXISTS as400_qlik_confirmado",
        "DROP TABLE IF EXISTS as400_qlik_confirmado",
        "DROP VIEW IF EXISTS as400_qlik",
        "DROP TABLE IF EXISTS as400_qlik",
    ):
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass

    conn.executescript(
        """
        DROP TABLE IF EXISTS apenas_no_pleno_vs_as400;
        DROP TABLE IF EXISTS causa_divergente_as400;
        DROP TABLE IF EXISTS apenas_no_as400_vs_pleno;
        DROP TABLE IF EXISTS filial_cutover;

        CREATE TABLE as400_qlik (
            origem_aba TEXT,
            armazem INTEGER,
            loja INTEGER,
            go_nome TEXT,
            ga TEXT,
            dt_gravacao REAL,
            dt_transmissao REAL,
            dt_confirmacao REAL,
            data_nf TEXT,
            data_transmissao TEXT,
            data_confirmacao TEXT,
            nr_devolucao INTEGER,
            destino_mercadoria TEXT,
            cd_artigo INTEGER,
            artigo_desc TEXT,
            motivo_devolucao TEXT,
            causa_devolucao TEXT,
            qtd_enviada REAL,
            qtd_confirmada REAL,
            preco_pvp REAL,
            importe_preco_venda REAL,
            importe_preco_custo REAL,
            custo_por_enviado REAL,
            custo_por_confirmado REAL
        );

        CREATE INDEX idx_as400_qlik_todas_chave
            ON as400_qlik (origem_aba, loja, nr_devolucao, data_nf, cd_artigo, causa_devolucao);

        CREATE INDEX idx_as400_qlik_todas_item
            ON as400_qlik (loja, nr_devolucao, data_nf, cd_artigo);

        CREATE VIEW as400_qlik_confirmado AS
        SELECT *
        FROM as400_qlik
        WHERE lower(IFNULL(origem_aba, '')) = 'confirmados';

        CREATE TABLE filial_cutover (
            loja INTEGER PRIMARY KEY,
            data_inicio_operacao TEXT
        );
        """
    )


def load_sqlite(conn: sqlite3.Connection, rows) -> int:
    insert_sql = """
        INSERT INTO as400_qlik (
            origem_aba, armazem, loja, go_nome, ga, dt_gravacao, dt_transmissao, dt_confirmacao,
            data_nf, data_transmissao, data_confirmacao, nr_devolucao, destino_mercadoria,
            cd_artigo, artigo_desc, motivo_devolucao, causa_devolucao, qtd_enviada,
            qtd_confirmada, preco_pvp, importe_preco_venda, importe_preco_custo,
            custo_por_enviado, custo_por_confirmado
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    count = 0
    batch = []
    for row in rows:
        batch.append(row)
        if len(batch) >= 5000:
            conn.executemany(insert_sql, batch)
            count += len(batch)
            batch = []
    if batch:
        conn.executemany(insert_sql, batch)
        count += len(batch)
    return count


def load_filial_cutover(conn: sqlite3.Connection, rows: list[tuple[int, str | None]]) -> None:
    conn.executemany(
        """
        INSERT INTO filial_cutover (loja, data_inicio_operacao)
        VALUES (?, ?)
        """,
        rows,
    )


def ensure_export_tracking_schema(conn: sqlite3.Connection) -> None:
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


def sync_concluded_statuses(conn: sqlite3.Connection) -> int:
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


def build_comparisons(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE apenas_no_pleno_vs_as400 AS
        SELECT
            p.data_devolucao,
            p.loja,
            p.codigo_produto,
            p.nro_nf,
            p.data_nf,
            p.nro_pedido,
            p.motivo,
            CASE
                WHEN p.motivo LIKE 'CAUSA %' THEN substr(p.motivo, 7, instr(substr(p.motivo, 7), ' ') - 1)
                ELSE ''
            END AS causa_pleno,
            p.qtd_devolvida,
            p.tipo_unidade_venda,
            p.valor_devolvido
        FROM pleno_devolucao_cd p
        LEFT JOIN filial_cutover fc
            ON fc.loja = p.loja
        LEFT JOIN as400_qlik_confirmado a
            ON a.loja = p.loja
           AND a.nr_devolucao = p.nro_nf
           AND a.data_nf = p.data_nf
           AND a.cd_artigo = p.codigo_produto
           AND IFNULL(a.causa_devolucao, '') = CASE
                WHEN p.motivo LIKE 'CAUSA %' THEN substr(p.motivo, 7, instr(substr(p.motivo, 7), ' ') - 1)
                ELSE ''
           END
        WHERE a.cd_artigo IS NULL
          AND (fc.data_inicio_operacao IS NULL OR p.data_nf >= fc.data_inicio_operacao);

        CREATE TABLE causa_divergente_as400 AS
        SELECT DISTINCT
            p.data_devolucao,
            p.loja,
            p.codigo_produto,
            p.nro_nf,
            p.data_nf,
            p.motivo,
            CASE
                WHEN p.motivo LIKE 'CAUSA %' THEN substr(p.motivo, 7, instr(substr(p.motivo, 7), ' ') - 1)
                ELSE ''
            END AS causa_pleno,
            a.causa_devolucao AS causa_as400,
            p.qtd_devolvida,
            p.tipo_unidade_venda
        FROM pleno_devolucao_cd p
        LEFT JOIN filial_cutover fc
            ON fc.loja = p.loja
        JOIN as400_qlik_confirmado a
            ON a.loja = p.loja
           AND a.nr_devolucao = p.nro_nf
           AND a.data_nf = p.data_nf
           AND a.cd_artigo = p.codigo_produto
        WHERE IFNULL(a.causa_devolucao, '') <> CASE
                WHEN p.motivo LIKE 'CAUSA %' THEN substr(p.motivo, 7, instr(substr(p.motivo, 7), ' ') - 1)
                ELSE ''
              END
          AND (fc.data_inicio_operacao IS NULL OR p.data_nf >= fc.data_inicio_operacao);

        CREATE TABLE apenas_no_as400_vs_pleno AS
        SELECT
            a.data_nf,
            a.loja,
            a.cd_artigo,
            a.nr_devolucao,
            a.causa_devolucao,
            a.qtd_confirmada,
            a.artigo_desc
        FROM as400_qlik_confirmado a
        LEFT JOIN pleno_devolucao_cd p
            ON p.loja = a.loja
           AND p.nro_nf = a.nr_devolucao
           AND p.data_nf = a.data_nf
           AND p.codigo_produto = a.cd_artigo
        WHERE p.codigo_produto IS NULL;

        CREATE INDEX idx_apenas_no_pleno_vs_as400
            ON apenas_no_pleno_vs_as400 (loja, nro_nf, data_nf, codigo_produto, causa_pleno);

        CREATE INDEX idx_causa_divergente_as400
            ON causa_divergente_as400 (loja, nro_nf, data_nf, codigo_produto);
        """
    )


def main() -> None:
    args = parse_args()
    workspace_root = Path(__file__).resolve().parent.parent
    env = read_env(workspace_root / ".env")
    input_path = Path(args.input).expanduser().resolve()
    db_path = Path(args.db).expanduser().resolve()
    filial_cutover_rows = fetch_filial_cutover(env)

    with sqlite3.connect(db_path) as conn:
        init_sqlite(conn)
        row_count = load_sqlite(conn, iter_rows(input_path, args.sheet))
        load_filial_cutover(conn, filial_cutover_rows)
        build_comparisons(conn)
        ensure_export_tracking_schema(conn)
        concluded_count = sync_concluded_statuses(conn)

    print(f"Arquivo importado: {input_path}")
    print(f"Banco SQLite: {db_path}")
    if args.sheet:
        print(f"Aba importada: {args.sheet}")
    else:
        print("Abas importadas: todas")
    print(f"Linhas importadas: {row_count}")
    print(f"Lojas com data de virada carregadas: {len(filial_cutover_rows)}")
    print(f"Itens marcados como concluidos: {concluded_count}")


if __name__ == "__main__":
    main()
