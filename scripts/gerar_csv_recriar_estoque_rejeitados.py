#!/usr/bin/env python3
"""Gera o CSV de recreacao de estoque no mesmo layout do processo anterior."""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from auditar_xmls_rejeitados_estoque import ROOT, chunked, load_env


FIELDS = [
    "loja", "nome_loja", "codigo", "descricao", "qtd_xml_total",
    "qtd_recriar_estoque", "qtd_xml_original", "qtd_movimentada",
    "valor_recriar_estoque", "valor_xml_original", "valor_movimentado",
    "notas_distintas", "ocorrencias_item", "notas", "chaves", "mcd03_id",
    "mcd03_flgativa_compra", "mcd03_flgativa_venda", "mcd01_flgativa",
    "mcd01_flgativa_compra", "mcd03_perc_aliquota_efetiva_fcx",
    "fis10_csticms_id_fcx", "dom01_tributacao_fcx_id",
]


def num(value: str | None) -> Decimal:
    return Decimal(str(value or "0"))


def metadata(conn, pairs: list[tuple[int, str]]) -> dict[tuple[int, str], dict]:
    result = {}
    for values in chunked(pairs, 400):
        where = " OR ".join(["(f.cfg06_numero=%s AND m.mcd01_codint=%s)"] * len(values))
        params = [value for pair in values for value in pair]
        sql = f"""
            SELECT f.cfg06_numero AS loja, m.mcd01_codint AS codigo,
                m.mcd01_descricao AS descricao, mf.mcd03_id,
                mf.mcd03_flgativa_compra, mf.mcd03_flgativa_venda,
                m.mcd01_flgativa, m.mcd01_flgativa_compra,
                mf.mcd03_perc_aliquota_efetiva_fcx,
                mf.fis10_csticms_id_fcx, mf.dom01_tributacao_fcx_id
            FROM cfg06_filial f
            JOIN mcd03_mercadoria_filial mf ON mf.cfg06_filial_id = f.cfg06_id
            JOIN mcd01_mercadoria m ON m.mcd01_id = mf.mcd01_mercadoria_id
            WHERE {where}
        """
        with conn.cursor() as cur:
            cur.execute(sql, params)
            for row in cur.fetchall():
                result[(int(row["loja"]), str(row["codigo"]))] = row
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("items_csv", type=Path)
    args = parser.parse_args()

    candidates = []
    with args.items_csv.open(encoding="utf-8-sig") as source:
        for row in csv.DictReader(source):
            if row["status_item"] != "MOVIMENTOU_ESTOQUE":
                candidates.append(row)
    pairs = sorted({(int(row["loja"]), row["codigo_produto_xml"]) for row in candidates if row["codigo_produto_xml"]})

    import pymysql
    env = load_env(ROOT / ".env")
    conn = pymysql.connect(host=env["MYSQL_HOST"], port=int(env.get("MYSQL_PORT", "3306")), user=env["MYSQL_USER"], password=env["MYSQL_PASSWORD"], database=env["MYSQL_DATABASE"], charset="latin1", cursorclass=pymysql.cursors.DictCursor)
    try:
        registrations = metadata(conn, pairs)
    finally:
        conn.close()

    grouped = {}
    for row in candidates:
        key = (int(row["loja"]), row["codigo_produto_xml"])
        target = grouped.setdefault(key, {
            "loja": key[0], "nome_loja": row["nome_loja"], "codigo": key[1],
            "descricao": row["descricao_produto_xml"], "qtd_xml_total": Decimal("0"),
            "valor_recriar_estoque": Decimal("0"), "notas": set(), "chaves": set(), "ocorrencias_item": 0,
        })
        target["qtd_xml_total"] += num(row["quantidade_xml"])
        target["valor_recriar_estoque"] += num(row["valor_xml"])
        target["notas"].add(str(row["nota_xml"]))
        target["chaves"].add(row["chave"])
        target["ocorrencias_item"] += 1

    rows = []
    for key, row in sorted(grouped.items()):
        registration = registrations.get(key, {})
        qty = row["qtd_xml_total"]
        value = row["valor_recriar_estoque"]
        rows.append({
            "loja": row["loja"], "nome_loja": row["nome_loja"], "codigo": row["codigo"],
            "descricao": registration.get("descricao") or row["descricao"],
            "qtd_xml_total": f"{qty:.3f}", "qtd_recriar_estoque": f"{qty:.3f}",
            "qtd_xml_original": f"{qty:.3f}", "qtd_movimentada": "0.000",
            "valor_recriar_estoque": f"{value:.2f}", "valor_xml_original": f"{value:.2f}",
            "valor_movimentado": "0.00", "notas_distintas": len(row["notas"]),
            "ocorrencias_item": row["ocorrencias_item"],
            "notas": ",".join(sorted(row["notas"], key=lambda item: int(item) if item.isdigit() else item)),
            "chaves": ",".join(sorted(row["chaves"])), "mcd03_id": registration.get("mcd03_id", ""),
            "mcd03_flgativa_compra": registration.get("mcd03_flgativa_compra", ""),
            "mcd03_flgativa_venda": registration.get("mcd03_flgativa_venda", ""),
            "mcd01_flgativa": registration.get("mcd01_flgativa", ""),
            "mcd01_flgativa_compra": registration.get("mcd01_flgativa_compra", ""),
            "mcd03_perc_aliquota_efetiva_fcx": registration.get("mcd03_perc_aliquota_efetiva_fcx", ""),
            "fis10_csticms_id_fcx": registration.get("fis10_csticms_id_fcx", ""),
            "dom01_tributacao_fcx_id": registration.get("dom01_tributacao_fcx_id", ""),
        })

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "outputs" / "rejeitados_lojas_proprias" / f"itens_para_recriar_estoque_por_filial_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "itens_para_recriar_estoque_consolidado_por_loja_artigo.csv"
    with out.open("w", newline="", encoding="utf-8-sig") as target:
        writer = csv.DictWriter(target, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"itens_sem_movimento={len(candidates)} linhas_consolidadas={len(rows)} cadastros_encontrados={len(registrations)}")
    print(out)


if __name__ == "__main__":
    main()
