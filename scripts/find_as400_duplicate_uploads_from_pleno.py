#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "outputs/devolucao_central.sqlite"
DEFAULT_OUTPUT_DIR = ROOT / "reports"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Parte das notas originais do Pleno e procura duplicidade de subida no "
            "AS400/Qlik quando a mesma devolucao aparece com mais de uma numeracao "
            "para a mesma loja, data e artigo."
        )
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Base SQLite central.")
    parser.add_argument("--loja", type=int, help="Filtra uma loja especifica.")
    parser.add_argument("--artigo", type=int, help="Filtra um artigo especifico.")
    parser.add_argument("--nota", type=int, help="Filtra a nota original do Pleno.")
    parser.add_argument("--data-nf", help="Filtra a data da nota no formato YYYY-MM-DD.")
    parser.add_argument(
        "--output",
        help="Arquivo CSV de saida. Se omitido, grava em reports/ com nome padrao.",
    )
    return parser.parse_args()


def build_query() -> str:
    return """
        WITH base_pleno AS (
            SELECT
                p.loja,
                p.nro_nf AS nota_pleno,
                p.data_nf,
                p.codigo_produto AS artigo,
                p.causa_pleno,
                p.motivo,
                p.qtd_devolvida,
                p.tipo_unidade_venda
            FROM pleno p
            WHERE 1 = 1
              AND (:loja IS NULL OR p.loja = :loja)
              AND (:artigo IS NULL OR p.codigo_produto = :artigo)
              AND (:nota IS NULL OR p.nro_nf = :nota)
              AND (:data_nf IS NULL OR p.data_nf = :data_nf)
        ),
        as400_matches AS (
            SELECT
                b.loja,
                b.nota_pleno,
                b.data_nf,
                b.artigo,
                b.causa_pleno,
                b.motivo,
                b.qtd_devolvida,
                b.tipo_unidade_venda,
                q.nr_devolucao,
                q.nr_devolucao_normalizado,
                q.data_transmissao,
                q.data_confirmacao,
                q.status_qlik,
                q.causa_devolucao AS causa_as400,
                q.qtd_enviada,
                q.qtd_confirmada
            FROM base_pleno b
            JOIN as400_qlik q
              ON q.loja = b.loja
             AND q.cd_artigo = b.artigo
             AND q.data_nf = b.data_nf
             AND q.nr_devolucao_normalizado = b.nota_pleno
        ),
        grupos_duplicados AS (
            SELECT
                loja,
                nota_pleno,
                data_nf,
                artigo,
                COUNT(DISTINCT nr_devolucao) AS qtd_notas_as400,
                GROUP_CONCAT(DISTINCT nr_devolucao) AS notas_as400
            FROM as400_matches
            GROUP BY loja, nota_pleno, data_nf, artigo
            HAVING COUNT(DISTINCT nr_devolucao) > 1
        )
        SELECT
            a.loja,
            a.nota_pleno,
            a.data_nf,
            a.artigo,
            a.causa_pleno,
            a.motivo,
            a.qtd_devolvida,
            a.tipo_unidade_venda,
            g.qtd_notas_as400,
            g.notas_as400,
            a.nr_devolucao,
            a.data_transmissao,
            a.data_confirmacao,
            a.status_qlik,
            a.causa_as400,
            a.qtd_enviada,
            a.qtd_confirmada
        FROM as400_matches a
        JOIN grupos_duplicados g
          ON g.loja = a.loja
         AND g.nota_pleno = a.nota_pleno
         AND g.data_nf = a.data_nf
         AND g.artigo = a.artigo
        ORDER BY a.loja, a.data_nf, a.nota_pleno, a.artigo, a.nr_devolucao
    """


def default_output_path(args: argparse.Namespace) -> Path:
    suffix = []
    if args.loja is not None:
        suffix.append(f"loja{args.loja}")
    if args.artigo is not None:
        suffix.append(f"art{args.artigo}")
    if args.nota is not None:
        suffix.append(f"nf{args.nota}")
    if args.data_nf:
        suffix.append(args.data_nf.replace("-", ""))
    name = "duplicidades_as400_pleno"
    if suffix:
        name += "_" + "_".join(suffix)
    return DEFAULT_OUTPUT_DIR / f"{name}.csv"


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
    output_path = Path(args.output).expanduser().resolve() if args.output else default_output_path(args)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = list(
            conn.execute(
                build_query(),
                {
                    "loja": args.loja,
                    "artigo": args.artigo,
                    "nota": args.nota,
                    "data_nf": args.data_nf,
                },
            )
        )

    if not rows:
        print("Nenhuma duplicidade encontrada para os filtros informados.")
        print(f"Base: {db_path}")
        return

    write_csv(rows, output_path)
    grupos = {
        (row["loja"], row["nota_pleno"], row["data_nf"], row["artigo"])
        for row in rows
    }
    print(f"Base: {db_path}")
    print(f"Arquivo: {output_path}")
    print(f"Grupos duplicados: {len(grupos)}")
    print(f"Linhas detalhadas: {len(rows)}")


if __name__ == "__main__":
    main()
