from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import sys

sys.path.insert(
    0,
    "/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/.python_packages",
)

import pymysql


OUTPUT_PATH = Path(
    "/Users/alexandrematheuscrose/Documents/Codex/2026-05-19/tabelas-pleno-vamos-criar-uma-conex/outputs/TESOURARIA_1155_202604.csv"
)


@dataclass(frozen=True)
class Rule:
    doc_type: str
    debit_account: str
    credit_account: str
    text_mode: str


RULES = {
    "03.01": Rule("SC", "113102", "111015", "brinks"),
    "01.01.01": Rule("SC", "111015", "111011", "memo"),
    "01.01.08": Rule("SC", "111011", "314211", "memo"),
    "01.03": Rule("SC", "111015", "314211", "memo"),
    "02.03": Rule("SC", "314211", "111015", "memo"),
    "01.02": Rule("TR", "111010", "111010", "brinks"),
    "02.02.02": Rule("TR", "111010", "111010", "brinks"),
}


def format_amount(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{quantized:.2f}".replace(".", ",")


def format_date(value: date) -> str:
    return value.strftime("%d%m%Y")


def build_text(fin07_id: int, memo: str | None, rule: Rule) -> str:
    if rule.text_mode == "brinks":
        return f"{fin07_id}-BRINKS"
    base = (memo or "").strip()
    return f"{fin07_id}-{base}"


def make_row(
    item_no: int,
    company: str,
    doc_type: str,
    movement_date: date,
    account: str,
    debit: Decimal | None,
    credit: Decimal | None,
    store_code: str,
    text: str,
) -> list[str]:
    return [
        str(item_no),
        company,
        doc_type,
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


def fetch_rows() -> list[tuple]:
    conn = pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "172.22.20.101"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "diabrasil"),
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ.get("MYSQL_DATABASE", "pleno"),
        connect_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    t.fin07_id,
                    t.fin07_data_vencto_realizada,
                    c.fin11_codigo,
                    t.fin07_valor,
                    t.fin07_memo,
                    f.cfg06_numero
                FROM fin07_transacao t
                INNER JOIN fin11_categoria c
                    ON c.fin11_id = t.fin11_categoria_id
                INNER JOIN cfg06_filial f
                    ON f.cfg06_id = t.cfg06_filial_referencia_id
                WHERE t.cfg06_filial_referencia_id = 5
                  AND t.dom22_situacao_trans_financeira_id = 2
                  AND t.fin07_data_vencto_realizada BETWEEN '2026-04-01' AND '2026-04-30'
                  AND c.fin11_codigo IN ('03.01', '01.01.01', '01.01.08', '01.03', '02.03', '01.02', '02.02.02')
                ORDER BY
                    t.fin07_data_vencto_realizada,
                    t.fin07_id
                """
            )
            return list(cur.fetchall())
    finally:
        conn.close()


def generate() -> Path:
    records = fetch_rows()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=",", quotechar='"', quoting=csv.QUOTE_ALL)
        for fin07_id, movement_date, fin11_codigo, amount, memo, store_number in records:
            rule = RULES.get(fin11_codigo)
            if rule is None:
                continue

            store_code = f"{int(store_number):05d}"
            text = build_text(fin07_id, memo, rule)
            amount = Decimal(amount)

            writer.writerow(
                make_row(
                    item_no=1,
                    company="0136",
                    doc_type=rule.doc_type,
                    movement_date=movement_date,
                    account=rule.debit_account,
                    debit=amount,
                    credit=None,
                    store_code=store_code,
                    text=text,
                )
            )
            writer.writerow(
                make_row(
                    item_no=2,
                    company="0136",
                    doc_type=rule.doc_type,
                    movement_date=movement_date,
                    account=rule.credit_account,
                    debit=None,
                    credit=amount,
                    store_code=store_code,
                    text=text,
                )
            )

    return OUTPUT_PATH


if __name__ == "__main__":
    output = generate()
    print(output)
