#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from itertools import zip_longest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = ROOT / "outputs" / "estoque_mais_notas_sem_checkin" / "input"
OUTPUT_DIR = ROOT / "outputs" / "estoque_mais_notas_sem_checkin"
DEFAULT_ORIGIN_STORE = 704


def first_day_current_month() -> str:
    today = date.today()
    return today.replace(day=1).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Soma o arquivo de estoque com as quantidades das notas do CD sem check-in, "
            "produto a produto e loja a loja."
        )
    )
    parser.add_argument(
        "--estoque",
        type=Path,
        help=f"CSV de estoque. Se omitido, usa o CSV mais recente em {INPUT_DIR}",
    )
    parser.add_argument(
        "--start-date",
        default=first_day_current_month(),
        help="Data inicial das notas sem check-in. Padrao: primeiro dia do mes atual.",
    )
    parser.add_argument(
        "--end-date",
        help="Data final inclusiva das notas sem check-in. Se omitida, nao aplica limite final.",
    )
    parser.add_argument(
        "--origin-store",
        type=int,
        default=DEFAULT_ORIGIN_STORE,
        help=f"Loja/CD origem das notas. Padrao: {DEFAULT_ORIGIN_STORE}.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=OUTPUT_DIR,
        help=f"Diretorio de saida. Padrao: {OUTPUT_DIR}",
    )
    parser.add_argument(
        "--preserve-layout",
        action="store_true",
        help=(
            "Mantem exatamente as colunas do CSV de estoque e altera somente "
            "a quantidade de estoque com as notas sem check-in."
        ),
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Gera uma conferencia por loja e artigo apos criar o arquivo de estoque.",
    )
    parser.add_argument(
        "--include-products-only-in-notes",
        action="store_true",
        help=(
            "Inclui no estoque os artigos presentes nas notas, mas ausentes no CSV original. "
            "Os campos que a nota nao informa permanecem vazios ou zerados."
        ),
    )
    parser.add_argument(
        "--note-numbers",
        help=(
            "Lista de numeros de notas separados por virgula. Quando informada, "
            "usa somente essas notas e nao filtra pelo status de check-in."
        ),
    )
    parser.add_argument(
        "--checked-in-date",
        help=(
            "Data YYYY-MM-DD para usar as notas com check-in preenchido e "
            "data de entrada/saida igual a esta data."
        ),
    )
    parser.add_argument(
        "--rejeitados-consolidado",
        type=Path,
        help=(
            "CSV consolidado de itens rejeitados por loja e artigo. Usa as colunas "
            "loja, codigo e qtd_xml_total como acrescimo adicional ao estoque."
        ),
    )
    return parser.parse_args()


def load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def load_env() -> dict[str, str]:
    env = load_env_file(ROOT / ".env")
    env.update(os.environ)
    return env


def normalize_number(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def to_decimal(value: Any) -> Decimal:
    text = str(value or "").strip()
    if not text:
        return Decimal("0")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return Decimal(text)
    except Exception:
        return Decimal("0")


def normalize_key(value: Any) -> str:
    text = str(value or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def format_number(value: float) -> str:
    rounded = round(float(value), 3)
    if rounded == int(rounded):
        return str(int(rounded))
    return f"{rounded:.3f}".rstrip("0").rstrip(".")


def decimal_places(value: Any) -> int:
    """Return the source precision so the stock CSV keeps its decimal style."""
    text = str(value or "").strip()
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    if "." not in text:
        return 0
    return len(text.rsplit(".", 1)[1])


def format_stock_quantity(value: Decimal, original: Any, increment: Any) -> str:
    """Keep dot decimals and retain enough precision for stock plus note quantity."""
    places = decimal_places(original)
    if value == value.to_integral_value():
        if places == 0:
            return str(value.quantize(Decimal("1")))
        return f"{value.quantize(Decimal('1.' + ('0' * places)))}"
    if places < 3:
        places = 3
    return f"{value.quantize(Decimal('1.' + ('0' * places)))}"


def format_new_stock_quantity(value: Decimal) -> str:
    """Use the source decimal separator without fabricating trailing precision."""
    if value == value.to_integral_value():
        return str(value.quantize(Decimal("1")))
    return f"{value.quantize(Decimal('1.000'))}"


def choose_column(fieldnames: list[str], candidates: tuple[str, ...], label: str) -> str:
    normalized = {field.strip().lower(): field for field in fieldnames}
    for candidate in candidates:
        found = normalized.get(candidate.lower())
        if found:
            return found
    raise SystemExit(
        f"Coluna de {label} nao encontrada. Esperava uma destas: {', '.join(candidates)}"
    )


def sniff_dialect(path: Path) -> csv.Dialect:
    sample = path.read_text(encoding="utf-8-sig", errors="replace")[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,|\t")
    except csv.Error:
        return csv.excel


def latest_input_csv() -> Path:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(INPUT_DIR.glob("*.csv"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not files:
        raise SystemExit(
            f"Nenhum CSV encontrado. Coloque o arquivo de estoque em {INPUT_DIR}"
        )
    return files[0]


def load_stock(path: Path) -> tuple[list[dict[str, str]], list[str], str, str, str]:
    if not path.exists():
        raise SystemExit(f"Arquivo de estoque nao encontrado: {path}")

    dialect = sniff_dialect(path)
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp, dialect=dialect)
        if not reader.fieldnames:
            raise SystemExit(f"CSV sem cabecalho: {path}")
        fieldnames = list(reader.fieldnames)
        store_col = choose_column(
            fieldnames,
            ("nro_loja", "loja", "filial", "codigo_loja", "cod_loja"),
            "loja",
        )
        sku_col = choose_column(
            fieldnames,
            ("codigo_interno", "sku", "codigo_produto", "produto", "cod_produto", "artigo"),
            "produto",
        )
        qty_col = choose_column(
            fieldnames,
            ("qtd_estoque", "quantidade", "qtd", "estoque", "saldo", "qtd_atual"),
            "quantidade de estoque",
        )
        return list(reader), fieldnames, store_col, sku_col, qty_col


def load_rejected_items(path: Path | None) -> tuple[list[dict[str, str]], dict[tuple[str, str], Decimal]]:
    if path is None:
        return [], {}
    if not path.exists():
        raise SystemExit(f"Arquivo consolidado de rejeitados nao encontrado: {path}")
    dialect = sniff_dialect(path)
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp, dialect=dialect)
        if not reader.fieldnames:
            raise SystemExit(f"CSV de rejeitados sem cabecalho: {path}")
        fields = list(reader.fieldnames)
        store_col = choose_column(fields, ("loja", "nro_loja", "filial"), "loja dos rejeitados")
        sku_col = choose_column(fields, ("codigo", "codigo_interno", "sku"), "produto dos rejeitados")
        qty_col = choose_column(
            fields,
            ("qtd_recriar_estoque", "qtd_xml_total", "quantidade", "qtd"),
            "quantidade dos rejeitados",
        )
        rows = list(reader)
    quantities: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for row in rows:
        key = (normalize_key(row.get(store_col)), normalize_key(row.get(sku_col)))
        if not key[0] or not key[1]:
            continue
        quantities[key] += to_decimal(row.get(qty_col))
    return rows, dict(quantities)


def db_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def fetch_notes_without_checkin(
    start_date: str,
    end_date: str | None,
    origin_store: int,
    note_numbers: list[str] | None = None,
    checked_in_date: str | None = None,
) -> list[dict[str, Any]]:
    env = load_env()
    sys.path.insert(0, str(ROOT / ".python_packages"))
    import pymysql

    conn = pymysql.connect(
        host=env["MYSQL_HOST"],
        port=int(env.get("MYSQL_PORT", "3306")),
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        database=env["MYSQL_DATABASE"],
        charset="latin1",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        if note_numbers:
            return fetch_selected_notes(conn, note_numbers, origin_store)
        with conn.cursor() as cur:
            query = """
                SELECT
                    f_destino.cfg06_numero AS loja,
                    f_destino.cfg06_nome AS nome_loja,
                    m.mcd01_codint AS codigo_interno,
                    LEFT(COALESCE(m.mcd01_descricao_curta, m.mcd01_descricao), 120) AS descricao,
                    COUNT(DISTINCT nf.fis01_id) AS notas_sem_checkin,
                    COUNT(DISTINCT ni.fis02_id) AS itens_sem_checkin,
                    ROUND(SUM(COALESCE(ni.fis02_qtd, 0)), 3) AS qtd_sem_checkin,
                    ROUND(SUM(COALESCE(ni.fis02_qtd, 0) * COALESCE(NULLIF(ni.fis02_vlrunit_liquido, 0), ni.fis02_vlrunit, 0)), 2) AS valor_sem_checkin,
                    GROUP_CONCAT(DISTINCT nf.fis01_nronf ORDER BY nf.fis01_nronf SEPARATOR ',') AS notas
                FROM fis01_notafiscal nf
                JOIN fis02_notafiscal_item ni
                    ON ni.fis01_notafiscal_id = nf.fis01_id
                JOIN mcd03_mercadoria_filial mf
                    ON mf.mcd03_id = ni.mcd03_mercadoria_filial_id
                JOIN mcd01_mercadoria m
                    ON m.mcd01_id = mf.mcd01_mercadoria_id
                LEFT JOIN pes04_pessoa p_origem
                    ON p_origem.pes04_id = nf.pes04_pessoa_emit
                LEFT JOIN pes03_estabelecimento origem
                    ON origem.pes03_id = p_origem.pes03_estabelecimento_id
                LEFT JOIN cfg06_filial f_origem
                    ON f_origem.pes03_estabelecimento_id = origem.pes03_id
                LEFT JOIN pes04_pessoa p_destino
                    ON p_destino.pes04_id = nf.pes04_pessoa_dest
                LEFT JOIN pes03_estabelecimento destino
                    ON destino.pes03_id = p_destino.pes03_estabelecimento_id
                LEFT JOIN cfg06_filial f_destino
                    ON f_destino.pes03_estabelecimento_id = destino.pes03_id
                WHERE nf.fis01_entrada_saida = 'S'
                  AND COALESCE(nf.fis01_flgcancelada, 0) = 0
                  AND f_origem.cfg06_numero = %s
                  AND f_destino.cfg06_numero IS NOT NULL
            """
            params: list[Any] = [origin_store]
            if note_numbers:
                placeholders = ", ".join(["%s"] * len(note_numbers))
                query += f" AND nf.fis01_nronf IN ({placeholders}) "
                params.extend(note_numbers)
            elif checked_in_date:
                query += """
                  AND nf.adm05_usuario_checkin_id IS NOT NULL
                  AND nf.fis01_data_entrada_saida = %s
                """
                params.append(checked_in_date)
            else:
                query += " AND nf.adm05_usuario_checkin_id IS NULL "
            if not note_numbers and not checked_in_date and end_date:
                query += """
                  AND (
                      (nf.fis01_data_emissao >= %s AND nf.fis01_data_emissao <= %s)
                      OR (
                          nf.fis01_data_entrada_saida >= %s
                          AND nf.fis01_data_entrada_saida <= %s
                      )
                  )
                """
                params.extend([start_date, end_date, start_date, end_date])
            elif not note_numbers and not checked_in_date:
                query += """
                  AND (
                      nf.fis01_data_emissao >= %s
                      OR nf.fis01_data_entrada_saida >= %s
                  )
                """
                params.extend([start_date, start_date])
            query += """
                GROUP BY
                    f_destino.cfg06_numero,
                    f_destino.cfg06_nome,
                    m.mcd01_codint,
                    descricao
                ORDER BY f_destino.cfg06_numero, m.mcd01_codint
                """
            cur.execute(query, params)
            return [{key: db_value(value) for key, value in row.items()} for row in cur.fetchall()]
    finally:
        conn.close()


def fetch_selected_notes(
    conn: Any, note_numbers: list[str], origin_store: int
) -> list[dict[str, Any]]:
    """Fetch a short, explicit list without using the check-in status."""
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    query = """
        SELECT
            f_destino.cfg06_numero AS loja,
            f_destino.cfg06_nome AS nome_loja,
            m.mcd01_codint AS codigo_interno,
            LEFT(COALESCE(m.mcd01_descricao_curta, m.mcd01_descricao), 120) AS descricao,
            nf.fis01_nronf AS nota,
            ni.fis02_id AS item_id,
            COALESCE(ni.fis02_qtd, 0) AS quantidade,
            COALESCE(NULLIF(ni.fis02_vlrunit_liquido, 0), ni.fis02_vlrunit, 0) AS valor_unitario
        FROM fis01_notafiscal nf
        JOIN fis02_notafiscal_item ni
            ON ni.fis01_notafiscal_id = nf.fis01_id
        JOIN mcd03_mercadoria_filial mf
            ON mf.mcd03_id = ni.mcd03_mercadoria_filial_id
        JOIN mcd01_mercadoria m
            ON m.mcd01_id = mf.mcd01_mercadoria_id
        LEFT JOIN pes04_pessoa p_origem
            ON p_origem.pes04_id = nf.pes04_pessoa_emit
        LEFT JOIN pes03_estabelecimento origem
            ON origem.pes03_id = p_origem.pes03_estabelecimento_id
        LEFT JOIN cfg06_filial f_origem
            ON f_origem.pes03_estabelecimento_id = origem.pes03_id
        LEFT JOIN pes04_pessoa p_destino
            ON p_destino.pes04_id = nf.pes04_pessoa_dest
        LEFT JOIN pes03_estabelecimento destino
            ON destino.pes03_id = p_destino.pes03_estabelecimento_id
        LEFT JOIN cfg06_filial f_destino
            ON f_destino.pes03_estabelecimento_id = destino.pes03_id
        WHERE nf.fis01_nronf = %s
          AND nf.fis01_entrada_saida = 'S'
          AND COALESCE(nf.fis01_flgcancelada, 0) = 0
          AND f_origem.cfg06_numero = %s
          AND f_destino.cfg06_numero IS NOT NULL
    """
    with conn.cursor() as cur:
        for note_number in note_numbers:
            cur.execute(query, (note_number, origin_store))
            for row in cur.fetchall():
                key = (normalize_key(row["loja"]), normalize_key(row["codigo_interno"]))
                entry = grouped.setdefault(
                    key,
                    {
                        "loja": row["loja"],
                        "nome_loja": row["nome_loja"],
                        "codigo_interno": row["codigo_interno"],
                        "descricao": row["descricao"],
                        "notas": set(),
                        "item_ids": set(),
                        "qtd_sem_checkin": Decimal("0"),
                        "valor_sem_checkin": Decimal("0"),
                    },
                )
                quantity = to_decimal(row["quantidade"])
                unit_value = to_decimal(row["valor_unitario"])
                entry["notas"].add(str(row["nota"]))
                entry["item_ids"].add(str(row["item_id"]))
                entry["qtd_sem_checkin"] += quantity
                entry["valor_sem_checkin"] += quantity * unit_value

    rows: list[dict[str, Any]] = []
    for row in grouped.values():
        rows.append(
            {
                "loja": row["loja"],
                "nome_loja": row["nome_loja"],
                "codigo_interno": row["codigo_interno"],
                "descricao": row["descricao"],
                "notas_sem_checkin": len(row["notas"]),
                "itens_sem_checkin": len(row["item_ids"]),
                "qtd_sem_checkin": float(row["qtd_sem_checkin"]),
                "valor_sem_checkin": float(row["valor_sem_checkin"]),
                "notas": ",".join(sorted(row["notas"])),
            }
        )
    return sorted(rows, key=lambda row: (normalize_key(row["loja"]), normalize_key(row["codigo_interno"])))


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
    delimiter: str = ";",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


def verify_adjusted_stock(
    original_path: Path,
    adjusted_path: Path,
    store_col: str,
    sku_col: str,
    qty_col: str,
    increments_by_key: dict[tuple[str, str], Decimal],
    expected_extra_by_key: dict[tuple[str, str], Decimal],
) -> tuple[int, list[dict[str, str]]]:
    dialect = sniff_dialect(original_path)
    divergences: list[dict[str, str]] = []
    checked_rows = 0
    with original_path.open("r", encoding="utf-8-sig", newline="") as original_fp, adjusted_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as adjusted_fp:
        original_reader = csv.DictReader(original_fp, dialect=dialect)
        adjusted_reader = csv.DictReader(adjusted_fp, dialect=dialect)
        if original_reader.fieldnames != adjusted_reader.fieldnames:
            raise SystemExit("Conferencia falhou: o layout do arquivo gerado foi alterado.")

        for original, adjusted in zip_longest(original_reader, adjusted_reader):
            checked_rows += 1
            if original is None and adjusted is not None:
                key = (normalize_key(adjusted.get(store_col)), normalize_key(adjusted.get(sku_col)))
                expected = expected_extra_by_key.pop(key, None)
                actual = to_decimal(adjusted.get(qty_col))
                if expected is None or actual != expected:
                    divergences.append(
                        {
                            "loja": key[0],
                            "codigo_interno": key[1],
                            "qtd_estoque_original": "0",
                            "qtd_notas_sem_checkin": str(expected or Decimal("0")),
                            "qtd_esperada": str(expected or Decimal("0")),
                            "qtd_gerada": str(actual),
                            "status": "DIVERGENTE_ITEM_NOVO",
                        }
                    )
                continue
            if original is not None and adjusted is None:
                divergences.append(
                    {
                        "loja": "",
                        "codigo_interno": "",
                        "qtd_estoque_original": "",
                        "qtd_notas_sem_checkin": "",
                        "qtd_esperada": "",
                        "qtd_gerada": "",
                        "status": "DIVERGENTE_QUANTIDADE_DE_LINHAS",
                    }
                )
                continue

            key = (normalize_key(original.get(store_col)), normalize_key(original.get(sku_col)))
            original_qty = to_decimal(original.get(qty_col))
            increment = increments_by_key.get(key, Decimal("0"))
            expected = original_qty + increment
            actual = to_decimal(adjusted.get(qty_col))
            other_columns_match = all(
                original.get(field) == adjusted.get(field)
                for field in original_reader.fieldnames
                if field != qty_col
            )
            if actual != expected or not other_columns_match:
                divergences.append(
                    {
                        "loja": key[0],
                        "codigo_interno": key[1],
                        "qtd_estoque_original": str(original_qty),
                            "qtd_notas_sem_checkin": str(increment),
                        "qtd_esperada": str(expected),
                        "qtd_gerada": str(actual),
                        "status": "DIVERGENTE",
                    }
                )
    for key, expected in expected_extra_by_key.items():
        divergences.append(
            {
                "loja": key[0],
                "codigo_interno": key[1],
                "qtd_estoque_original": "0",
                "qtd_notas_sem_checkin": str(expected),
                "qtd_esperada": str(expected),
                "qtd_gerada": "",
                "status": "DIVERGENTE_ITEM_NOVO_AUSENTE",
            }
        )
    return checked_rows, divergences


def main() -> None:
    args = parse_args()
    stock_path = args.estoque or latest_input_csv()
    stock_rows, stock_fields, store_col, sku_col, qty_col = load_stock(stock_path)
    stock_dialect = sniff_dialect(stock_path)
    note_numbers = (
        [number.strip() for number in args.note_numbers.split(",") if number.strip()]
        if args.note_numbers
        else None
    )
    note_rows = fetch_notes_without_checkin(
        args.start_date,
        args.end_date,
        args.origin_store,
        note_numbers,
        args.checked_in_date,
    )
    rejected_rows, rejected_by_key = load_rejected_items(args.rejeitados_consolidado)

    notes_by_key: dict[tuple[str, str], dict[str, Any]] = {
        (normalize_key(row["loja"]), normalize_key(row["codigo_interno"])): row
        for row in note_rows
    }
    increments_by_key: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for key, note in notes_by_key.items():
        increments_by_key[key] += to_decimal(note.get("qtd_sem_checkin"))
    for key, quantity in rejected_by_key.items():
        increments_by_key[key] += quantity

    seen: set[tuple[str, str]] = set()
    row_template_by_store: dict[str, dict[str, str]] = {}
    output_rows: list[dict[str, Any]] = []
    for row in stock_rows:
        key = (normalize_key(row.get(store_col)), normalize_key(row.get(sku_col)))
        seen.add(key)
        row_template_by_store.setdefault(key[0], row)
        note = notes_by_key.get(key, {})
        increment = increments_by_key.get(key, Decimal("0"))
        qtd_estoque = normalize_number(row.get(qty_col))
        qtd_sem_checkin = normalize_number(note.get("qtd_sem_checkin"))
        if args.preserve_layout:
            out = dict(row)
            out[qty_col] = format_stock_quantity(
                to_decimal(row.get(qty_col)) + increment,
                row.get(qty_col),
                increment,
            )
            output_rows.append(out)
            continue
        out = dict(row)
        out["qtd_notas_sem_checkin"] = format_number(qtd_sem_checkin)
        out["qtd_estoque_com_sem_checkin"] = format_number(qtd_estoque + float(increment))
        out["notas_sem_checkin"] = note.get("notas_sem_checkin", 0)
        out["valor_sem_checkin"] = note.get("valor_sem_checkin", 0)
        out["notas"] = note.get("notas", "")
        output_rows.append(out)

    missing_stock_rows = []
    for key, increment in increments_by_key.items():
        if key in seen:
            continue
        note = notes_by_key.get(key, {})
        missing_stock_rows.append(
            {
                store_col: note.get("loja", key[0]),
                sku_col: note.get("codigo_interno", key[1]),
                qty_col: "0",
                "descricao": note.get("descricao", ""),
                "qtd_notas_sem_checkin": format_number(float(increment)),
                "qtd_estoque_com_sem_checkin": format_number(float(increment)),
                "notas_sem_checkin": note.get("notas_sem_checkin", 0),
                "valor_sem_checkin": note.get("valor_sem_checkin", 0),
                "notas": note.get("notas", ""),
            }
        )
    if args.preserve_layout and args.include_products_only_in_notes:
        for row in missing_stock_rows:
            store = normalize_key(row[store_col])
            template = row_template_by_store.get(store, {})
            out = {field: template.get(field, "") for field in stock_fields}
            out[store_col] = row[store_col]
            out[sku_col] = row[sku_col]
            out[qty_col] = format_new_stock_quantity(to_decimal(row["qtd_notas_sem_checkin"]))
            for field in (
                "valor_estoque",
                "valor_imposto_estoque",
                "unidade_medida",
                "quilos_estoque",
                "volumes_estoque",
                "qtd_pedido_pendente",
            ):
                if field in out:
                    out[field] = "0.00" if field == "valor_estoque" else "0" if field != "unidade_medida" else ""
            output_rows.append(out)
    elif not args.preserve_layout:
        output_rows.extend(missing_stock_rows)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.out_dir
    adjusted_path = (
        out_dir / stock_path.name
        if args.preserve_layout
        else out_dir / f"estoque_com_notas_sem_checkin_{stamp}.csv"
    )
    detail_label = (
        "notas_lista_produto"
        if note_numbers
        else "notas_checkin_produto"
        if args.checked_in_date
        else "notas_sem_checkin_produto"
    )
    detail_path = out_dir / f"{detail_label}_{stamp}.csv"
    rejected_detail_path = out_dir / f"rejeitados_consolidado_{stamp}.csv" if rejected_rows else None
    manifest_path = out_dir / f"manifest_{stamp}.json"

    extra_fields = [
        "qtd_notas_sem_checkin",
        "qtd_estoque_com_sem_checkin",
        "notas_sem_checkin",
        "valor_sem_checkin",
        "notas",
    ]
    adjusted_fields = (
        stock_fields
        if args.preserve_layout
        else stock_fields + [field for field in extra_fields if field not in stock_fields]
    )
    if not args.preserve_layout and missing_stock_rows and "descricao" not in adjusted_fields:
        adjusted_fields.insert(2, "descricao")

    write_csv(adjusted_path, output_rows, adjusted_fields, delimiter=stock_dialect.delimiter)
    detail_fields = [
        "loja",
        "nome_loja",
        "codigo_interno",
        "descricao",
        "notas_sem_checkin",
        "itens_sem_checkin",
        "qtd_sem_checkin",
        "valor_sem_checkin",
        "notas",
    ]
    write_csv(detail_path, note_rows, detail_fields)
    if rejected_detail_path:
        write_csv(rejected_detail_path, rejected_rows, list(rejected_rows[0].keys()), delimiter=",")

    verification_path = None
    checked_rows = 0
    verification_rows: list[dict[str, str]] = []
    if args.verify:
        expected_extra_by_key = (
            {
                (normalize_key(row[store_col]), normalize_key(row[sku_col])): to_decimal(
                    row["qtd_notas_sem_checkin"]
                )
                for row in missing_stock_rows
            }
            if args.preserve_layout and args.include_products_only_in_notes
            else {}
        )
        checked_rows, verification_rows = verify_adjusted_stock(
            stock_path,
            adjusted_path,
            store_col,
            sku_col,
            qty_col,
            dict(increments_by_key),
            expected_extra_by_key,
        )
        verification_path = out_dir / f"conferencia_divergencias_{stamp}.csv"
        write_csv(
            verification_path,
            verification_rows,
            [
                "loja",
                "codigo_interno",
                "qtd_estoque_original",
                "qtd_notas_sem_checkin",
                "qtd_esperada",
                "qtd_gerada",
                "status",
            ],
        )

    totals = defaultdict(float)
    for row in output_rows:
        totals["qtd_estoque"] += normalize_number(row.get(qty_col))
        totals["qtd_sem_checkin"] += normalize_number(row.get("qtd_notas_sem_checkin"))
        totals["qtd_ajustada"] += normalize_number(row.get("qtd_estoque_com_sem_checkin"))

    found_note_numbers = {
        number
        for row in note_rows
        for number in str(row.get("notas", "")).split(",")
        if number
    }
    missing_note_numbers = sorted(set(note_numbers or []) - found_note_numbers)
    manifest = {
        "generated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "stock_file": str(stock_path),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "origin_store": args.origin_store,
        "note_numbers": note_numbers,
        "note_numbers_not_found": missing_note_numbers,
        "checked_in_date": args.checked_in_date,
        "rejeitados_consolidado": str(args.rejeitados_consolidado) if args.rejeitados_consolidado else None,
        "stock_rows": len(stock_rows),
        "note_product_rows": len(note_rows),
        "rejected_product_rows": len(rejected_rows),
        "rejected_store_product_rows": len(rejected_by_key),
        "products_only_in_notes": len(missing_stock_rows),
        "totals": {key: round(value, 3) for key, value in totals.items()},
        "files": {
            "estoque_ajustado": str(adjusted_path),
            "detalhe_notas_sem_checkin": str(detail_path),
            "detalhe_rejeitados": str(rejected_detail_path) if rejected_detail_path else None,
            "conferencia": str(verification_path) if verification_path else None,
        },
        "verification": {
            "checked_rows": checked_rows,
            "divergent_rows": sum(
                row["status"] == "DIVERGENTE" for row in verification_rows
            ),
        }
        if args.verify
        else None,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"entrada: {stock_path}")
    print(f"estoque_ajustado: {adjusted_path}")
    print(f"detalhe_notas: {detail_path}")
    print(f"manifest: {manifest_path}")
    print(f"linhas_estoque={len(stock_rows)}")
    print(f"linhas_notas_produto={len(note_rows)}")
    print(f"linhas_rejeitados_produto={len(rejected_rows)}")
    print(f"produtos_so_em_notas={len(missing_stock_rows)}")
    print(f"qtd_estoque={round(totals['qtd_estoque'], 3)}")
    print(f"qtd_sem_checkin={round(totals['qtd_sem_checkin'], 3)}")
    print(f"qtd_ajustada={round(totals['qtd_ajustada'], 3)}")
    if args.verify:
        divergences = sum(row["status"] == "DIVERGENTE" for row in verification_rows)
        print(f"conferencia: {verification_path}")
        print(f"conferencia_linhas={checked_rows}")
        print(f"conferencia_divergencias={divergences}")


if __name__ == "__main__":
    main()
