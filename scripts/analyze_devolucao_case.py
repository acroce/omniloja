#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sqlite3
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pymysql


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Monta um resumo de devolucao CD cruzando Pleno, origem da NF, exportacao e AS400."
    )
    parser.add_argument("--loja", type=int, required=True, help="Numero da loja.")
    parser.add_argument(
        "--artigos",
        required=True,
        help="Lista de artigos separados por virgula. Ex.: 2358,73557,73551,60838",
    )
    parser.add_argument("--start-date", required=True, help="Data inicial YYYY-MM-DD.")
    parser.add_argument("--end-date", required=True, help="Data final YYYY-MM-DD.")
    parser.add_argument(
        "--db",
        default="outputs/devolucao_auditoria.sqlite",
        help="Base SQLite local com arquivos/exportacoes/AS400.",
    )
    parser.add_argument(
        "--env",
        default=".env",
        help="Arquivo .env com credenciais do Pleno.",
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "csv"],
        default="markdown",
        help="Formato de saida.",
    )
    return parser.parse_args()


def read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip("'\"")
    return env


def connect_mysql(env: dict[str, str]):
    return pymysql.connect(
        host=env.get("DB_HOST", env.get("MYSQL_HOST", "127.0.0.1")),
        port=int(env.get("DB_PORT", env.get("MYSQL_PORT", "3306"))),
        user=env.get("DB_USERNAME", env.get("DB_USER", env.get("MYSQL_USER", "root"))),
        password=env.get("DB_PASSWORD", env.get("MYSQL_PASSWORD", "")),
        database=env.get("DB_DATABASE", env.get("MYSQL_DATABASE", "pleno")),
        charset="latin1",
        cursorclass=pymysql.cursors.DictCursor,
    )


def parse_artigos(raw: str) -> list[int]:
    artigos = [int(item.strip()) for item in raw.split(",") if item.strip()]
    if not artigos:
        raise SystemExit("Informe ao menos um artigo.")
    return artigos


def placeholders(values: list[Any] | tuple[Any, ...]) -> str:
    return ",".join(["%s"] * len(values))


def to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        if value == value.to_integral():
            return str(value.to_integral())
        return format(value.normalize(), "f").rstrip("0").rstrip(".")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def parse_causa(motivo: str | None) -> str:
    if not motivo:
        return ""
    match = re.search(r"CAUSA\s+(\d+)", motivo)
    return match.group(1) if match else ""


def derive_original_note(nro_nf_gerado: int) -> int:
    text = str(nro_nf_gerado)
    if len(text) > 4:
        prefix = int(text[:2])
        if 90 <= prefix <= 99:
            return int(text[2:])
    return nro_nf_gerado


def key(loja: int, data_nf: Any, nro_nf: int, artigo: int) -> tuple[int, str, int, int]:
    return (int(loja), to_text(data_nf), int(nro_nf), int(artigo))


def fetch_pleno_view(
    conn,
    loja: int,
    artigos: list[int],
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
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
            FROM view_dia_devolucao_cd
            WHERE loja = %s
              AND codigo_produto IN ({placeholders(artigos)})
              AND data_devolucao BETWEEN %s AND %s
            ORDER BY data_devolucao, nro_nf, codigo_produto
            """,
            [loja, *artigos, start_date, end_date],
        )
        return list(cur.fetchall())


def fetch_fiscal_rows(
    conn,
    loja: int,
    artigos: list[int],
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                nf.fis01_id,
                nf.fis01_nronf AS nro_nf,
                nf.fis01_serienf AS serie,
                nf.fis01_entrada_saida,
                nf.fis01_data_emissao AS data_nf,
                nf.fis01_data_entrada_saida,
                nf.fis01_flgcancelada,
                nf.fis01_nfe_cstat,
                nf.fis01_nfe_xmotivo,
                nf.fis01_inform_adic,
                nf.fis01_nronf_origem,
                nf.fis01_serienf_origem,
                op.dom14_descricao AS operacao,
                it.fis02_id,
                it.fis02_item,
                it.fis02_qtd,
                it.fis02_vlrunit,
                it.fis02_vlrtot_bruto,
                it.fis02_flgtroca,
                it.fis02_origem_nro_nf,
                it.fis02_origem_serie_nf,
                it.fis02_origem_notafiscal_item_id,
                it.fis02_xped,
                cf.fis04_codigo AS cfop,
                m.mcd01_codint AS codigo_produto,
                COALESCE(m.mcd01_descricao_curta, m.mcd01_descricao) AS descricao,
                f.cfg06_numero AS loja,
                f.cfg06_nome AS nome_loja
            FROM fis01_notafiscal nf
            JOIN fis02_notafiscal_item it
                ON it.fis01_notafiscal_id = nf.fis01_id
            JOIN mcd03_mercadoria_filial mf
                ON mf.mcd03_id = it.mcd03_mercadoria_filial_id
            JOIN cfg06_filial f
                ON f.cfg06_id = mf.cfg06_filial_id
            JOIN mcd01_mercadoria m
                ON m.mcd01_id = mf.mcd01_mercadoria_id
            LEFT JOIN dom14_operacao_fiscal op
                ON op.dom14_id = nf.dom14_operacao_fiscal_id
            LEFT JOIN fis04_cfop cf
                ON cf.fis04_id = it.fis04_cfopemit_id
            WHERE f.cfg06_numero = %s
              AND m.mcd01_codint IN ({placeholders(artigos)})
              AND nf.fis01_data_emissao BETWEEN %s AND %s
              AND nf.fis01_flgcancelada = 0
              AND nf.fis01_nfe_cstat = '100'
            ORDER BY nf.fis01_data_emissao, nf.fis01_nronf, it.fis02_item
            """,
            [loja, *artigos, start_date, end_date],
        )
        return list(cur.fetchall())


def fetch_origins(conn, fiscal_item_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not fiscal_item_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                tr.fis02_notafiscal_item_id,
                tr.est09_id,
                tr.est09_entrada_saida,
                tr.est09_data,
                tr.est09_qtd,
                tr.adm22_motivo_troca_id,
                mt.adm22_descricao AS motivo_troca,
                tr.adm05_usuario_id,
                u.adm05_usuario AS usuario,
                u.adm05_nome_apresentacao AS usuario_nome
            FROM est09_troca_movimento tr
            LEFT JOIN adm22_motivo_troca mt
                ON mt.adm22_id = tr.adm22_motivo_troca_id
            LEFT JOIN adm05_usuario u
                ON u.adm05_id = tr.adm05_usuario_id
            WHERE tr.fis02_notafiscal_item_id IN ({placeholders(fiscal_item_ids)})
            ORDER BY tr.fis02_notafiscal_item_id, tr.est09_data, tr.est09_id
            """,
            fiscal_item_ids,
        )
        origins: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in cur.fetchall():
            origins[int(row["fis02_notafiscal_item_id"])].append(row)
        return origins


def fetch_sqlite_rows(
    sqlite_path: Path,
    loja: int,
    artigos: list[int],
    start_date: str,
    end_date: str,
) -> tuple[dict[tuple[int, str, int, int], list[sqlite3.Row]], dict[tuple[int, str, int, int], list[sqlite3.Row]]]:
    exports: dict[tuple[int, str, int, int], list[sqlite3.Row]] = defaultdict(list)
    as400: dict[tuple[int, str, int, int], list[sqlite3.Row]] = defaultdict(list)

    if not sqlite_path.exists():
        return exports, as400

    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        export_rows = conn.execute(
            f"""
            SELECT *
            FROM devolucao_export_status_detalhe
            WHERE nro_loja = ?
              AND codigo_interno IN ({",".join(["?"] * len(artigos))})
              AND data_nf BETWEEN ? AND ?
            ORDER BY data_nf, nro_nf_original, nro_nf_gerado, codigo_interno
            """,
            [loja, *artigos, start_date, end_date],
        ).fetchall()
        for row in export_rows:
            exports[
                key(
                    row["nro_loja"],
                    row["data_nf"],
                    row["nro_nf_original"],
                    row["codigo_interno"],
                )
            ].append(row)

        as400_rows = conn.execute(
            f"""
            SELECT *
            FROM as400_qlik_confirmado
            WHERE loja = ?
              AND cd_artigo IN ({",".join(["?"] * len(artigos))})
              AND data_nf BETWEEN ? AND ?
            ORDER BY data_nf, nr_devolucao, cd_artigo
            """,
            [loja, *artigos, start_date, end_date],
        ).fetchall()
        for row in as400_rows:
            original_note = derive_original_note(int(row["nr_devolucao"]))
            as400[key(row["loja"], row["data_nf"], original_note, row["cd_artigo"])].append(row)

    return exports, as400


def choose_origin(origins: list[dict[str, Any]]) -> dict[str, Any] | None:
    with_motive = [row for row in origins if row.get("adm22_motivo_troca_id")]
    if with_motive:
        return with_motive[0]
    return origins[0] if origins else None


def build_rows(
    pleno_rows: list[dict[str, Any]],
    fiscal_rows: list[dict[str, Any]],
    origins: dict[int, list[dict[str, Any]]],
    exports: dict[tuple[int, str, int, int], list[sqlite3.Row]],
    as400: dict[tuple[int, str, int, int], list[sqlite3.Row]],
) -> list[dict[str, str]]:
    fiscal_by_key: dict[tuple[int, str, int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in fiscal_rows:
        fiscal_by_key[key(row["loja"], row["data_nf"], row["nro_nf"], row["codigo_produto"])].append(row)

    all_keys = set(fiscal_by_key)
    for row in pleno_rows:
        all_keys.add(key(row["loja"], row["data_nf"], row["nro_nf"], row["codigo_produto"]))

    pleno_by_key = {
        key(row["loja"], row["data_nf"], row["nro_nf"], row["codigo_produto"]): row
        for row in pleno_rows
    }

    output: list[dict[str, str]] = []
    for item_key in sorted(all_keys, key=lambda value: (value[1], value[2], value[3])):
        loja, data_nf, nro_nf, artigo = item_key
        pleno = pleno_by_key.get(item_key, {})
        fiscal = fiscal_by_key.get(item_key, [{}])[0]
        origin = choose_origin(origins.get(int(fiscal.get("fis02_id") or 0), []))
        export_rows = exports.get(item_key, [])
        as400_rows = as400.get(item_key, [])

        origin_doc = ""
        if fiscal.get("fis01_nronf_origem"):
            origin_doc = f"NF {to_text(fiscal.get('fis01_nronf_origem'))}/{to_text(fiscal.get('fis01_serienf_origem'))}"
        elif fiscal.get("fis02_origem_nro_nf"):
            origin_doc = f"Item origem NF {to_text(fiscal.get('fis02_origem_nro_nf'))}/{to_text(fiscal.get('fis02_origem_serie_nf'))}"
        elif fiscal.get("fis02_xped"):
            origin_doc = f"Pedido {to_text(fiscal.get('fis02_xped'))}"
        elif origin:
            origin_doc = f"est09 {to_text(origin.get('est09_id'))}"

        export_note = ", ".join(str(row["nro_nf_gerado"]) for row in export_rows)
        export_status = ", ".join(sorted({row["status"] for row in export_rows})) if export_rows else ""
        export_qty = ", ".join(to_text(row["qtd_devolvida"]) for row in export_rows)
        export_date = ", ".join(to_text(row["exported_at"]) for row in export_rows)

        as400_note = ", ".join(str(row["nr_devolucao"]) for row in as400_rows)
        as400_qty = ", ".join(to_text(row["qtd_confirmada"]) for row in as400_rows)

        sent_status = "Reenviado" if export_rows else "Enviado"
        if as400_rows:
            sent_status = "Confirmado AS400"

        motivo = to_text(pleno.get("motivo")) or to_text(fiscal.get("fis01_inform_adic"))
        output.append(
            {
                "loja": str(loja),
                "data_nf": data_nf,
                "nf_pleno": str(nro_nf),
                "artigo": str(artigo),
                "descricao": to_text(fiscal.get("descricao")),
                "qtd_view": to_text(pleno.get("qtd_devolvida")),
                "qtd_nf": to_text(fiscal.get("fis02_qtd")),
                "motivo": motivo,
                "causa": parse_causa(motivo),
                "origem": origin_doc,
                "requisicao_origem": to_text(origin.get("est09_id")) if origin else "",
                "codigo_motivo_origem": to_text(origin.get("adm22_motivo_troca_id")) if origin else "",
                "mov_qtd": to_text(origin.get("est09_qtd")) if origin else "",
                "mov_usuario": to_text(origin.get("usuario_nome")) if origin else "",
                "nf_exportada": export_note,
                "qtd_exportada": export_qty,
                "data_envio_as400": export_date,
                "status_export": export_status,
                "as400_nf": as400_note,
                "as400_qtd": as400_qty,
                "status_envio": sent_status,
            }
        )
    return output


def print_markdown(rows: list[dict[str, str]]) -> None:
    headers = [
        "loja",
        "data_nf",
        "nf_pleno",
        "artigo",
        "descricao",
        "qtd_view",
        "qtd_nf",
        "causa",
        "motivo",
        "origem",
        "requisicao_origem",
        "codigo_motivo_origem",
        "mov_qtd",
        "mov_usuario",
        "nf_exportada",
        "qtd_exportada",
        "data_envio_as400",
        "status_export",
        "as400_nf",
        "as400_qtd",
        "status_envio",
    ]
    print("| " + " | ".join(headers) + " |")
    print("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        print("| " + " | ".join(row.get(header, "").replace("|", "/") for header in headers) + " |")


def print_csv(rows: list[dict[str, str]]) -> None:
    headers = list(rows[0].keys()) if rows else []
    print(";".join(headers))
    for row in rows:
        print(";".join(row.get(header, "").replace(";", ",") for header in headers))


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    env_path = (root / args.env).resolve()
    sqlite_path = (root / args.db).resolve()
    artigos = parse_artigos(args.artigos)

    env = read_env(env_path)
    with connect_mysql(env) as mysql_conn:
        pleno_rows = fetch_pleno_view(mysql_conn, args.loja, artigos, args.start_date, args.end_date)
        fiscal_rows = fetch_fiscal_rows(mysql_conn, args.loja, artigos, args.start_date, args.end_date)
        fiscal_item_ids = [int(row["fis02_id"]) for row in fiscal_rows if row.get("fis02_id")]
        origins = fetch_origins(mysql_conn, fiscal_item_ids)

    exports, as400 = fetch_sqlite_rows(sqlite_path, args.loja, artigos, args.start_date, args.end_date)
    rows = build_rows(pleno_rows, fiscal_rows, origins, exports, as400)

    if args.format == "csv":
        print_csv(rows)
    else:
        print_markdown(rows)


if __name__ == "__main__":
    main()
