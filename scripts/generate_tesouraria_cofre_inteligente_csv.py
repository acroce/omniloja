from __future__ import annotations

import csv
import json
import sys
from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PYTHON_PACKAGES = ROOT / ".python_packages"
if str(PYTHON_PACKAGES) not in sys.path:
    sys.path.insert(0, str(PYTHON_PACKAGES))

import pymysql


OUTPUT_ROOT = ROOT / "outputs" / "tesouraria_cofre_inteligente"

CONTA_CONTABIL_COFRE_INTELIGENTE = "113102"
CONTA_CONTABIL_CAIXA_GERAL = "111015"


@dataclass(frozen=True)
class TransferenciaCofre:
    filial: int
    nome_filial: str
    transacao_id: int
    situacao_id: int
    situacao: str
    data_lancamento: date
    data_prevista: date | None
    data_realizada: date | None
    valor: Decimal
    memo: str | None
    conta_caixa_geral_codigo: str | None
    conta_cofre_inteligente_codigo: str | None
    qtd_linhas_fin08: int
    contas_financeiras: str | None
    filiais_encontradas: str | None


def load_env(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def parse_args() -> ArgumentParser:
    parser = ArgumentParser(
        description="Gera CSV de tesouraria para transferencias Caixa Geral -> Cofre Inteligente."
    )
    parser.add_argument("--start-date", required=True, help="Data inicial em YYYY-MM-DD.")
    parser.add_argument("--end-date", required=True, help="Data final em YYYY-MM-DD.")
    parser.add_argument(
        "--loja",
        type=int,
        help="Numero da loja/filial. Se omitido, exporta todas as lojas.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Caminho do CSV de saida. Se omitido, gera em outputs/tesouraria_cofre_inteligente.",
    )
    parser.add_argument(
        "--include-canceladas",
        action="store_true",
        help="Inclui transacoes canceladas. Por padrao, canceladas ficam fora.",
    )
    parser.add_argument(
        "--somente-liquidadas",
        action="store_true",
        help="Exporta somente transacoes liquidadas.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Mostra resumo e primeiras transacoes sem gerar arquivo.",
    )
    parser.add_argument(
        "--limit-preview",
        type=int,
        default=10,
        help="Quantidade de transacoes exibidas no preview.",
    )
    return parser


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def format_amount(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{quantized:.2f}".replace(".", ",")


def format_date(value: date) -> str:
    return value.strftime("%d%m%Y")


def default_output_path(start_date: date, end_date: date, loja: int | None) -> Path:
    loja_part = f"LOJA_{loja}" if loja is not None else "TODAS_LOJAS"
    file_name = (
        f"TESOURARIA_COFRE_INTELIGENTE_{loja_part}_"
        f"{start_date:%Y%m%d}_{end_date:%Y%m%d}.csv"
    )
    return OUTPUT_ROOT / file_name


def connect(env: dict[str, str]) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=env["MYSQL_HOST"],
        port=int(env.get("MYSQL_PORT", "3306")),
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        database=env.get("MYSQL_DATABASE", "pleno"),
        charset="latin1",
        connect_timeout=15,
        read_timeout=3600,
        write_timeout=3600,
    )


def fetch_transferencias(
    conn: pymysql.connections.Connection,
    start_date: date,
    end_date: date,
    loja: int | None,
    include_canceladas: bool,
    somente_liquidadas: bool,
) -> list[TransferenciaCofre]:
    sql = """
        WITH lancamentos AS (
            SELECT
                l.fin07_transacao_id,
                COUNT(*) AS qtd_linhas_fin08,
                SUM(CASE WHEN conta.fin03_nome = _latin1'CAIXA GERAL' THEN l.fin08_valor ELSE 0 END) AS valor_caixa_geral,
                SUM(CASE WHEN conta.fin03_nome = _latin1'COFRE INTELIGENTE' THEN l.fin08_valor ELSE 0 END) AS valor_cofre_inteligente,
                MAX(CASE WHEN conta.fin03_nome = _latin1'CAIXA GERAL' THEN conta.fin03_codigo END) AS conta_caixa_geral_codigo,
                MAX(CASE WHEN conta.fin03_nome = _latin1'CAIXA GERAL' THEN conta.fin03_nome END) AS conta_caixa_geral_nome,
                MAX(CASE WHEN conta.fin03_nome = _latin1'COFRE INTELIGENTE' THEN conta.fin03_codigo END) AS conta_cofre_inteligente_codigo,
                MAX(CASE WHEN conta.fin03_nome = _latin1'COFRE INTELIGENTE' THEN conta.fin03_nome END) AS conta_cofre_inteligente_nome,
                MAX(CASE WHEN conta.fin03_nome = _latin1'COFRE INTELIGENTE' THEN f.cfg06_numero END) AS filial,
                MAX(CASE WHEN conta.fin03_nome = _latin1'COFRE INTELIGENTE' THEN f.cfg06_nome END) AS nome_filial,
                GROUP_CONCAT(DISTINCT conta.fin03_nome ORDER BY conta.fin03_nome SEPARATOR ' | ') AS contas_financeiras,
                GROUP_CONCAT(DISTINCT f.cfg06_numero ORDER BY f.cfg06_numero SEPARATOR ',') AS filiais_encontradas
            FROM fin08_transacao_lancamento l
            INNER JOIN fin03_conta conta
                ON conta.fin03_id = l.fin03_conta_id
            LEFT JOIN cfg06_filial f
                ON f.cfg06_id = conta.cfg06_filial_id
            GROUP BY
                l.fin07_transacao_id
        )
        SELECT
            l.filial,
            l.nome_filial,
            t.fin07_id AS transacao_id,
            st.dom22_id AS situacao_id,
            st.dom22_descricao AS situacao,
            COALESCE(t.fin07_data_vencto_realizada, t.fin07_data_vencto_programada) AS data_lancamento,
            t.fin07_data_vencto_programada AS data_prevista,
            t.fin07_data_vencto_realizada AS data_realizada,
            t.fin07_valor AS valor,
            t.fin07_memo AS memo,
            l.conta_caixa_geral_codigo,
            l.conta_cofre_inteligente_codigo,
            l.qtd_linhas_fin08,
            l.contas_financeiras,
            l.filiais_encontradas
        FROM fin07_transacao t
        INNER JOIN fin11_categoria c
            ON c.fin11_id = t.fin11_categoria_id
        INNER JOIN dom22_situacao_trans_financeira st
            ON st.dom22_id = t.dom22_situacao_trans_financeira_id
        INNER JOIN lancamentos l
            ON l.fin07_transacao_id = t.fin07_id
        WHERE TRIM(t.fin07_descricao) = _latin1'DEPOSITO COFRE INTELIGENTE'
          AND c.fin11_codigo = _latin1'03.01'
          AND l.conta_caixa_geral_nome = _latin1'CAIXA GERAL'
          AND l.conta_cofre_inteligente_nome = _latin1'COFRE INTELIGENTE'
          AND l.valor_caixa_geral = l.valor_cofre_inteligente
          AND t.fin07_data_vencto_programada BETWEEN %s AND %s
          AND (%s IS NULL OR l.filial = %s)
          AND (%s = 1 OR st.dom22_id <> 1)
          AND (%s = 0 OR st.dom22_id = 2)
        ORDER BY
            l.filial,
            COALESCE(t.fin07_data_vencto_realizada, t.fin07_data_vencto_programada),
            t.fin07_id
    """
    params = (
        start_date.isoformat(),
        end_date.isoformat(),
        loja,
        loja,
        1 if include_canceladas else 0,
        1 if somente_liquidadas else 0,
    )

    with conn.cursor() as cur:
        cur.execute("SET NAMES latin1")
        cur.execute("SET collation_connection = 'latin1_swedish_ci'")
        cur.execute(sql, params)
        return [
            TransferenciaCofre(
                filial=int(row[0]),
                nome_filial=row[1] or "",
                transacao_id=int(row[2]),
                situacao_id=int(row[3]),
                situacao=row[4] or "",
                data_lancamento=row[5],
                data_prevista=row[6],
                data_realizada=row[7],
                valor=Decimal(row[8]),
                memo=row[9],
                conta_caixa_geral_codigo=row[10],
                conta_cofre_inteligente_codigo=row[11],
                qtd_linhas_fin08=int(row[12]),
                contas_financeiras=row[13],
                filiais_encontradas=row[14],
            )
            for row in cur.fetchall()
        ]


def make_row(
    item_no: int,
    movement_date: date,
    account: str,
    debit: Decimal | None,
    credit: Decimal | None,
    store_code: str,
    text: str,
) -> list[str]:
    return [
        str(item_no),
        "0136",
        "SC",
        format_date(movement_date),
        format_date(movement_date),
        "BRL",
        "",
        "",
        "",
        "S",
        account,
        "",
        format_amount(debit) if debit is not None else " ",
        format_amount(credit) if credit is not None else " ",
        "",
        "",
        "",
        "",
        "",
        "",
        store_code,
        "",
        store_code,
        text,
    ]


def build_csv_rows(records: list[TransferenciaCofre]) -> list[list[str]]:
    rows: list[list[str]] = []
    for record in records:
        store_code = f"{record.filial:05d}"
        rows.append(
            make_row(
                item_no=1,
                movement_date=record.data_lancamento,
                account=CONTA_CONTABIL_COFRE_INTELIGENTE,
                debit=record.valor,
                credit=None,
                store_code=store_code,
                text=f"{record.transacao_id}-COFRE INTELIGENTE",
            )
        )
        rows.append(
            make_row(
                item_no=2,
                movement_date=record.data_lancamento,
                account=CONTA_CONTABIL_CAIXA_GERAL,
                debit=None,
                credit=record.valor,
                store_code=store_code,
                text=f"{record.transacao_id}-CAIXA GERAL",
            )
        )
    return rows


def write_csv(output_path: Path, rows: list[list[str]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter=",", quotechar='"', quoting=csv.QUOTE_ALL)
        writer.writerows(rows)


def write_manifest(
    output_path: Path,
    start_date: date,
    end_date: date,
    loja: int | None,
    records: list[TransferenciaCofre],
    include_canceladas: bool,
    somente_liquidadas: bool,
) -> Path:
    manifest_path = output_path.with_suffix(".manifest.json")
    total = sum((record.valor for record in records), Decimal("0.00"))
    payload: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "loja": loja,
        "include_canceladas": include_canceladas,
        "somente_liquidadas": somente_liquidadas,
        "transacoes": len(records),
        "linhas_csv": len(records) * 2,
        "valor_total": str(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "output": str(output_path),
    }
    manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest_path


def print_preview(records: list[TransferenciaCofre], limit: int) -> None:
    total = sum((record.valor for record in records), Decimal("0.00"))
    print(f"transacoes={len(records)}")
    print(f"linhas_csv={len(records) * 2}")
    print(f"valor_total={format_amount(total)}")
    for record in records[:limit]:
        print(
            "|".join(
                [
                    str(record.filial),
                    record.nome_filial,
                    str(record.transacao_id),
                    record.situacao,
                    record.data_lancamento.isoformat(),
                    format_amount(record.valor),
                ]
            )
        )


def main() -> int:
    parser = parse_args()
    args = parser.parse_args()
    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)
    if end_date < start_date:
        raise SystemExit("--end-date deve ser maior ou igual a --start-date")

    env = load_env(ROOT / ".env")
    required = ["MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD"]
    missing = [key for key in required if not env.get(key)]
    if missing:
        raise SystemExit(f"Chaves obrigatorias ausentes no .env: {', '.join(missing)}")

    conn = connect(env)
    try:
        records = fetch_transferencias(
            conn=conn,
            start_date=start_date,
            end_date=end_date,
            loja=args.loja,
            include_canceladas=args.include_canceladas,
            somente_liquidadas=args.somente_liquidadas,
        )
    finally:
        conn.close()

    if args.preview:
        print_preview(records, args.limit_preview)
        return 0

    output_path = args.output or default_output_path(start_date, end_date, args.loja)
    rows = build_csv_rows(records)
    write_csv(output_path, rows)
    manifest_path = write_manifest(
        output_path=output_path,
        start_date=start_date,
        end_date=end_date,
        loja=args.loja,
        records=records,
        include_canceladas=args.include_canceladas,
        somente_liquidadas=args.somente_liquidadas,
    )

    print(output_path)
    print(manifest_path)
    print(f"transacoes={len(records)} linhas_csv={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
