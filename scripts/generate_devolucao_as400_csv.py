#!/usr/bin/env python3
import argparse
import csv
import re
import sqlite3
from calendar import monthrange
from datetime import date, datetime, timedelta
from pathlib import Path
from decimal import Decimal, InvalidOperation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gera arquivos de devolucao no layout do AS400 a partir da base SQLite local."
    )
    parser.add_argument(
        "--db",
        default="outputs/devolucao_auditoria.sqlite",
        help="Caminho do banco SQLite de auditoria.",
    )
    parser.add_argument(
        "--source-table",
        default="apenas_no_pleno",
        help="Tabela-base da diferenca. Ex.: apenas_no_pleno ou apenas_no_pleno_vs_as400.",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/devolucao_as400",
        help="Pasta de saida dos CSVs gerados.",
    )
    parser.add_argument(
        "--mode",
        choices=["missing", "note"],
        default="missing",
        help="missing = gera o que esta em apenas_no_pleno; note = gera uma nota especifica do pleno_devolucao_cd.",
    )
    parser.add_argument("--loja", type=int, help="Loja para o modo note.")
    parser.add_argument("--nro-nf", type=int, help="Numero da devolucao original para o modo note.")
    parser.add_argument("--data-nf", help="Data da devolucao/origem no formato YYYY-MM-DD para o modo note.")
    parser.add_argument(
        "--only-first-cause",
        action="store_true",
        help="Para teste: dentro de cada nota, gera apenas os itens com a primeira causa encontrada pelo menor codigo_produto.",
    )
    parser.add_argument(
        "--split-by-cause",
        action="store_true",
        help="Quebra notas multicausa em um arquivo por causa, numerando 99XXXX, 98XXXX, 97XXXX e assim por diante.",
    )
    parser.add_argument(
        "--difference-only",
        action="store_true",
        help="Para reprocesso: ignora a primeira causa da nota e gera apenas as causas seguintes, renumerando a primeira diferenca como 99XXXX.",
    )
    parser.add_argument(
        "--single-file",
        action="store_true",
        help="Gera um unico CSV com todas as linhas, em vez de um arquivo por nota.",
    )
    parser.add_argument(
        "--prefix-start",
        type=int,
        default=99,
        help="Prefixo inicial para renumerar a nota. Ex.: 99 gera 99XXXX; 98 gera 98XXXX.",
    )
    parser.add_argument(
        "--remaining-after-manual",
        action="store_true",
        help="Gera apenas os itens ainda faltantes apos reprocessos ja gravados como manual_reprocesso, usando o proximo prefixo livre.",
    )
    return parser.parse_args()


def format_nro_nf(nro_nf: int, cause_index: int = 0, prefix_start: int = 99) -> int:
    prefix = prefix_start - cause_index
    if prefix < 10:
        raise ValueError(f"Quantidade de causas excede o formato suportado para a nota {nro_nf}.")
    return int(f"{prefix}{nro_nf:04d}")


def format_quantity(value) -> str:
    if value is None or value == "":
        return ""
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        return str(value)
    if dec == dec.to_integral():
        return str(dec.to_integral())
    normalized = format(dec.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def normalize_export_date(data_nf: str, today: date | None = None) -> str:
    if not data_nf:
        return data_nf
    today = today or date.today()
    source = datetime.strptime(data_nf, "%Y-%m-%d").date()
    first_day_current_month = today.replace(day=1)
    previous_month_last_day = first_day_current_month - timedelta(days=1)
    previous_month_first_day = previous_month_last_day.replace(day=1)
    if source >= previous_month_first_day:
        return data_nf
    target_year = previous_month_first_day.year
    target_month = previous_month_first_day.month
    target_day = min(source.day, monthrange(target_year, target_month)[1])
    return date(target_year, target_month, target_day).isoformat()


def parse_causa(motivo: str | None) -> str:
    if not motivo:
        return ""
    match = re.search(r"CAUSA\s+(\d+)", motivo)
    return match.group(1) if match else ""


CAUSE_SQL = """
CASE
    WHEN p.motivo LIKE 'CAUSA %' THEN substr(p.motivo, 7, instr(substr(p.motivo, 7), ' ') - 1)
    ELSE ''
END
"""


def source_select_sql(source_table: str) -> str:
    return f"""
        WITH enviados_ok AS (
            SELECT
                nro_loja,
                data_nf,
                CASE
                    WHEN length(CAST(nro_nf AS TEXT)) > 4
                     AND CAST(substr(CAST(nro_nf AS TEXT), 1, 2) AS INTEGER) BETWEEN 90 AND 99
                    THEN CAST(substr(CAST(nro_nf AS TEXT), 3) AS INTEGER)
                    ELSE nro_nf
                END AS nro_nf_original,
                codigo_interno,
                causa_devolucao
            FROM arquivos_devolucao
        )
        SELECT
            p.loja AS nro_loja,
            p.nro_nf,
            p.data_nf,
            p.codigo_produto AS codigo_interno,
            p.qtd_devolvida,
            p.motivo,
            p.tipo_unidade_venda
        FROM {source_table} p
        LEFT JOIN enviados_ok e
            ON e.nro_loja = p.loja
           AND e.data_nf = p.data_nf
           AND e.nro_nf_original = p.nro_nf
           AND e.codigo_interno = p.codigo_produto
           AND IFNULL(e.causa_devolucao, '') = {CAUSE_SQL}
        WHERE e.codigo_interno IS NULL
          AND IFNULL({CAUSE_SQL}, '') <> ''
          AND p.nro_nf <= 1000
    """


def fetch_rows(conn: sqlite3.Connection, args: argparse.Namespace) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    if args.mode == "missing":
        query = f"""
            SELECT *
            FROM (
                {source_select_sql(args.source_table)}
            ) src
            ORDER BY data_nf, nro_loja, nro_nf, codigo_interno
        """
        return list(conn.execute(query))

    if args.loja is None or args.nro_nf is None or not args.data_nf:
        raise SystemExit("No modo note, informe --loja, --nro-nf e --data-nf.")

    if args.remaining_after_manual:
        query = f"""
            SELECT *
            FROM (
                {source_select_sql(args.source_table)}
            ) src
            WHERE nro_loja = ?
              AND nro_nf = ?
              AND data_nf = ?
            ORDER BY codigo_interno
        """
        return list(conn.execute(query, (args.loja, args.nro_nf, args.data_nf)))

    query = f"""
        SELECT *
        FROM (
            {source_select_sql(args.source_table)}
        ) src
        WHERE nro_loja = ?
          AND nro_nf = ?
          AND data_nf = ?
        ORDER BY codigo_interno
    """
    return list(conn.execute(query, (args.loja, args.nro_nf, args.data_nf)))


def get_next_prefix_start(conn: sqlite3.Connection, loja: int, nro_nf: int, data_nf: str) -> int:
    row = conn.execute(
        """
        SELECT MIN(CAST(substr(CAST(nro_nf AS TEXT), 1, 2) AS INTEGER)) AS menor_prefixo
        FROM arquivos_devolucao
        WHERE nro_loja = ?
          AND data_nf = ?
          AND length(CAST(nro_nf AS TEXT)) > 4
          AND CAST(substr(CAST(nro_nf AS TEXT), 1, 2) AS INTEGER) BETWEEN 90 AND 99
          AND CAST(substr(CAST(nro_nf AS TEXT), 3) AS INTEGER) = ?
        """,
        (loja, data_nf, nro_nf),
    ).fetchone()
    if row and row[0] is not None:
        return int(row[0]) - 1
    return 99


def generated_note_exists(conn: sqlite3.Connection, loja: int, generated_nro_nf: int) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM (
            SELECT nro_nf AS note_number, nro_loja AS loja
            FROM arquivos_devolucao
            UNION ALL
            SELECT nr_devolucao AS note_number, loja
            FROM as400_qlik_confirmado
        ) t
        WHERE t.loja = ?
          AND t.note_number = ?
        LIMIT 1
        """,
        (loja, generated_nro_nf),
    ).fetchone()
    return row is not None


def find_available_prefixes(
    conn: sqlite3.Connection,
    loja: int,
    nro_nf_original: int,
    quantity: int,
    prefix_start: int,
) -> list[int]:
    prefixes: list[int] = []
    candidate = prefix_start
    while len(prefixes) < quantity:
        if candidate < 10:
            raise ValueError(
                f"Sem prefixos disponiveis para loja {loja} e devolucao original {nro_nf_original}."
            )
        generated_nro_nf = format_nro_nf(nro_nf_original, cause_index=0, prefix_start=candidate)
        if not generated_note_exists(conn, loja, generated_nro_nf):
            prefixes.append(candidate)
        candidate -= 1
    return prefixes


def group_key(row: sqlite3.Row) -> tuple[int, int, str]:
    return int(row["nro_loja"]), int(row["nro_nf"]), str(row["data_nf"])


def group_rows_by_note(rows: list[sqlite3.Row]) -> dict[tuple[int, int, str], list[sqlite3.Row]]:
    groups: dict[tuple[int, int, str], list[sqlite3.Row]] = {}
    for row in rows:
        groups.setdefault(group_key(row), []).append(row)
    return groups


def first_cause_for_group(rows: list[sqlite3.Row]) -> str | None:
    ordered = sorted(rows, key=lambda row: int(row["codigo_interno"]))
    return ordered[0]["motivo"] if ordered else None


def ordered_causes_for_group(rows: list[sqlite3.Row]) -> list[str]:
    ordered_rows = sorted(rows, key=lambda row: int(row["codigo_interno"]))
    causes: list[str] = []
    seen: set[str] = set()
    for row in ordered_rows:
        motivo = (row["motivo"] or "").strip()
        if not motivo or motivo in seen:
            continue
        seen.add(motivo)
        causes.append(motivo)
    return causes


def summarize_group(rows: list[sqlite3.Row]) -> tuple[str | None, list[str]]:
    causes = ordered_causes_for_group(rows)
    first_cause = causes[0] if causes else None
    return first_cause, causes


def write_group(output_dir: Path, rows: list[sqlite3.Row], cause_index: int = 0, prefix_start: int = 99) -> Path:
    first = rows[0]
    nro_loja = int(first["nro_loja"])
    nro_nf_original = int(first["nro_nf"])
    data_nf = normalize_export_date(str(first["data_nf"]))
    nro_nf_novo = format_nro_nf(nro_nf_original, cause_index=cause_index, prefix_start=prefix_start)
    safe_date = data_nf.replace("-", "")
    output_path = output_dir / f"DEVOLUCAO_CD_LOJA{nro_loja}_{safe_date}_{nro_nf_novo}.csv"

    with output_path.open("w", newline="", encoding="latin1") as fp:
        writer = csv.writer(fp, delimiter=";")
        writer.writerow(
            [
                "nro_loja",
                "nro_nf",
                "data_nf",
                "codigo_interno",
                "qtd_devolvida",
                "causa_devolucao",
                "tipo_unidade_venda",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    int(row["nro_loja"]),
                    nro_nf_novo,
                    normalize_export_date(str(row["data_nf"])),
                    int(row["codigo_interno"]),
                    format_quantity(row["qtd_devolvida"]),
                    parse_causa(row["motivo"]),
                    row["tipo_unidade_venda"] or "",
                ]
            )
    return output_path


def write_single_file(output_dir: Path, rows: list[tuple[int, sqlite3.Row]], file_name: str, prefix_start: int = 99) -> Path:
    output_path = output_dir / file_name
    with output_path.open("w", newline="", encoding="latin1") as fp:
        writer = csv.writer(fp, delimiter=";")
        writer.writerow(
            [
                "nro_loja",
                "nro_nf",
                "data_nf",
                "codigo_interno",
                "qtd_devolvida",
                "causa_devolucao",
                "tipo_unidade_venda",
            ]
        )
        for cause_index, row in rows:
            writer.writerow(
                [
                    int(row["nro_loja"]),
                    format_nro_nf(int(row["nro_nf"]), cause_index=cause_index, prefix_start=prefix_start),
                    normalize_export_date(str(row["data_nf"])),
                    int(row["codigo_interno"]),
                    format_quantity(row["qtd_devolvida"]),
                    parse_causa(row["motivo"]),
                    row["tipo_unidade_venda"] or "",
                ]
            )
    return output_path


def main() -> None:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        if args.remaining_after_manual and args.mode == "note" and args.loja is not None and args.nro_nf is not None and args.data_nf:
            args.prefix_start = get_next_prefix_start(conn, args.loja, args.nro_nf, args.data_nf)
        rows = fetch_rows(conn, args)
        if not rows:
            raise SystemExit("Nenhum registro encontrado para gerar o arquivo.")

        groups = group_rows_by_note(rows)

        generated_files: list[Path] = []
        multicausa_notes = 0
        single_file_rows: list[tuple[int, sqlite3.Row]] = []
        for note_key, grouped_rows in groups.items():
            loja, nro_nf_original, _data_nf = note_key
            first_cause, causes = summarize_group(grouped_rows)
            if len(causes) > 1:
                multicausa_notes += 1
                loja, nro_nf, data_nf = note_key
                print(
                    f"Nota multicausa detectada: loja={loja} nro_nf={nro_nf} data_nf={data_nf} "
                    f"primeira_causa={first_cause!r} causas={causes!r}"
                )

            if args.split_by_cause:
                causes_to_generate = causes
                if args.difference_only and len(causes) > 1:
                    causes_to_generate = causes[1:]
                elif args.difference_only:
                    causes_to_generate = []

                if causes_to_generate:
                    prefix_sequence = find_available_prefixes(
                        conn,
                        loja,
                        nro_nf_original,
                        len(causes_to_generate),
                        args.prefix_start,
                    )
                    for cause_index, cause in enumerate(causes_to_generate):
                        rows_to_write = [row for row in grouped_rows if (row["motivo"] or "").strip() == cause]
                        if rows_to_write:
                            if args.single_file:
                                single_file_rows.extend(
                                    ((99 - prefix_sequence[cause_index]), row) for row in rows_to_write
                                )
                            else:
                                generated_files.append(
                                    write_group(
                                        output_dir,
                                        rows_to_write,
                                        cause_index=0,
                                        prefix_start=prefix_sequence[cause_index],
                                    )
                                )
                elif not args.difference_only:
                    prefix_sequence = find_available_prefixes(
                        conn,
                        loja,
                        nro_nf_original,
                        1,
                        args.prefix_start,
                    )
                    if args.single_file:
                        single_file_rows.extend(((99 - prefix_sequence[0]), row) for row in grouped_rows)
                    else:
                        generated_files.append(
                            write_group(
                                output_dir,
                                grouped_rows,
                                cause_index=0,
                                prefix_start=prefix_sequence[0],
                            )
                        )
                continue

            rows_to_write = grouped_rows
            if args.only_first_cause and first_cause is not None:
                rows_to_write = [row for row in grouped_rows if row["motivo"] == first_cause]
            if not rows_to_write:
                continue
            if len(causes) > 1:
                loja, nro_nf, data_nf = note_key
                print(
                    f"  itens_gerados={len(rows_to_write)}/{len(grouped_rows)}"
                )
            prefix_sequence = find_available_prefixes(
                conn,
                loja,
                nro_nf_original,
                1,
                args.prefix_start,
            )
            if args.single_file:
                single_file_rows.extend(((99 - prefix_sequence[0]), row) for row in rows_to_write)
            else:
                generated_files.append(
                    write_group(
                        output_dir,
                        rows_to_write,
                        cause_index=0,
                        prefix_start=prefix_sequence[0],
                    )
                )

        if args.single_file and single_file_rows:
            generated_files.append(
                write_single_file(
                    output_dir,
                    single_file_rows,
                    "DEVOLUCAO_CD_TODAS_LOJAS_FALTANTES.csv",
                    prefix_start=args.prefix_start,
                )
            )

    print(f"Banco SQLite: {db_path}")
    print(f"Pasta de saida: {output_dir}")
    print(f"Notas multicausa encontradas: {multicausa_notes}")
    print(f"Filtro only-first-cause: {'SIM' if args.only_first_cause else 'NAO'}")
    print(f"Quebra por causa: {'SIM' if args.split_by_cause else 'NAO'}")
    print(f"Somente diferenca: {'SIM' if args.difference_only else 'NAO'}")
    print(f"Arquivos gerados: {len(generated_files)}")
    for path in generated_files[:20]:
        print(path)
    if len(generated_files) > 20:
        print(f"... e mais {len(generated_files) - 20} arquivo(s)")


if __name__ == "__main__":
    main()
