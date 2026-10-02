#!/usr/bin/env python3
import argparse
import csv
import sqlite3
from calendar import monthrange
from datetime import date, datetime, timedelta
from pathlib import Path
from decimal import Decimal, InvalidOperation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gera um CSV consolidado apenas com os itens marcados para REENVIAR."
    )
    parser.add_argument(
        "--db",
        default="outputs/devolucao_auditoria.sqlite",
        help="Caminho do banco SQLite.",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/devolucao_as400",
        help="Pasta de saida do CSV.",
    )
    parser.add_argument(
        "--file-name",
        default="DEVOLUCAO_CD_REENVIAR_AS400.csv",
        help="Nome do arquivo CSV gerado.",
    )
    return parser.parse_args()


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


def fetch_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return list(
        conn.execute(
            """
            SELECT
                nro_loja,
                nro_nf_gerado AS nro_nf,
                data_nf,
                codigo_interno,
                qtd_devolvida,
                causa_devolucao,
                tipo_unidade_venda
            FROM devolucao_export_status_detalhe
            WHERE status = 'REENVIAR'
              AND classificacao_nota = 'LOJA'
            ORDER BY data_nf, nro_loja, nro_nf_gerado, codigo_interno
            """
        )
    )


def write_csv(output_path: Path, rows: list[sqlite3.Row]) -> None:
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
                    int(row["nro_nf"]),
                    normalize_export_date(str(row["data_nf"])),
                    int(row["codigo_interno"]),
                    format_quantity(row["qtd_devolvida"]),
                    row["causa_devolucao"] or "",
                    row["tipo_unidade_venda"] or "",
                ]
            )


def main() -> None:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / args.file_name

    with sqlite3.connect(db_path) as conn:
        rows = fetch_rows(conn)

    if not rows:
        raise SystemExit("Nenhum item com status REENVIAR encontrado.")

    write_csv(output_path, rows)

    print(f"Banco SQLite: {db_path}")
    print(f"Arquivo gerado: {output_path}")
    print(f"Itens gerados: {len(rows)}")


if __name__ == "__main__":
    main()
