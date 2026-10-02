#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "outputs/devolucao_central.sqlite"
DEFAULT_OUTPUT = ROOT / "reports" / "duplicidades_devolucao_mes6.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Gera uma planilha de duplicidade de subida de devolucoes no mes 06, "
            "usando a familia da nota normalizada e as variacoes enviadas."
        )
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Base SQLite central.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="CSV de saida.")
    return parser.parse_args()


def file_month_expr() -> str:
    return """
        CASE
            WHEN file_name GLOB 'DEVOLUCAO*_20*.csv'
            THEN substr(
                replace(
                    replace(file_name, 'DEVOLUCAO_CD_', ''),
                    'DEVOLUCAO_', ''
                ),
                1,
                6
            )
            ELSE NULL
        END
    """


def build_query() -> str:
    return f"""
        WITH envios_limpos AS (
            SELECT
                nro_loja AS loja,
                nro_nf_original AS nota_base,
                data_nf,
                codigo_interno AS artigo,
                qtd_devolvida,
                causa_devolucao,
                tipo_unidade_venda,
                nro_nf_gerado,
                file_name,
                {file_month_expr()} AS arquivo_mes
            FROM envios_arquivo
        ),
        familias_envio AS (
            SELECT
                loja,
                nota_base,
                data_nf,
                artigo,
                MAX(qtd_devolvida) AS qtd_devolvida,
                MAX(causa_devolucao) AS causa_devolucao,
                MAX(tipo_unidade_venda) AS tipo_unidade_venda,
                COUNT(DISTINCT nro_nf_gerado) AS qtd_notas_enviadas,
                GROUP_CONCAT(DISTINCT nro_nf_gerado) AS notas_enviadas,
                GROUP_CONCAT(DISTINCT file_name) AS arquivos_origem,
                SUM(CASE WHEN arquivo_mes = '202606' THEN 1 ELSE 0 END) AS linhas_arquivo_mes6
            FROM envios_limpos
            GROUP BY loja, nota_base, data_nf, artigo
            HAVING COUNT(DISTINCT nro_nf_gerado) > 1
               AND SUM(CASE WHEN arquivo_mes = '202606' THEN 1 ELSE 0 END) > 0
        ),
        consulta_mes6 AS (
            SELECT
                loja,
                nr_devolucao_normalizado AS nota_base,
                data_nf,
                cd_artigo AS artigo,
                MAX(artigo_desc) AS artigo_desc,
                COUNT(DISTINCT nr_devolucao) AS qtd_notas_consulta,
                GROUP_CONCAT(DISTINCT nr_devolucao) AS notas_consulta,
                MIN(data_transmissao) AS primeira_transmissao,
                MAX(data_transmissao) AS ultima_transmissao,
                MIN(data_confirmacao) AS primeira_confirmacao,
                MAX(data_confirmacao) AS ultima_confirmacao
            FROM as400_qlik
            WHERE substr(COALESCE(data_confirmacao, data_transmissao, data_nf), 1, 7) = '2026-06'
            GROUP BY loja, nr_devolucao_normalizado, data_nf, cd_artigo
        )
        SELECT
            f.loja,
            f.nota_base,
            f.data_nf,
            f.artigo,
            COALESCE(c.artigo_desc, '') AS artigo_desc,
            f.causa_devolucao,
            f.tipo_unidade_venda,
            f.qtd_devolvida,
            f.qtd_notas_enviadas,
            f.notas_enviadas,
            COALESCE(c.qtd_notas_consulta, 0) AS qtd_notas_consulta_mes6,
            COALESCE(c.notas_consulta, '') AS notas_consulta_mes6,
            COALESCE(c.primeira_transmissao, '') AS primeira_transmissao,
            COALESCE(c.ultima_transmissao, '') AS ultima_transmissao,
            COALESCE(c.primeira_confirmacao, '') AS primeira_confirmacao,
            COALESCE(c.ultima_confirmacao, '') AS ultima_confirmacao,
            f.arquivos_origem
        FROM familias_envio f
        JOIN consulta_mes6 c
          ON c.loja = f.loja
         AND c.nota_base = f.nota_base
         AND c.data_nf = f.data_nf
         AND c.artigo = f.artigo
        ORDER BY f.loja, f.data_nf, f.nota_base, f.artigo
    """


def write_csv(rows: list[sqlite3.Row], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp, delimiter=";")
        writer.writerow(rows[0].keys())
        for row in rows:
            writer.writerow([row[key] for key in row.keys()])


def main() -> None:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = list(conn.execute(build_query()))

    if not rows:
        print("Nenhuma duplicidade de subida encontrada para o mes 06 com a regra atual.")
        print(f"Base: {db_path}")
        return

    write_csv(rows, output_path)
    print(f"Base: {db_path}")
    print(f"Arquivo: {output_path}")
    print(f"Linhas: {len(rows)}")


if __name__ == "__main__":
    main()
