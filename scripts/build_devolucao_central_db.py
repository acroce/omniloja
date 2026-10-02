#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DB = ROOT / "outputs/devolucao_auditoria.sqlite"
DEFAULT_TARGET_DB = ROOT / "outputs/devolucao_central.sqlite"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Cria uma base SQLite centralizada para conciliacao de devolucoes "
            "entre Pleno, arquivos enviados, AS400, AS400 Qlik e erros do AS400."
        )
    )
    parser.add_argument("--source-db", default=str(DEFAULT_SOURCE_DB))
    parser.add_argument("--target-db", default=str(DEFAULT_TARGET_DB))
    return parser.parse_args()


def extract_causa(text: str | None) -> str:
    if not text:
        return ""
    match = re.search(r"CAUSA\s+(\d+)", str(text), re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"^\s*(\d+)\s*[- ]", str(text))
    return match.group(1) if match else ""


def normalize_generated_note(note: int | str | None) -> int | None:
    if note in (None, ""):
        return None
    text = str(note).strip()
    if not text:
        return None
    try:
        value = int(float(text))
    except ValueError:
        return None
    normalized = str(value)
    if len(normalized) > 4 and normalized[:2] in {"99", "98", "97", "96", "95", "94", "93", "92", "91", "90"}:
        return int(normalized[2:])
    return value


def require_source_tables(conn: sqlite3.Connection, tables: list[str]) -> None:
    existing = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN (%s)"
            % ",".join("?" for _ in tables),
            tables,
        )
    }
    missing = [table for table in tables if table not in existing]
    if missing:
        raise SystemExit(f"Tabelas ausentes na base origem: {', '.join(missing)}")


def has_table_or_view(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
            (name,),
        ).fetchone()[0]
        > 0
    )


def copy_pleno(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    dst.execute("DROP TABLE IF EXISTS pleno")
    dst.execute(
        """
        CREATE TABLE pleno (
            data_devolucao TEXT NOT NULL,
            loja INTEGER NOT NULL,
            codigo_produto INTEGER NOT NULL,
            nro_nf INTEGER NOT NULL,
            data_nf TEXT NOT NULL,
            nro_pedido INTEGER,
            motivo TEXT,
            causa_pleno TEXT,
            qtd_devolvida REAL,
            tipo_unidade_venda TEXT,
            valor_devolvido REAL
        )
        """
    )
    rows = []
    for row in src.execute(
        """
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
        FROM pleno_devolucao_cd
        """
    ):
        rows.append(
            (
                row[0],
                int(row[1]),
                int(row[2]),
                int(row[3]),
                row[4],
                row[5],
                row[6],
                extract_causa(row[6]),
                row[7],
                row[8],
                row[9],
            )
        )
    dst.executemany(
        """
        INSERT INTO pleno (
            data_devolucao, loja, codigo_produto, nro_nf, data_nf, nro_pedido,
            motivo, causa_pleno, qtd_devolvida, tipo_unidade_venda, valor_devolvido
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    dst.execute("CREATE INDEX idx_central_pleno_item ON pleno (loja, nro_nf, codigo_produto)")
    dst.execute("CREATE INDEX idx_central_pleno_data ON pleno (data_nf, loja)")
    return len(rows)


def copy_envios(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    dst.execute("DROP TABLE IF EXISTS envios_arquivo")
    dst.execute(
        """
        CREATE TABLE envios_arquivo (
            source_zip TEXT,
            folder_date TEXT,
            file_name TEXT NOT NULL,
            nro_loja INTEGER NOT NULL,
            nro_nf_gerado INTEGER NOT NULL,
            nro_nf_original INTEGER NOT NULL,
            data_nf TEXT NOT NULL,
            codigo_interno INTEGER NOT NULL,
            qtd_devolvida REAL,
            causa_devolucao TEXT,
            tipo_unidade_venda TEXT
        )
        """
    )
    rows = []
    for row in src.execute(
        """
        SELECT
            source_zip,
            folder_date,
            file_name,
            nro_loja,
            nro_nf,
            data_nf,
            codigo_interno,
            qtd_devolvida,
            causa_devolucao,
            tipo_unidade_venda
        FROM arquivos_devolucao
        """
    ):
        nro_nf_gerado = int(row[4])
        rows.append(
            (
                row[0],
                row[1],
                row[2],
                int(row[3]),
                nro_nf_gerado,
                normalize_generated_note(nro_nf_gerado),
                row[5],
                int(row[6]),
                row[7],
                row[8] or "",
                row[9],
            )
        )
    dst.executemany(
        """
        INSERT INTO envios_arquivo (
            source_zip, folder_date, file_name, nro_loja, nro_nf_gerado, nro_nf_original,
            data_nf, codigo_interno, qtd_devolvida, causa_devolucao, tipo_unidade_venda
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    dst.execute(
        "CREATE INDEX idx_central_envios_item ON envios_arquivo (nro_loja, nro_nf_original, codigo_interno)"
    )
    return len(rows)


def copy_as400(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    dst.execute("DROP TABLE IF EXISTS as400")
    dst.execute(
        """
        CREATE TABLE as400 (
            linha_excel INTEGER,
            loja INTEGER NOT NULL,
            nota INTEGER NOT NULL,
            nota_normalizada INTEGER NOT NULL,
            data_nf TEXT,
            produto INTEGER NOT NULL,
            causa TEXT,
            quantidade REAL,
            ano INTEGER,
            mes INTEGER,
            dia INTEGER
        )
        """
    )
    rows = []
    for row in src.execute(
        """
        SELECT
            linha_excel,
            loja,
            nota,
            nota_normalizada,
            data_nf,
            produto,
            causa,
            qtda,
            ano,
            mes,
            dia
        FROM as400_devolucoes_completo
        WHERE loja IS NOT NULL
          AND nota IS NOT NULL
          AND produto IS NOT NULL
        """
    ):
        rows.append(
            (
                int(float(row[0])) if row[0] not in (None, "") else None,
                int(float(row[1])),
                int(float(row[2])),
                normalize_generated_note(row[3] if row[3] not in (None, "") else row[2]),
                row[4],
                int(float(row[5])),
                "" if row[6] is None else str(row[6]).strip(),
                float(row[7]) if row[7] not in (None, "") else None,
                int(float(row[8])) if row[8] not in (None, "") else None,
                int(float(row[9])) if row[9] not in (None, "") else None,
                int(float(row[10])) if row[10] not in (None, "") else None,
            )
        )
    dst.executemany(
        """
        INSERT INTO as400 (
            linha_excel, loja, nota, nota_normalizada, data_nf, produto,
            causa, quantidade, ano, mes, dia
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    dst.execute("CREATE INDEX idx_central_as400_item ON as400 (loja, nota_normalizada, produto)")
    return len(rows)


def copy_as400_qlik(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    dst.execute("DROP TABLE IF EXISTS as400_qlik")
    dst.execute(
        """
        CREATE TABLE as400_qlik (
            origem_aba TEXT,
            loja INTEGER NOT NULL,
            nr_devolucao INTEGER NOT NULL,
            nr_devolucao_normalizado INTEGER NOT NULL,
            data_nf TEXT,
            data_transmissao TEXT,
            data_confirmacao TEXT,
            status_qlik TEXT,
            cd_artigo INTEGER NOT NULL,
            causa_devolucao TEXT,
            qtd_enviada REAL,
            qtd_confirmada REAL,
            artigo_desc TEXT
        )
        """
    )
    rows = []
    table_name = "as400_qlik"
    if (
        src.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='as400_qlik'"
        ).fetchone()[0]
        == 0
    ):
        table_name = "as400_qlik_confirmado"
    query = f"""
        SELECT
            {'origem_aba,' if table_name == 'as400_qlik' else "'Confirmados' AS origem_aba,"}
            loja,
            nr_devolucao,
            data_nf,
            data_transmissao,
            data_confirmacao,
            {'origem_aba AS status_qlik,' if table_name == 'as400_qlik' else "'Confirmados' AS status_qlik,"}
            cd_artigo,
            causa_devolucao,
            qtd_enviada,
            qtd_confirmada,
            artigo_desc
        FROM {table_name}
        WHERE loja IS NOT NULL
          AND nr_devolucao IS NOT NULL
          AND cd_artigo IS NOT NULL
    """
    for row in src.execute(query):
        nr_devolucao = int(row[2])
        rows.append(
            (
                row[0],
                int(row[1]),
                nr_devolucao,
                normalize_generated_note(nr_devolucao),
                row[3],
                row[4],
                row[5],
                row[6],
                int(row[7]),
                "" if row[8] is None else str(row[8]).strip(),
                row[9],
                row[10],
                row[11],
            )
        )
    dst.executemany(
        """
        INSERT INTO as400_qlik (
            origem_aba, loja, nr_devolucao, nr_devolucao_normalizado, data_nf, data_transmissao,
            data_confirmacao, status_qlik, cd_artigo, causa_devolucao, qtd_enviada, qtd_confirmada, artigo_desc
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    dst.execute(
        "CREATE INDEX idx_central_qlik_item ON as400_qlik (loja, nr_devolucao_normalizado, cd_artigo)"
    )
    return len(rows)


def copy_as400_erros(src: sqlite3.Connection, dst: sqlite3.Connection) -> int:
    dst.execute("DROP TABLE IF EXISTS as400_erros")
    dst.execute(
        """
        CREATE TABLE as400_erros (
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
            origem_artigo TEXT
        )
        """
    )
    rows = []
    base_rows = src.execute(
        """
        SELECT
            loja,
            data_nota,
            numero_nota,
            numero_nota_original,
            art1_codigo_artigo,
            art1_causa_devolucao,
            art2_codigo_artigo,
            art2_causa_devolucao,
            art3_codigo_artigo,
            art3_causa_devolucao,
            erro,
            codigo_transacao,
            tipo_devolucao,
            numero_remito_interno
        FROM as400_erros_junho
        WHERE loja IS NOT NULL
        """
    )
    for row in base_rows:
        article_data = [
            ("art1", row[4], row[5]),
            ("art2", row[6], row[7]),
            ("art3", row[8], row[9]),
        ]
        for origem, codigo_produto, causa in article_data:
            if codigo_produto in (None, ""):
                continue
            rows.append(
                (
                    int(row[0]),
                    row[1],
                    int(row[2]) if row[2] not in (None, "") else None,
                    int(row[3]) if row[3] not in (None, "") else None,
                    int(codigo_produto),
                    "" if causa is None else str(causa).strip(),
                    row[10],
                    row[11],
                    row[12],
                    row[13],
                    origem,
                )
            )
    dst.executemany(
        """
        INSERT INTO as400_erros (
            loja, data_nota, numero_nota, numero_nota_original, codigo_produto,
            causa_devolucao, erro_as400, codigo_transacao, tipo_devolucao,
            numero_remito_interno, origem_artigo
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    dst.execute(
        "CREATE INDEX idx_central_erros_item ON as400_erros (loja, numero_nota_original, codigo_produto)"
    )
    return len(rows)


def build_pleno_status(dst: sqlite3.Connection) -> int:
    dst.execute("DROP TABLE IF EXISTS pleno_status")
    as400_union_extra = ""
    erros_union_extra = ""
    if has_table_or_view(dst, "as400_db2_live"):
        as400_union_extra = """
                UNION ALL
                SELECT
                    loja,
                    nota,
                    nota_normalizada,
                    data_nf,
                    produto,
                    causa
                FROM as400_db2_live
        """
    if has_table_or_view(dst, "as400_erros_db2_live"):
        erros_union_extra = """
                UNION ALL
                SELECT
                    loja,
                    numero_nota_original AS nro_nf,
                    codigo_produto,
                    erro_as400,
                    data_nota
                FROM as400_erros_db2_live
        """

    dst.executescript(
        f"""
        CREATE TABLE pleno_status AS
        WITH envios AS (
            SELECT
                nro_loja AS loja,
                nro_nf_original AS nro_nf,
                codigo_interno AS codigo_produto,
                MIN(file_name) AS primeiro_arquivo_enviado,
                GROUP_CONCAT(DISTINCT file_name) AS arquivos_enviados,
                COUNT(*) AS qtd_linhas_enviadas,
                COUNT(DISTINCT file_name) AS qtd_arquivos_enviados,
                COUNT(DISTINCT nro_nf_gerado) AS qtd_vezes_enviado_as400,
                MIN(folder_date) AS primeira_pasta_envio,
                MAX(folder_date) AS ultima_pasta_envio
            FROM envios_arquivo
            GROUP BY nro_loja, nro_nf_original, codigo_interno
        ),
        as400_base AS (
            SELECT
                loja,
                nota_normalizada AS nro_nf,
                produto AS codigo_produto,
                MIN(nota) AS nota_as400_exemplo,
                MIN(data_nf) AS primeira_data_as400,
                MAX(data_nf) AS ultima_data_as400,
                GROUP_CONCAT(DISTINCT causa) AS causas_as400,
                COUNT(*) AS qtd_linhas_as400
            FROM (
                SELECT
                    loja,
                    nota,
                    nota_normalizada,
                    data_nf,
                    produto,
                    causa
                FROM as400
                {as400_union_extra}
            ) as400_union
            GROUP BY loja, nota_normalizada, produto
        ),
        qlik_base AS (
            SELECT
                loja,
                nr_devolucao_normalizado AS nro_nf,
                cd_artigo AS codigo_produto,
                MIN(CASE WHEN lower(IFNULL(origem_aba, '')) = 'confirmados' THEN nr_devolucao END) AS nota_qlik_exemplo,
                MIN(data_nf) AS primeira_data_qlik,
                MAX(data_confirmacao) AS ultima_confirmacao_qlik,
                GROUP_CONCAT(DISTINCT causa_devolucao) AS causas_qlik,
                GROUP_CONCAT(DISTINCT origem_aba) AS origens_qlik,
                COUNT(*) AS qtd_linhas_qlik,
                MAX(CASE WHEN lower(IFNULL(origem_aba, '')) = 'confirmados' THEN 1 ELSE 0 END) AS confirmado_qlik
            FROM as400_qlik
            GROUP BY loja, nr_devolucao_normalizado, cd_artigo
        ),
        erros AS (
            SELECT
                loja,
                nro_nf,
                codigo_produto,
                GROUP_CONCAT(DISTINCT erro_as400) AS erros_as400,
                MIN(data_nota) AS primeira_data_erro,
                MAX(data_nota) AS ultima_data_erro,
                COUNT(*) AS qtd_linhas_erro
            FROM (
                SELECT
                    loja,
                    numero_nota_original AS nro_nf,
                    codigo_produto,
                    erro_as400,
                    data_nota
                FROM as400_erros
                WHERE numero_nota_original IS NOT NULL
                {erros_union_extra}
            ) erros_union
            GROUP BY loja, nro_nf, codigo_produto
        )
        SELECT
            p.data_devolucao,
            p.loja,
            p.codigo_produto,
            p.nro_nf,
            p.data_nf,
            p.nro_pedido,
            p.motivo,
            p.causa_pleno,
            p.qtd_devolvida,
            p.tipo_unidade_venda,
            p.valor_devolvido,
            CASE WHEN e.loja IS NOT NULL THEN 'SIM' ELSE 'NAO' END AS enviado,
            COALESCE(e.primeiro_arquivo_enviado, '') AS primeiro_arquivo_enviado,
            COALESCE(e.arquivos_enviados, '') AS arquivos_enviados,
            COALESCE(e.qtd_linhas_enviadas, 0) AS qtd_linhas_enviadas,
            COALESCE(e.qtd_arquivos_enviados, 0) AS qtd_arquivos_enviados,
            COALESCE(e.qtd_vezes_enviado_as400, 0) AS qtd_vezes_enviado_as400,
            COALESCE(e.primeira_pasta_envio, '') AS primeira_pasta_envio,
            COALESCE(e.ultima_pasta_envio, '') AS ultima_pasta_envio,
            CASE WHEN a.loja IS NOT NULL THEN 'SIM' ELSE 'NAO' END AS conciliado_as400,
            CASE WHEN IFNULL(q.confirmado_qlik, 0) = 1 THEN 'SIM' ELSE 'NAO' END AS conciliado_qlik,
            CASE WHEN a.loja IS NOT NULL OR IFNULL(q.confirmado_qlik, 0) = 1 THEN 'SIM' ELSE 'NAO' END AS conciliado,
            COALESCE(a.nota_as400_exemplo, '') AS nota_as400_exemplo,
            COALESCE(a.primeira_data_as400, '') AS primeira_data_as400,
            COALESCE(a.ultima_data_as400, '') AS ultima_data_as400,
            COALESCE(a.causas_as400, '') AS causas_as400,
            COALESCE(a.qtd_linhas_as400, 0) AS qtd_linhas_as400,
            COALESCE(q.nota_qlik_exemplo, '') AS nota_qlik_exemplo,
            COALESCE(q.primeira_data_qlik, '') AS primeira_data_qlik,
            COALESCE(q.ultima_confirmacao_qlik, '') AS ultima_confirmacao_qlik,
            COALESCE(q.causas_qlik, '') AS causas_qlik,
            COALESCE(q.origens_qlik, '') AS origens_qlik,
            COALESCE(q.qtd_linhas_qlik, 0) AS qtd_linhas_qlik,
            COALESCE(r.erros_as400, '') AS erro_as400,
            COALESCE(r.primeira_data_erro, '') AS primeira_data_erro,
            COALESCE(r.ultima_data_erro, '') AS ultima_data_erro,
            COALESCE(r.qtd_linhas_erro, 0) AS qtd_linhas_erro,
            CASE
                WHEN a.loja IS NOT NULL OR IFNULL(q.confirmado_qlik, 0) = 1 THEN 'CONCILIADO'
                WHEN r.loja IS NOT NULL THEN 'ERRO_AS400'
                WHEN e.loja IS NOT NULL THEN 'ENVIADO'
                ELSE 'PENDENTE_ENVIO'
            END AS status
        FROM pleno p
        LEFT JOIN envios e
            ON e.loja = p.loja
           AND e.nro_nf = p.nro_nf
           AND e.codigo_produto = p.codigo_produto
        LEFT JOIN as400_base a
            ON a.loja = p.loja
           AND a.nro_nf = p.nro_nf
           AND a.codigo_produto = p.codigo_produto
        LEFT JOIN qlik_base q
            ON q.loja = p.loja
           AND q.nro_nf = p.nro_nf
           AND q.codigo_produto = p.codigo_produto
        LEFT JOIN erros r
            ON r.loja = p.loja
           AND r.nro_nf = p.nro_nf
           AND r.codigo_produto = p.codigo_produto;

        CREATE INDEX idx_central_status_item ON pleno_status (loja, nro_nf, codigo_produto);
        CREATE INDEX idx_central_status_resumo ON pleno_status (status, loja, data_nf);

        DROP VIEW IF EXISTS resumo_status;
        CREATE VIEW resumo_status AS
        SELECT status, COUNT(*) AS total_linhas
        FROM pleno_status
        GROUP BY status
        ORDER BY total_linhas DESC;
        """
    )
    return int(dst.execute("SELECT COUNT(*) FROM pleno_status").fetchone()[0])


def write_metadata(dst: sqlite3.Connection, source_db: Path) -> None:
    dst.execute("DROP TABLE IF EXISTS metadados")
    dst.execute("CREATE TABLE metadados (chave TEXT PRIMARY KEY, valor TEXT NOT NULL)")
    values = [
        ("source_db", str(source_db)),
        ("gerado_em", datetime.now().isoformat(timespec="seconds")),
        ("descricao", "Base central de devolucoes com cruzamento Pleno x Envios x AS400 x AS400_QLIK x Erros"),
    ]
    dst.executemany("INSERT INTO metadados (chave, valor) VALUES (?, ?)", values)


def main() -> None:
    args = parse_args()
    source_db = Path(args.source_db).expanduser().resolve()
    target_db = Path(args.target_db).expanduser().resolve()
    target_db.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(source_db) as src, sqlite3.connect(target_db) as dst:
        require_source_tables(src, ["pleno_devolucao_cd", "arquivos_devolucao", "as400_devolucoes_completo", "as400_erros_junho"])
        if not (has_table_or_view(src, "as400_qlik") or has_table_or_view(src, "as400_qlik_confirmado")):
            raise SystemExit("Tabelas ausentes na base origem: as400_qlik ou as400_qlik_confirmado")
        pleno_total = copy_pleno(src, dst)
        envios_total = copy_envios(src, dst)
        as400_total = copy_as400(src, dst)
        qlik_total = copy_as400_qlik(src, dst)
        erros_total = copy_as400_erros(src, dst)
        status_total = build_pleno_status(dst)
        write_metadata(dst, source_db)
        dst.commit()

    print(f"Base central criada em: {target_db}")
    print(f"linhas_pleno={pleno_total}")
    print(f"linhas_envios_arquivo={envios_total}")
    print(f"linhas_as400={as400_total}")
    print(f"linhas_as400_qlik={qlik_total}")
    print(f"linhas_as400_erros={erros_total}")
    print(f"linhas_pleno_status={status_total}")


if __name__ == "__main__":
    main()
