#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, ".python_packages")


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "outputs" / "pleno_stock_audit"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Exporta trilhas de auditoria de estoque diretamente do Pleno: "
            "estoque diario, vendas, movimentos, notas, pedidos, inventarios e conciliacao."
        )
    )
    parser.add_argument("--date", help="Data unica da auditoria no formato YYYY-MM-DD.")
    parser.add_argument("--start-date", help="Data inicial no formato YYYY-MM-DD.")
    parser.add_argument("--end-date", help="Data final no formato YYYY-MM-DD.")
    parser.add_argument(
        "--lojas",
        help="Lista de lojas separadas por virgula. Se omitido, exporta todas as lojas.",
    )
    parser.add_argument(
        "--all-lojas",
        action="store_true",
        help="Exporta todas as lojas e identifica a carga como lojas_todas.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Diretorio base de saida. Padrao: {DEFAULT_OUT_DIR}",
    )
    parser.add_argument(
        "--limit-top",
        type=int,
        default=500,
        help="Quantidade maxima de linhas nos arquivos top_divergencias e top_movimentos.",
    )
    return parser.parse_args()


def resolve_period(args: argparse.Namespace) -> tuple[str, str]:
    if args.date and (args.start_date or args.end_date):
        raise SystemExit("Use --date ou --start-date/--end-date, nao os dois.")
    if args.date:
        return args.date, args.date
    if args.start_date and args.end_date:
        return args.start_date, args.end_date
    yesterday = date.today() - timedelta(days=1)
    value = yesterday.isoformat()
    return value, value


def parse_lojas(value: str | None) -> list[int]:
    if not value:
        return []
    lojas = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        lojas.append(int(item))
    return lojas


def load_env() -> dict[str, str]:
    env = dict(os.environ)
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            key, value = line.split("=", 1)
            env[key] = value.strip().strip('"').strip("'")
    return env


def normalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return value


def fetch_all(conn: Any, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [{key: normalize(value) for key, value in row.items()} for row in cur.fetchall()]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def loja_filter(alias: str, lojas: list[int], params: list[Any]) -> str:
    if not lojas:
        return ""
    params.extend(lojas)
    placeholders = ", ".join(["%s"] * len(lojas))
    return f" AND {alias}.cfg06_numero IN ({placeholders})"


def queries(start_date: str, end_date: str, lojas: list[int], limit_top: int) -> dict[str, tuple[str, list[Any]]]:
    result: dict[str, tuple[str, list[Any]]] = {}
    previous_start_date = (date.fromisoformat(start_date) - timedelta(days=1)).isoformat()

    params: list[Any] = [previous_start_date, start_date, end_date, start_date, start_date, end_date]
    loja_sql = loja_filter("f", lojas, params)
    result["estoque_diario_loja"] = (
        f"""
        WITH previous_stock AS (
            SELECT *
            FROM est01_estoque_diario
            WHERE est01_data = %s
        ),
        base AS (
            SELECT DISTINCT mcd03_mercadoria_filial_id, dom18_finalidadenf_id
            FROM est01_estoque_diario
            WHERE est01_data BETWEEN %s AND %s
            UNION
            SELECT DISTINCT mcd03_mercadoria_filial_id, dom18_finalidadenf_id
            FROM previous_stock
        )
        SELECT
            f.cfg06_numero AS loja,
            f.cfg06_nome AS nome_loja,
            %s AS data_movimento,
            COUNT(*) AS itens,
            ROUND(SUM(COALESCE(prev.est01_qtd_fim_dia, ed.est01_qtd_inicio_dia, 0)), 3) AS qtd_inicio,
            ROUND(SUM(COALESCE(ed.est01_qtd_fim_dia, prev.est01_qtd_fim_dia, 0)), 3) AS qtd_fim,
            ROUND(SUM(COALESCE(ed.est01_qtd_fim_dia, prev.est01_qtd_fim_dia, 0) -
                      COALESCE(prev.est01_qtd_fim_dia, ed.est01_qtd_inicio_dia, 0)), 3) AS variacao_qtd,
            ROUND(SUM(COALESCE(ed.est01_qtd_vendida, 0)), 3) AS qtd_vendida_estoque_diario,
            ROUND(SUM(COALESCE(ed.est01_vlrtot_venda_dia, 0)), 2) AS valor_venda_estoque_diario,
            ROUND(SUM(COALESCE(prev.est01_qtd_fim_dia, ed.est01_qtd_inicio_dia, 0) *
                      COALESCE(prev.est01_vlr_custo_medio_fim_dia, ed.est01_vlr_custo_medio_inicio_dia, 0)), 2) AS valor_inicio_custo,
            ROUND(SUM(COALESCE(ed.est01_qtd_fim_dia, prev.est01_qtd_fim_dia, 0) *
                      COALESCE(ed.est01_vlr_custo_medio_fim_dia, prev.est01_vlr_custo_medio_fim_dia, 0)), 2) AS valor_fim_custo,
            ROUND(SUM((COALESCE(ed.est01_qtd_fim_dia, prev.est01_qtd_fim_dia, 0) *
                       COALESCE(ed.est01_vlr_custo_medio_fim_dia, prev.est01_vlr_custo_medio_fim_dia, 0)) -
                      (COALESCE(prev.est01_qtd_fim_dia, ed.est01_qtd_inicio_dia, 0) *
                       COALESCE(prev.est01_vlr_custo_medio_fim_dia, ed.est01_vlr_custo_medio_inicio_dia, 0))), 2) AS variacao_valor_custo
        FROM base
        JOIN mcd03_mercadoria_filial mf ON mf.mcd03_id = base.mcd03_mercadoria_filial_id
        JOIN cfg06_filial f ON f.cfg06_id = mf.cfg06_filial_id
        LEFT JOIN est01_estoque_diario ed
            ON ed.mcd03_mercadoria_filial_id = base.mcd03_mercadoria_filial_id
           AND ed.dom18_finalidadenf_id = base.dom18_finalidadenf_id
           AND ed.est01_data BETWEEN %s AND %s
        LEFT JOIN previous_stock prev
            ON prev.mcd03_mercadoria_filial_id = base.mcd03_mercadoria_filial_id
           AND prev.dom18_finalidadenf_id = base.dom18_finalidadenf_id
        WHERE 1 = 1
          {loja_sql}
        GROUP BY f.cfg06_numero, f.cfg06_nome
        ORDER BY f.cfg06_numero
        """,
        params,
    )

    params = [previous_start_date, start_date, end_date, start_date, start_date, end_date]
    loja_sql = loja_filter("f", lojas, params)
    result["estoque_diario_sku"] = (
        f"""
        WITH previous_stock AS (
            SELECT *
            FROM est01_estoque_diario
            WHERE est01_data = %s
        ),
        base AS (
            SELECT DISTINCT mcd03_mercadoria_filial_id, dom18_finalidadenf_id
            FROM est01_estoque_diario
            WHERE est01_data BETWEEN %s AND %s
            UNION
            SELECT DISTINCT mcd03_mercadoria_filial_id, dom18_finalidadenf_id
            FROM previous_stock
        )
        SELECT
            f.cfg06_numero AS loja,
            f.cfg06_nome AS nome_loja,
            %s AS data_movimento,
            m.mcd01_codint AS sku,
            base.dom18_finalidadenf_id AS finalidade_estoque,
            LEFT(COALESCE(m.mcd01_descricao_curta, m.mcd01_descricao), 120) AS descricao,
            ROUND(COALESCE(prev.est01_qtd_fim_dia, ed.est01_qtd_inicio_dia, 0), 3) AS qtd_inicio,
            ROUND(COALESCE(prev.est01_qtd_fim_dia, ed.est01_qtd_inicio_dia, 0) *
                  COALESCE(prev.est01_vlr_custo_medio_fim_dia, ed.est01_vlr_custo_medio_inicio_dia, 0), 2) AS valor_inicio_custo,
            ROUND(COALESCE(ed.est01_qtd_fim_dia, prev.est01_qtd_fim_dia, 0), 3) AS qtd_fim,
            ROUND(COALESCE(ed.est01_qtd_fim_dia, prev.est01_qtd_fim_dia, 0) *
                  COALESCE(ed.est01_vlr_custo_medio_fim_dia, prev.est01_vlr_custo_medio_fim_dia, 0), 2) AS valor_fim_custo,
            ROUND(COALESCE(ed.est01_qtd_fim_dia, prev.est01_qtd_fim_dia, 0) -
                  COALESCE(prev.est01_qtd_fim_dia, ed.est01_qtd_inicio_dia, 0), 3) AS variacao_qtd,
            ROUND((COALESCE(ed.est01_qtd_fim_dia, prev.est01_qtd_fim_dia, 0) *
                   COALESCE(ed.est01_vlr_custo_medio_fim_dia, prev.est01_vlr_custo_medio_fim_dia, 0)) -
                  (COALESCE(prev.est01_qtd_fim_dia, ed.est01_qtd_inicio_dia, 0) *
                   COALESCE(prev.est01_vlr_custo_medio_fim_dia, ed.est01_vlr_custo_medio_inicio_dia, 0)), 2) AS variacao_valor_custo,
            ROUND(COALESCE(ed.est01_qtd_vendida, 0), 3) AS qtd_vendida_estoque_diario,
            ROUND(COALESCE(ed.est01_vlrtot_venda_dia, 0), 2) AS valor_venda_estoque_diario,
            ROUND(COALESCE(prev.est01_vlr_custo_medio_fim_dia, ed.est01_vlr_custo_medio_inicio_dia, 0), 4) AS custo_inicio,
            ROUND(COALESCE(ed.est01_vlr_custo_medio_fim_dia, prev.est01_vlr_custo_medio_fim_dia, 0), 4) AS custo_fim
        FROM base
        JOIN mcd03_mercadoria_filial mf ON mf.mcd03_id = base.mcd03_mercadoria_filial_id
        JOIN cfg06_filial f ON f.cfg06_id = mf.cfg06_filial_id
        JOIN mcd01_mercadoria m ON m.mcd01_id = mf.mcd01_mercadoria_id
        LEFT JOIN est01_estoque_diario ed
            ON ed.mcd03_mercadoria_filial_id = base.mcd03_mercadoria_filial_id
           AND ed.dom18_finalidadenf_id = base.dom18_finalidadenf_id
           AND ed.est01_data BETWEEN %s AND %s
        LEFT JOIN previous_stock prev
            ON prev.mcd03_mercadoria_filial_id = base.mcd03_mercadoria_filial_id
           AND prev.dom18_finalidadenf_id = base.dom18_finalidadenf_id
        WHERE 1 = 1
          {loja_sql}
        ORDER BY f.cfg06_numero, data_movimento, m.mcd01_codint
        """,
        params,
    )

    params = [start_date, end_date]
    loja_sql = loja_filter("f", lojas, params)
    result["vendas_sku"] = (
        f"""
        SELECT
            f.cfg06_numero AS loja,
            f.cfg06_nome AS nome_loja,
            c.fcx01_data AS data_movimento,
            m.mcd01_codint AS sku,
            LEFT(COALESCE(m.mcd01_descricao_curta, m.mcd01_descricao), 120) AS descricao,
            ROUND(SUM(i.fcx02_qtd), 3) AS qtd_vendida,
            ROUND(SUM(i.fcx02_vlrtot), 2) AS valor_vendido,
            COUNT(DISTINCT c.fcx01_id) AS cupons
        FROM fcx02_cupom_item i
        JOIN fcx01_cupom c ON c.fcx01_id = i.fcx01_cupom_id
        JOIN cfg06_filial f ON f.cfg06_id = c.cfg06_filial_id
        LEFT JOIN mcd01_mercadoria m ON m.mcd01_id = i.mcd01_mercadoria_id
        WHERE c.fcx01_data BETWEEN %s AND %s
          AND IFNULL(c.fcx01_flgestornado, 0) = 0
          AND IFNULL(c.fcx01_cupom_id_cancelado, 0) = 0
          AND IFNULL(i.fcx02_flgestornado, 0) = 0
          {loja_sql}
        GROUP BY f.cfg06_numero, f.cfg06_nome, c.fcx01_data, m.mcd01_codint, descricao
        ORDER BY f.cfg06_numero, c.fcx01_data, m.mcd01_codint
        """,
        params,
    )

    signed_qty = """
        CASE
            WHEN e.est04_inventario_item_id IS NOT NULL THEN ii.est04_contagem_final - ii.est04_qtd_sistema
            WHEN e.fis02_notafiscal_item_id IS NOT NULL THEN IF(nf.fis01_entrada_saida = 'E', ni.fis02_qtd, -ni.fis02_qtd)
            WHEN e.fcx02_cupom_item_id IS NOT NULL THEN -ci.fcx02_qtd
            WHEN e.est02_boletim_consumo_producao_id IS NOT NULL THEN IF(b.est02_entrada_saida = 'E', b.est02_qtd, -b.est02_qtd)
            ELSE 0
        END
    """
    signed_value = """
        CASE
            WHEN e.est04_inventario_item_id IS NOT NULL
                THEN (ii.est04_contagem_final - ii.est04_qtd_sistema) * COALESCE(ed.est01_vlr_custo_medio_fim_dia, 0)
            WHEN e.fis02_notafiscal_item_id IS NOT NULL
                THEN IF(nf.fis01_entrada_saida = 'E', ni.fis02_qtd, -ni.fis02_qtd)
                     * COALESCE(NULLIF(ni.fis02_vlrunit_liquido, 0), NULLIF(ni.fis02_vlrunit, 0), ed.est01_vlr_custo_medio_fim_dia, 0)
            WHEN e.fcx02_cupom_item_id IS NOT NULL
                THEN -ci.fcx02_qtd * COALESCE(ed.est01_vlr_custo_medio_fim_dia, 0)
            WHEN e.est02_boletim_consumo_producao_id IS NOT NULL
                THEN IF(b.est02_entrada_saida = 'E', b.est02_qtd, -b.est02_qtd)
                     * COALESCE(NULLIF(b.est02_vlrcusto, 0), ed.est01_vlr_custo_medio_fim_dia, 0)
            ELSE 0
        END
    """
    origem = """
        CASE
            WHEN e.est04_inventario_item_id IS NOT NULL THEN 'INVENTARIO'
            WHEN e.fis02_notafiscal_item_id IS NOT NULL THEN CONCAT('NF_', nf.fis01_entrada_saida)
            WHEN e.fcx02_cupom_item_id IS NOT NULL THEN 'VENDA_CUPOM'
            WHEN e.est02_boletim_consumo_producao_id IS NOT NULL AND b.est02_entrada_saida = 'S' THEN 'AUTOCONSUMO'
            WHEN e.est02_boletim_consumo_producao_id IS NOT NULL AND b.est02_entrada_saida = 'E' THEN 'AUTOCONSUMO_ENTRADA'
            ELSE 'SEM_CAUSA'
        END
    """

    ed_custo_cte = f"""
        ed_custo AS (
            SELECT
                mcd03_mercadoria_filial_id,
                est01_data,
                MAX(est01_qtd_inicio_dia) AS est01_qtd_inicio_dia,
                MAX(est01_vlr_custo_medio_fim_dia) AS est01_vlr_custo_medio_fim_dia
            FROM est01_estoque_diario
            WHERE est01_data BETWEEN '{start_date}' AND '{end_date}'
            GROUP BY mcd03_mercadoria_filial_id, est01_data
        )
    """

    inventario_ja_no_inicio = """
        e.est04_inventario_item_id IS NOT NULL
        AND ABS(COALESCE(ed.est01_qtd_inicio_dia, 0) - COALESCE(ii.est04_contagem_final, 0)) < 0.001
    """

    devolucao_info_cte = """
        troca_info AS (
            SELECT
                tr.fis02_notafiscal_item_id,
                GROUP_CONCAT(DISTINCT tr.est09_id ORDER BY tr.est09_id SEPARATOR '|') AS devolucao_codigos,
                GROUP_CONCAT(DISTINCT tr.adm22_motivo_troca_id ORDER BY tr.adm22_motivo_troca_id SEPARATOR '|') AS devolucao_motivo_ids,
                GROUP_CONCAT(DISTINCT
                    CASE
                        WHEN mt.adm22_descricao LIKE 'CAUSA %%'
                            THEN SUBSTRING_INDEX(SUBSTRING(mt.adm22_descricao, 7), ' ', 1)
                        ELSE NULL
                    END
                    ORDER BY mt.adm22_descricao SEPARATOR '|'
                ) AS devolucao_causa_codigos,
                GROUP_CONCAT(DISTINCT mt.adm22_descricao ORDER BY mt.adm22_descricao SEPARATOR ' | ') AS devolucao_causas,
                ROUND(SUM(IF(tr.est09_entrada_saida = 'E', tr.est09_qtd, -tr.est09_qtd)), 3) AS devolucao_qtd
            FROM est09_troca_movimento tr
            LEFT JOIN adm22_motivo_troca mt
                ON mt.adm22_id = tr.adm22_motivo_troca_id
            WHERE tr.fis02_notafiscal_item_id IS NOT NULL
            GROUP BY tr.fis02_notafiscal_item_id
        ),
        retificacao_info AS (
            SELECT
                d.fis02_notafiscal_item_id,
                GROUP_CONCAT(DISTINCT d.dia01_id ORDER BY d.dia01_id SEPARATOR '|') AS retificacao_ids,
                GROUP_CONCAT(DISTINCT d.dia01_albaram ORDER BY d.dia01_albaram SEPARATOR '|') AS retificacao_albarans,
                GROUP_CONCAT(DISTINCT d.dia01_tipo_operacao ORDER BY d.dia01_tipo_operacao SEPARATOR '|') AS retificacao_tipos,
                GROUP_CONCAT(DISTINCT d.dia01_aprovado_dia ORDER BY d.dia01_aprovado_dia SEPARATOR '|') AS retificacao_aprovacoes,
                ROUND(SUM(d.dia01_qtd_embalagem), 3) AS retificacao_qtd_embalagem,
                ROUND(SUM(d.dia01_qtdtot_unidade), 3) AS retificacao_qtd_unidade
            FROM dia01_ajustes_recebimento d
            WHERE d.fis02_notafiscal_item_id IS NOT NULL
            GROUP BY d.fis02_notafiscal_item_id
        )
    """

    params = [start_date, end_date]
    loja_sql = loja_filter("f", lojas, params)
    result["movimentos_estoque"] = (
        f"""
        WITH {ed_custo_cte}, {devolucao_info_cte}
        SELECT
            f.cfg06_numero AS loja,
            f.cfg06_nome AS nome_loja,
            e.est05_data AS data_movimento,
            m.mcd01_codint AS sku,
            LEFT(COALESCE(m.mcd01_descricao_curta, m.mcd01_descricao), 120) AS descricao,
            {origem} AS origem,
            e.est05_id AS movimento_id,
            nf.fis01_nronf AS nota,
            nf.fis01_serienf AS serie,
            nf.fis01_entrada_saida AS nota_entrada_saida,
            inv.est03_id AS inventario_id,
            b.est02_id AS boletim_id,
            ci.fcx01_cupom_id AS cupom_id,
            troca.devolucao_codigos,
            troca.devolucao_motivo_ids,
            troca.devolucao_causa_codigos,
            troca.devolucao_causas,
            troca.devolucao_qtd,
            retif.retificacao_ids,
            retif.retificacao_albarans,
            retif.retificacao_tipos,
            retif.retificacao_aprovacoes,
            retif.retificacao_qtd_embalagem,
            retif.retificacao_qtd_unidade,
            ROUND({signed_qty}, 3) AS qtd_movimento,
            ROUND({signed_value}, 2) AS valor_movimento_custo
        FROM est05_estoque_movimento e
        JOIN mcd03_mercadoria_filial mf ON mf.mcd03_id = e.mcd03_mercadoria_filial_id
        JOIN cfg06_filial f ON f.cfg06_id = mf.cfg06_filial_id
        JOIN mcd01_mercadoria m ON m.mcd01_id = mf.mcd01_mercadoria_id
        LEFT JOIN ed_custo ed
            ON ed.mcd03_mercadoria_filial_id = e.mcd03_mercadoria_filial_id
           AND ed.est01_data = e.est05_data
        LEFT JOIN est04_inventario_item ii ON ii.est04_id = e.est04_inventario_item_id
        LEFT JOIN est03_inventario inv ON inv.est03_id = ii.est03_inventario_id
        LEFT JOIN fis02_notafiscal_item ni ON ni.fis02_id = e.fis02_notafiscal_item_id
        LEFT JOIN fis01_notafiscal nf ON nf.fis01_id = ni.fis01_notafiscal_id
        LEFT JOIN fcx02_cupom_item ci ON ci.fcx02_id = e.fcx02_cupom_item_id
        LEFT JOIN est02_boletim_consumo_producao b ON b.est02_id = e.est02_boletim_consumo_producao_id
        LEFT JOIN troca_info troca ON troca.fis02_notafiscal_item_id = e.fis02_notafiscal_item_id
        LEFT JOIN retificacao_info retif ON retif.fis02_notafiscal_item_id = e.fis02_notafiscal_item_id
        WHERE e.est05_data BETWEEN %s AND %s
          {loja_sql}
        ORDER BY f.cfg06_numero, e.est05_data, m.mcd01_codint, e.est05_id
        """,
        params,
    )

    params = [start_date, end_date]
    loja_sql = loja_filter("f", lojas, params)
    result["movimentos_resumo"] = (
        f"""
        WITH {ed_custo_cte}
        SELECT
            f.cfg06_numero AS loja,
            f.cfg06_nome AS nome_loja,
            e.est05_data AS data_movimento,
            {origem} AS origem,
            COUNT(*) AS linhas,
            ROUND(SUM(CASE
                WHEN e.est02_boletim_consumo_producao_id IS NOT NULL AND b.est02_entrada_saida = 'S' THEN ABS({signed_qty})
                WHEN e.est02_boletim_consumo_producao_id IS NOT NULL THEN 0
                ELSE {signed_qty}
            END), 3) AS qtd_movimento,
            ROUND(SUM(CASE
                WHEN e.est02_boletim_consumo_producao_id IS NOT NULL AND b.est02_entrada_saida = 'S' THEN ABS({signed_value})
                WHEN e.est02_boletim_consumo_producao_id IS NOT NULL THEN 0
                ELSE {signed_value}
            END), 2) AS valor_movimento_custo
        FROM est05_estoque_movimento e
        JOIN mcd03_mercadoria_filial mf ON mf.mcd03_id = e.mcd03_mercadoria_filial_id
        JOIN cfg06_filial f ON f.cfg06_id = mf.cfg06_filial_id
        LEFT JOIN ed_custo ed
            ON ed.mcd03_mercadoria_filial_id = e.mcd03_mercadoria_filial_id
           AND ed.est01_data = e.est05_data
        LEFT JOIN est04_inventario_item ii ON ii.est04_id = e.est04_inventario_item_id
        LEFT JOIN fis02_notafiscal_item ni ON ni.fis02_id = e.fis02_notafiscal_item_id
        LEFT JOIN fis01_notafiscal nf ON nf.fis01_id = ni.fis01_notafiscal_id
        LEFT JOIN fcx02_cupom_item ci ON ci.fcx02_id = e.fcx02_cupom_item_id
        LEFT JOIN est02_boletim_consumo_producao b ON b.est02_id = e.est02_boletim_consumo_producao_id
        WHERE e.est05_data BETWEEN %s AND %s
          {loja_sql}
        GROUP BY f.cfg06_numero, f.cfg06_nome, e.est05_data, origem
        ORDER BY f.cfg06_numero, e.est05_data, origem
        """,
        params,
    )

    params = [start_date, end_date]
    loja_sql = loja_filter("f", lojas, params)
    result["notas_entrada"] = (
        f"""
        SELECT
            f.cfg06_numero AS loja,
            f.cfg06_nome AS nome_loja,
            nf.fis01_id AS nota_id,
            nf.fis01_nronf AS nota,
            nf.fis01_serienf AS serie,
            nf.fis01_data_emissao AS data_emissao,
            nf.fis01_data_entrada_saida AS data_entrada,
            nf.fis01_vlrtot_liquido AS valor_nf,
            m.mcd01_codint AS sku,
            LEFT(COALESCE(m.mcd01_descricao_curta, m.mcd01_descricao), 120) AS descricao,
            ROUND(SUM(ni.fis02_qtd), 3) AS qtd_nota,
            ROUND(SUM(ni.fis02_qtd * COALESCE(NULLIF(ni.fis02_vlrunit_liquido, 0), ni.fis02_vlrunit, 0)), 2) AS valor_item_nota,
            COUNT(DISTINCT e.est05_id) AS movimentos_estoque
        FROM fis01_notafiscal nf
        JOIN fis02_notafiscal_item ni ON ni.fis01_notafiscal_id = nf.fis01_id
        JOIN mcd03_mercadoria_filial mf ON mf.mcd03_id = ni.mcd03_mercadoria_filial_id
        JOIN cfg06_filial f ON f.cfg06_id = mf.cfg06_filial_id
        JOIN mcd01_mercadoria m ON m.mcd01_id = mf.mcd01_mercadoria_id
        LEFT JOIN est05_estoque_movimento e ON e.fis02_notafiscal_item_id = ni.fis02_id
        WHERE nf.fis01_entrada_saida = 'E'
          AND nf.fis01_data_entrada_saida BETWEEN %s AND %s
          {loja_sql}
        GROUP BY f.cfg06_numero, f.cfg06_nome, nf.fis01_id, nf.fis01_nronf, nf.fis01_serienf,
                 nf.fis01_data_emissao, nf.fis01_data_entrada_saida, nf.fis01_vlrtot_liquido,
                 m.mcd01_codint, descricao
        ORDER BY f.cfg06_numero, nf.fis01_data_entrada_saida, nf.fis01_nronf, m.mcd01_codint
        """,
        params,
    )

    params = [start_date, end_date]
    loja_sql = loja_filter("f", lojas, params)
    result["notas_cd"] = (
        f"""
        WITH {ed_custo_cte}
        SELECT
            f.cfg06_numero AS loja,
            f.cfg06_nome AS nome_loja,
            e.est05_data AS data_movimento,
            nf.fis01_id AS nota_id,
            nf.fis01_nronf AS nota,
            nf.fis01_serienf AS serie,
            nf.fis01_data_emissao AS data_emissao,
            nf.fis01_data_entrada_saida AS data_entrada_saida,
            m.mcd01_codint AS sku,
            LEFT(COALESCE(m.mcd01_descricao_curta, m.mcd01_descricao), 120) AS descricao,
            ROUND(ABS(SUM({signed_qty})), 3) AS qtd_nota_cd,
            ROUND(ABS(SUM({signed_value})), 2) AS valor_nota_cd,
            COUNT(DISTINCT e.est05_id) AS movimentos_estoque
        FROM est05_estoque_movimento e
        JOIN mcd03_mercadoria_filial mf ON mf.mcd03_id = e.mcd03_mercadoria_filial_id
        JOIN cfg06_filial f ON f.cfg06_id = mf.cfg06_filial_id
        JOIN mcd01_mercadoria m ON m.mcd01_id = mf.mcd01_mercadoria_id
        JOIN fis02_notafiscal_item ni ON ni.fis02_id = e.fis02_notafiscal_item_id
        JOIN fis01_notafiscal nf ON nf.fis01_id = ni.fis01_notafiscal_id
        LEFT JOIN ed_custo ed
            ON ed.mcd03_mercadoria_filial_id = e.mcd03_mercadoria_filial_id
           AND ed.est01_data = e.est05_data
        LEFT JOIN est04_inventario_item ii ON ii.est04_id = e.est04_inventario_item_id
        LEFT JOIN fcx02_cupom_item ci ON ci.fcx02_id = e.fcx02_cupom_item_id
        LEFT JOIN est02_boletim_consumo_producao b ON b.est02_id = e.est02_boletim_consumo_producao_id
        WHERE e.est05_data BETWEEN %s AND %s
          AND nf.fis01_entrada_saida = 'S'
          AND nf.fis01_serienf = '1'
          {loja_sql}
        GROUP BY f.cfg06_numero, f.cfg06_nome, e.est05_data, nf.fis01_id, nf.fis01_nronf,
                 nf.fis01_serienf, nf.fis01_data_emissao, nf.fis01_data_entrada_saida,
                 m.mcd01_codint, descricao
        ORDER BY f.cfg06_numero, e.est05_data, nf.fis01_nronf, m.mcd01_codint
        """,
        params,
    )

    params = [start_date, end_date]
    loja_sql = loja_filter("f", lojas, params)
    result["notas_saida"] = (
        f"""
        WITH {ed_custo_cte}, {devolucao_info_cte}
        SELECT
            f.cfg06_numero AS loja,
            f.cfg06_nome AS nome_loja,
            e.est05_data AS data_movimento,
            nf.fis01_id AS nota_id,
            nf.fis01_nronf AS nota,
            nf.fis01_serienf AS serie,
            nf.fis01_data_emissao AS data_emissao,
            nf.fis01_data_entrada_saida AS data_saida,
            nf.fis01_entrada_saida AS entrada_saida,
            COALESCE(nf.fis01_flgcancelada, 0) AS cancelada,
            nf.fis01_vlrtot_liquido AS valor_nf,
            nf.fis01_nfe_chave AS chave_nfe,
            nf.fis01_nfe_cstat AS nfe_cstat,
            nf.fis01_nfe_xmotivo AS nfe_motivo,
            m.mcd01_codint AS sku,
            LEFT(COALESCE(m.mcd01_descricao_curta, m.mcd01_descricao), 120) AS descricao,
            ROUND(ABS(SUM({signed_qty})), 3) AS qtd_nota_saida,
            ROUND(ABS(SUM({signed_value})), 2) AS valor_nota_saida,
            COUNT(DISTINCT e.est05_id) AS movimentos_estoque,
            GROUP_CONCAT(DISTINCT e.est05_id ORDER BY e.est05_id SEPARATOR '|') AS movimento_ids,
            troca.devolucao_codigos,
            troca.devolucao_causa_codigos,
            troca.devolucao_causas
        FROM est05_estoque_movimento e
        JOIN mcd03_mercadoria_filial mf ON mf.mcd03_id = e.mcd03_mercadoria_filial_id
        JOIN cfg06_filial f ON f.cfg06_id = mf.cfg06_filial_id
        JOIN mcd01_mercadoria m ON m.mcd01_id = mf.mcd01_mercadoria_id
        JOIN fis02_notafiscal_item ni ON ni.fis02_id = e.fis02_notafiscal_item_id
        JOIN fis01_notafiscal nf ON nf.fis01_id = ni.fis01_notafiscal_id
        LEFT JOIN ed_custo ed
            ON ed.mcd03_mercadoria_filial_id = e.mcd03_mercadoria_filial_id
           AND ed.est01_data = e.est05_data
        LEFT JOIN est04_inventario_item ii ON ii.est04_id = e.est04_inventario_item_id
        LEFT JOIN fcx02_cupom_item ci ON ci.fcx02_id = e.fcx02_cupom_item_id
        LEFT JOIN est02_boletim_consumo_producao b ON b.est02_id = e.est02_boletim_consumo_producao_id
        LEFT JOIN troca_info troca ON troca.fis02_notafiscal_item_id = e.fis02_notafiscal_item_id
        WHERE e.est05_data BETWEEN %s AND %s
          AND nf.fis01_entrada_saida = 'S'
          AND COALESCE(nf.fis01_serienf, '') <> '1'
          {loja_sql}
        GROUP BY f.cfg06_numero, f.cfg06_nome, e.est05_data, nf.fis01_id, nf.fis01_nronf,
                 nf.fis01_serienf, nf.fis01_data_emissao, nf.fis01_data_entrada_saida,
                 nf.fis01_entrada_saida, nf.fis01_flgcancelada, nf.fis01_vlrtot_liquido,
                 nf.fis01_nfe_chave, nf.fis01_nfe_cstat, nf.fis01_nfe_xmotivo,
                 m.mcd01_codint, descricao, troca.devolucao_codigos,
                 troca.devolucao_causa_codigos, troca.devolucao_causas
        ORDER BY f.cfg06_numero, e.est05_data, nf.fis01_nronf, m.mcd01_codint
        """,
        params,
    )

    params = [end_date, end_date]
    loja_sql = loja_filter("f", lojas, params)
    result["notas_pendentes_entrada"] = (
        f"""
        SELECT
            f.cfg06_numero AS loja,
            f.cfg06_nome AS nome_loja,
            nf.fis01_id AS nota_id,
            nf.fis01_nronf AS nota,
            nf.fis01_serienf AS serie,
            nf.fis01_data_emissao AS data_emissao,
            nf.fis01_data_entrada_saida AS data_entrada,
            DATEDIFF(%s, nf.fis01_data_emissao) AS dias_pendente,
            nf.fis01_vlrtot_liquido AS valor_nf,
            COUNT(DISTINCT ni.fis02_id) AS itens,
            ROUND(SUM(ni.fis02_qtd), 3) AS qtd_total,
            ROUND(SUM(ni.fis02_qtd * COALESCE(NULLIF(ni.fis02_vlrunit_liquido, 0), ni.fis02_vlrunit, 0)), 2) AS valor_itens,
            COUNT(DISTINCT e.est05_id) AS movimentos_estoque,
            nf.fis01_flgtransf_em_transito AS transferencia_em_transito,
            nf.adm05_usuario_checkin_id AS usuario_checkin_id,
            'CD faturou para loja sem check-in' AS situacao
        FROM cfg06_filial f
        JOIN pes03_estabelecimento est ON est.pes03_id = f.pes03_estabelecimento_id
        JOIN pes04_pessoa dest ON dest.pes03_estabelecimento_id = est.pes03_id
        JOIN fis01_notafiscal nf ON nf.pes04_pessoa_dest = dest.pes04_id
        LEFT JOIN fis02_notafiscal_item ni ON ni.fis01_notafiscal_id = nf.fis01_id
        LEFT JOIN est05_estoque_movimento e ON e.fis02_notafiscal_item_id = ni.fis02_id
        WHERE nf.fis01_entrada_saida = 'S'
          AND nf.fis01_serienf = '1'
          AND nf.adm05_usuario_checkin_id IS NULL
          AND COALESCE(nf.fis01_flgcancelada, 0) = 0
          AND nf.fis01_data_emissao <= %s
          {loja_sql}
        GROUP BY f.cfg06_numero, f.cfg06_nome, nf.fis01_id, nf.fis01_nronf, nf.fis01_serienf,
                 nf.fis01_data_emissao, nf.fis01_data_entrada_saida, nf.fis01_vlrtot_liquido,
                 nf.fis01_flgtransf_em_transito, nf.adm05_usuario_checkin_id
        ORDER BY f.cfg06_numero, nf.fis01_data_emissao, nf.fis01_nronf
        """,
        params,
    )

    params = [f"{start_date} 00:00:00", f"{end_date} 23:59:59"]
    loja_sql = loja_filter("f", lojas, params)
    result["pedidos_transferencia"] = (
        f"""
        WITH pedidos AS (
            SELECT
                p.com16_id,
                p.cfg06_filial_dest_id,
                p.com16_nro_pedtransf_trd,
                p.com16_flgatendido_trd,
                p.com16_dthr
            FROM com16_pretransferencia p
            WHERE p.com16_dthr BETWEEN %s AND %s
              AND p.dom83_tipo_pedtransf_id = 2
        ),
        status_pedido AS (
            SELECT
                i.com16_pretransferencia_id,
                MAX(nf.fis01_nronf) AS nr_nota_pedido,
                MAX(fisico.fis02_notafiscal_item_id) AS item_nf_pedido
            FROM pedidos p
            JOIN com19_pretransferencia_item i ON i.com16_pretransferencia_id = p.com16_id
            LEFT JOIN com33_pedtransf_atendido a ON a.com19_pretransferencia_item_id = i.com19_id
            LEFT JOIN fis25_notafiscal_item_fisico fisico ON fisico.fis25_id = a.fis25_notafiscal_item_fisico_id
            LEFT JOIN fis01_notafiscal nf ON nf.fis01_id = fisico.fis01_notafiscal_id
            GROUP BY i.com16_pretransferencia_id
        ),
        custo_atual AS (
            SELECT
                mf.cfg06_filial_id,
                mf.mcd01_mercadoria_id,
                MAX(ea.est06_vlrcusto_medio) AS custo_medio
            FROM mcd03_mercadoria_filial mf
            JOIN est06_estoque_atual ea ON ea.mcd03_mercadoria_filial_id = mf.mcd03_id
            GROUP BY mf.cfg06_filial_id, mf.mcd01_mercadoria_id
        )
        SELECT
            f.cfg06_numero AS loja,
            f.cfg06_nome AS nome_loja,
            p.com16_nro_pedtransf_trd AS pedido,
            p.com16_dthr AS data_pedido,
            p.com16_flgatendido_trd AS atendido,
            m.mcd01_codint AS sku,
            LEFT(COALESCE(m.mcd01_descricao_curta, m.mcd01_descricao), 120) AS descricao,
            ROUND(i.com19_qtd, 3) AS qtd_pedida,
            ROUND(i.com19_qtd * COALESCE(custo.custo_medio, 0), 2) AS valor_pedido_custo_atual,
            ROUND(i.com19_qtd_confirmada, 3) AS qtd_confirmada,
            ROUND(i.com19_qtd_confirmada * COALESCE(custo.custo_medio, 0), 2) AS valor_confirmado_custo_atual,
            ROUND(fisico.fis25_qtd_nf, 3) AS qtd_nf,
            ROUND(fisico.fis25_qtd_nf * COALESCE(custo.custo_medio, 0), 2) AS valor_nf_custo_atual,
            COALESCE(nf.fis01_nronf, sp.nr_nota_pedido) AS nota,
            CASE WHEN sp.item_nf_pedido IS NOT NULL THEN 'Entrada realizada' ELSE 'Pendente Entrada' END AS situacao
        FROM pedidos p
        JOIN com19_pretransferencia_item i ON i.com16_pretransferencia_id = p.com16_id
        JOIN cfg06_filial f ON f.cfg06_id = p.cfg06_filial_dest_id
        LEFT JOIN com33_pedtransf_atendido a ON a.com19_pretransferencia_item_id = i.com19_id
        LEFT JOIN fis25_notafiscal_item_fisico fisico ON fisico.fis25_id = a.fis25_notafiscal_item_fisico_id
        LEFT JOIN fis01_notafiscal nf ON nf.fis01_id = fisico.fis01_notafiscal_id
        LEFT JOIN mcd01_mercadoria m ON m.mcd01_id = i.mcd01_mercadoria_id
        LEFT JOIN custo_atual custo
            ON custo.mcd01_mercadoria_id = i.mcd01_mercadoria_id
           AND custo.cfg06_filial_id = p.cfg06_filial_dest_id
        LEFT JOIN status_pedido sp ON sp.com16_pretransferencia_id = p.com16_id
        WHERE 1 = 1
          {loja_sql}
        ORDER BY f.cfg06_numero, p.com16_dthr, p.com16_nro_pedtransf_trd, m.mcd01_codint
        """,
        params,
    )

    params = [start_date, end_date]
    loja_sql = loja_filter("f", lojas, params)
    result["pedido_nota_divergencia"] = (
        f"""
        WITH notas_dia AS (
            SELECT DISTINCT
                nf.fis01_id,
                nf.fis01_nronf,
                nf.fis01_serienf,
                nf.fis01_data_emissao,
                e.est05_data AS fis01_data_entrada_saida,
                nf.dom14_operacao_fiscal_id,
                op.dom14_descricao,
                f.cfg06_id AS cfg06_filial_id,
                f.cfg06_numero,
                f.cfg06_nome
            FROM est05_estoque_movimento e
            JOIN mcd03_mercadoria_filial mf ON mf.mcd03_id = e.mcd03_mercadoria_filial_id
            JOIN cfg06_filial f ON f.cfg06_id = mf.cfg06_filial_id
            JOIN fis02_notafiscal_item ni ON ni.fis02_id = e.fis02_notafiscal_item_id
            JOIN fis01_notafiscal nf ON nf.fis01_id = ni.fis01_notafiscal_id
            LEFT JOIN dom14_operacao_fiscal op ON op.dom14_id = nf.dom14_operacao_fiscal_id
            WHERE nf.fis01_entrada_saida = 'S'
              AND nf.fis01_serienf = '1'
              AND e.est05_data BETWEEN %s AND %s
              {loja_sql}
        ),
        nota_skus AS (
            SELECT
                nd.fis01_id AS nota_id,
                mf.mcd01_mercadoria_id,
                ABS(SUM({signed_qty})) AS qtd_nota
            FROM notas_dia nd
            JOIN est05_estoque_movimento e ON e.est05_data = nd.fis01_data_entrada_saida
            JOIN mcd03_mercadoria_filial mf ON mf.mcd03_id = e.mcd03_mercadoria_filial_id
            JOIN fis02_notafiscal_item ni ON ni.fis02_id = e.fis02_notafiscal_item_id
            JOIN fis01_notafiscal nf ON nf.fis01_id = ni.fis01_notafiscal_id AND nf.fis01_id = nd.fis01_id
            LEFT JOIN est04_inventario_item ii ON ii.est04_id = e.est04_inventario_item_id
            LEFT JOIN fcx02_cupom_item ci ON ci.fcx02_id = e.fcx02_cupom_item_id
            LEFT JOIN est02_boletim_consumo_producao b ON b.est02_id = e.est02_boletim_consumo_producao_id
            WHERE mf.cfg06_filial_id = nd.cfg06_filial_id
            GROUP BY nd.fis01_id, mf.mcd01_mercadoria_id
        ),
        pedido_nota_explicito AS (
            SELECT DISTINCT
                p.com16_id AS pedido_id,
                p.com16_nro_pedtransf_trd AS pedido,
                p.com16_dthr AS data_pedido,
                p.com16_flgatendido_trd AS atendido,
                p.cfg06_filial_dest_id,
                nd.fis01_id AS nota_id,
                nd.fis01_nronf AS nota,
                nd.fis01_serienf AS serie,
                nd.fis01_data_emissao AS data_emissao,
                nd.fis01_data_entrada_saida AS data_entrada,
                nd.dom14_descricao AS operacao_fiscal,
                'VINCULO_EXPLICITO' AS tipo_vinculo
            FROM notas_dia nd
            JOIN fis02_notafiscal_item ni ON ni.fis01_notafiscal_id = nd.fis01_id
            JOIN fis25_notafiscal_item_fisico fisico ON fisico.fis02_notafiscal_item_id = ni.fis02_id
            JOIN com33_pedtransf_atendido a ON a.fis25_notafiscal_item_fisico_id = fisico.fis25_id
            JOIN com19_pretransferencia_item i ON i.com19_id = a.com19_pretransferencia_item_id
            JOIN com16_pretransferencia p ON p.com16_id = i.com16_pretransferencia_id
            WHERE p.cfg06_filial_dest_id = nd.cfg06_filial_id
        ),
        pedido_candidatos_base AS (
            SELECT
                nd.fis01_id AS nota_id,
                p.com16_id AS pedido_id,
                p.com16_nro_pedtransf_trd AS pedido,
                p.com16_dthr AS data_pedido,
                p.com16_flgatendido_trd AS atendido,
                p.cfg06_filial_dest_id,
                COUNT(DISTINCT ns.mcd01_mercadoria_id) AS itens_em_comum,
                SUM(LEAST(COALESCE(i.com19_qtd, 0), COALESCE(ns.qtd_nota, 0))) AS qtd_intersecao
            FROM notas_dia nd
            JOIN nota_skus ns ON ns.nota_id = nd.fis01_id
            JOIN com16_pretransferencia p
                ON p.cfg06_filial_dest_id = nd.cfg06_filial_id
               AND p.com16_dthr BETWEEN DATE_SUB(CONCAT(nd.fis01_data_entrada_saida, ' 00:00:00'), INTERVAL 2 DAY)
                                   AND CONCAT(nd.fis01_data_entrada_saida, ' 23:59:59')
               AND p.dom83_tipo_pedtransf_id IN (2, 3)
            JOIN com19_pretransferencia_item i
                ON i.com16_pretransferencia_id = p.com16_id
               AND i.mcd01_mercadoria_id = ns.mcd01_mercadoria_id
            GROUP BY nd.fis01_id, p.com16_id, p.com16_nro_pedtransf_trd, p.com16_dthr,
                     p.com16_flgatendido_trd, p.cfg06_filial_dest_id
            HAVING itens_em_comum > 0
        ),
        pedido_candidatos AS (
            SELECT
                base.*,
                ROW_NUMBER() OVER (
                    PARTITION BY base.nota_id
                    ORDER BY base.itens_em_comum DESC, base.qtd_intersecao DESC, base.data_pedido DESC, base.pedido_id DESC
                ) AS rn
            FROM pedido_candidatos_base base
        ),
        pedido_nota_inferido AS (
            SELECT
                c.pedido_id,
                c.pedido,
                c.data_pedido,
                c.atendido,
                c.cfg06_filial_dest_id,
                nd.fis01_id AS nota_id,
                nd.fis01_nronf AS nota,
                nd.fis01_serienf AS serie,
                nd.fis01_data_emissao AS data_emissao,
                nd.fis01_data_entrada_saida AS data_entrada,
                nd.dom14_descricao AS operacao_fiscal,
                'INFERIDO_POR_ITENS' AS tipo_vinculo
            FROM pedido_candidatos c
            JOIN notas_dia nd ON nd.fis01_id = c.nota_id
            WHERE c.rn = 1
              AND NOT EXISTS (
                  SELECT 1 FROM pedido_nota_explicito pe WHERE pe.nota_id = c.nota_id
              )
        ),
        pedido_nota AS (
            SELECT * FROM pedido_nota_explicito
            UNION ALL
            SELECT * FROM pedido_nota_inferido
        ),
        pedido_itens AS (
            SELECT
                pn.pedido_id,
                pn.nota_id,
                i.mcd01_mercadoria_id,
                SUM(i.com19_qtd) AS qtd_pedida,
                SUM(i.com19_qtd_confirmada) AS qtd_confirmada
            FROM pedido_nota pn
            JOIN com19_pretransferencia_item i ON i.com16_pretransferencia_id = pn.pedido_id
            GROUP BY pn.pedido_id, pn.nota_id, i.mcd01_mercadoria_id
        ),
        nota_itens AS (
            SELECT
                pn.pedido_id,
                pn.nota_id,
                mf.mcd01_mercadoria_id,
                ABS(SUM({signed_qty})) AS qtd_nota,
                ABS(SUM(ni.fis02_qtd * COALESCE(NULLIF(ni.fis02_vlrunit_liquido, 0), ni.fis02_vlrunit, 0))) AS valor_item_nota
            FROM pedido_nota pn
            JOIN est05_estoque_movimento e ON e.est05_data = pn.data_entrada
            JOIN mcd03_mercadoria_filial mf ON mf.mcd03_id = e.mcd03_mercadoria_filial_id
            JOIN fis02_notafiscal_item ni ON ni.fis02_id = e.fis02_notafiscal_item_id
            JOIN fis01_notafiscal nf ON nf.fis01_id = ni.fis01_notafiscal_id AND nf.fis01_id = pn.nota_id
            LEFT JOIN est04_inventario_item ii ON ii.est04_id = e.est04_inventario_item_id
            LEFT JOIN fcx02_cupom_item ci ON ci.fcx02_id = e.fcx02_cupom_item_id
            LEFT JOIN est02_boletim_consumo_producao b ON b.est02_id = e.est02_boletim_consumo_producao_id
            WHERE mf.cfg06_filial_id = pn.cfg06_filial_dest_id
            GROUP BY pn.pedido_id, pn.nota_id, mf.mcd01_mercadoria_id
        ),
        chaves AS (
            SELECT pedido_id, nota_id, mcd01_mercadoria_id FROM pedido_itens
            UNION
            SELECT pedido_id, nota_id, mcd01_mercadoria_id FROM nota_itens
        ),
        custo_atual AS (
            SELECT
                mf.cfg06_filial_id,
                mf.mcd01_mercadoria_id,
                MAX(ea.est06_vlrcusto_medio) AS custo_medio
            FROM mcd03_mercadoria_filial mf
            JOIN est06_estoque_atual ea ON ea.mcd03_mercadoria_filial_id = mf.mcd03_id
            GROUP BY mf.cfg06_filial_id, mf.mcd01_mercadoria_id
        )
        SELECT
            f.cfg06_numero AS loja,
            f.cfg06_nome AS nome_loja,
            pn.pedido,
            pn.data_pedido,
            pn.nota,
            pn.serie,
            pn.data_emissao,
            pn.data_entrada,
            pn.operacao_fiscal,
            pn.tipo_vinculo,
            m.mcd01_codint AS sku,
            LEFT(COALESCE(m.mcd01_descricao_curta, m.mcd01_descricao), 120) AS descricao,
            ROUND(COALESCE(pi.qtd_pedida, 0), 3) AS qtd_pedida,
            ROUND(COALESCE(pi.qtd_confirmada, 0), 3) AS qtd_confirmada,
            ROUND(COALESCE(ni.qtd_nota, 0), 3) AS qtd_nota,
            ROUND(COALESCE(ni.qtd_nota, 0) - COALESCE(pi.qtd_pedida, 0), 3) AS diferenca_qtd,
            ROUND(GREATEST(COALESCE(pi.qtd_pedida, 0) - COALESCE(ni.qtd_nota, 0), 0), 3) AS qtd_ruptura_pedido,
            ROUND(GREATEST(COALESCE(ni.qtd_nota, 0) - COALESCE(pi.qtd_pedida, 0), 0), 3) AS qtd_extra_nota,
            ROUND(COALESCE(pi.qtd_pedida, 0) * COALESCE(custo.custo_medio, 0), 2) AS valor_pedido_custo_atual,
            ROUND(COALESCE(ni.valor_item_nota, 0), 2) AS valor_item_nota,
            ROUND((COALESCE(ni.qtd_nota, 0) - COALESCE(pi.qtd_pedida, 0)) * COALESCE(custo.custo_medio, 0), 2) AS diferenca_valor_custo,
            ROUND(GREATEST(COALESCE(pi.qtd_pedida, 0) - COALESCE(ni.qtd_nota, 0), 0) * COALESCE(custo.custo_medio, 0), 2) AS valor_ruptura_pedido,
            CASE
                WHEN COALESCE(pi.qtd_pedida, 0) > 0 AND COALESCE(ni.qtd_nota, 0) = 0 THEN 'FALTOU_NA_NOTA'
                WHEN COALESCE(pi.qtd_pedida, 0) = 0 AND COALESCE(ni.qtd_nota, 0) > 0 THEN 'VEIO_SEM_PEDIDO'
                WHEN ABS(COALESCE(ni.qtd_nota, 0) - COALESCE(pi.qtd_pedida, 0)) > 0.001 THEN 'DIVERGENCIA_QTD'
                ELSE 'OK'
            END AS situacao,
            CASE
                WHEN COALESCE(pi.qtd_pedida, 0) > 0 AND COALESCE(ni.qtd_nota, 0) = 0 THEN 'Item estava no pedido e nao veio na nota CD.'
                WHEN COALESCE(pi.qtd_pedida, 0) = 0 AND COALESCE(ni.qtd_nota, 0) > 0 THEN 'Item veio na nota CD, mas nao estava no pedido vinculado.'
                WHEN COALESCE(ni.qtd_nota, 0) < COALESCE(pi.qtd_pedida, 0) THEN 'Nota CD veio com quantidade menor que o pedido.'
                WHEN COALESCE(ni.qtd_nota, 0) > COALESCE(pi.qtd_pedida, 0) THEN 'Nota CD veio com quantidade maior que o pedido.'
                ELSE 'Pedido e nota CD fecharam para o item.'
            END AS explicacao
        FROM chaves k
        JOIN pedido_nota pn ON pn.pedido_id = k.pedido_id AND pn.nota_id = k.nota_id
        JOIN cfg06_filial f ON f.cfg06_id = pn.cfg06_filial_dest_id
        JOIN mcd01_mercadoria m ON m.mcd01_id = k.mcd01_mercadoria_id
        LEFT JOIN pedido_itens pi
            ON pi.pedido_id = k.pedido_id
           AND pi.nota_id = k.nota_id
           AND pi.mcd01_mercadoria_id = k.mcd01_mercadoria_id
        LEFT JOIN nota_itens ni
            ON ni.pedido_id = k.pedido_id
           AND ni.nota_id = k.nota_id
           AND ni.mcd01_mercadoria_id = k.mcd01_mercadoria_id
        LEFT JOIN custo_atual custo
            ON custo.mcd01_mercadoria_id = k.mcd01_mercadoria_id
           AND custo.cfg06_filial_id = pn.cfg06_filial_dest_id
        UNION ALL

        SELECT
            nd.cfg06_numero AS loja,
            nd.cfg06_nome AS nome_loja,
            NULL AS pedido,
            NULL AS data_pedido,
            nd.fis01_nronf AS nota,
            nd.fis01_serienf AS serie,
            nd.fis01_data_emissao AS data_emissao,
            nd.fis01_data_entrada_saida AS data_entrada,
            nd.dom14_descricao AS operacao_fiscal,
            'SEM_VINCULO_PEDIDO' AS tipo_vinculo,
            m.mcd01_codint AS sku,
            LEFT(COALESCE(m.mcd01_descricao_curta, m.mcd01_descricao), 120) AS descricao,
            0 AS qtd_pedida,
            0 AS qtd_confirmada,
            ROUND(SUM(ni.fis02_qtd), 3) AS qtd_nota,
            ROUND(SUM(ni.fis02_qtd), 3) AS diferenca_qtd,
            0 AS qtd_ruptura_pedido,
            ROUND(SUM(ni.fis02_qtd), 3) AS qtd_extra_nota,
            0 AS valor_pedido_custo_atual,
            ROUND(SUM(ni.fis02_qtd * COALESCE(NULLIF(ni.fis02_vlrunit_liquido, 0), ni.fis02_vlrunit, 0)), 2) AS valor_item_nota,
            ROUND(SUM(ni.fis02_qtd * COALESCE(custo.custo_medio, 0)), 2) AS diferenca_valor_custo,
            0 AS valor_ruptura_pedido,
            'NOTA_CD_SEM_PEDIDO' AS situacao,
            'Nota CD sem pedido vinculado ou inferido para a loja no periodo.' AS explicacao
        FROM notas_dia nd
        JOIN est05_estoque_movimento e ON e.est05_data = nd.fis01_data_entrada_saida
        JOIN mcd03_mercadoria_filial mf ON mf.mcd03_id = e.mcd03_mercadoria_filial_id
        JOIN fis02_notafiscal_item ni ON ni.fis02_id = e.fis02_notafiscal_item_id
        JOIN fis01_notafiscal nf ON nf.fis01_id = ni.fis01_notafiscal_id AND nf.fis01_id = nd.fis01_id
        JOIN mcd01_mercadoria m ON m.mcd01_id = mf.mcd01_mercadoria_id
        LEFT JOIN custo_atual custo
            ON custo.mcd01_mercadoria_id = mf.mcd01_mercadoria_id
           AND custo.cfg06_filial_id = mf.cfg06_filial_id
        WHERE mf.cfg06_filial_id = nd.cfg06_filial_id
          AND NOT EXISTS (
            SELECT 1 FROM pedido_nota pn WHERE pn.nota_id = nd.fis01_id
        )
        GROUP BY nd.cfg06_numero, nd.cfg06_nome, nd.fis01_id, nd.fis01_nronf, nd.fis01_serienf,
                 nd.fis01_data_emissao, nd.fis01_data_entrada_saida, nd.dom14_descricao,
                 m.mcd01_codint, descricao
        ORDER BY
            loja,
            data_entrada,
            nota,
            pedido,
            CASE situacao
                WHEN 'FALTOU_NA_NOTA' THEN 1
                WHEN 'VEIO_SEM_PEDIDO' THEN 2
                WHEN 'NOTA_CD_SEM_PEDIDO' THEN 2
                WHEN 'DIVERGENCIA_QTD' THEN 3
                WHEN 'OK' THEN 4
                ELSE 5
            END,
            sku
        """,
        params,
    )

    params = [start_date, end_date, start_date, end_date]
    loja_sql = loja_filter("f", lojas, params)
    result["retificacoes"] = (
        f"""
        SELECT
            f.cfg06_numero AS loja,
            f.cfg06_nome AS nome_loja,
            d.dia01_id AS retificacao_id,
            d.dia01_numero_nf AS nota,
            d.dia01_data_nf AS data_nf,
            d.dia01_albaram AS albaran,
            d.dia01_data_albaram AS data_albaran,
            d.dia01_tipo_operacao AS tipo_operacao,
            d.dia01_aprovado_dia AS aprovado,
            d.dia01_dthr_exportacao AS exportacao_pleno,
            d.dia01_dthr_importacao AS importacao_pleno,
            m.mcd01_codint AS sku,
            LEFT(COALESCE(m.mcd01_descricao_curta, m.mcd01_descricao), 120) AS descricao,
            ROUND(d.dia01_qtd_embalagem, 3) AS qtd_embalagem,
            ROUND(d.dia01_qtdtot_unidade, 3) AS qtd_unidade,
            ni.fis02_id AS nota_item_id,
            nf.fis01_nronf AS nota_pleno,
            nf.fis01_serienf AS serie_pleno,
            nf.fis01_data_emissao AS data_emissao_pleno,
            nf.fis01_data_entrada_saida AS data_entrada_pleno
        FROM dia01_ajustes_recebimento d
        JOIN cfg06_filial f ON f.cfg06_id = d.cfg06_filial_id
        JOIN mcd01_mercadoria m ON m.mcd01_id = d.mcd01_mercadoria_id
        LEFT JOIN fis02_notafiscal_item ni ON ni.fis02_id = d.fis02_notafiscal_item_id
        LEFT JOIN fis01_notafiscal nf ON nf.fis01_id = ni.fis01_notafiscal_id
        WHERE (
            d.dia01_data_albaram BETWEEN %s AND %s
            OR d.dia01_data_nf BETWEEN %s AND %s
        )
          {loja_sql}
        ORDER BY f.cfg06_numero, d.dia01_data_albaram, d.dia01_albaram, m.mcd01_codint, d.dia01_id
        """,
        params,
    )

    params = [start_date, end_date, start_date, end_date]
    loja_mov_sql = loja_filter("f_mov", lojas, params)
    params.extend([start_date, end_date])
    loja_sql = loja_filter("f", lojas, params)
    result["inventarios"] = (
        f"""
        WITH ed_custo AS (
            SELECT
                mcd03_mercadoria_filial_id,
                est01_data,
                MAX(est01_vlr_custo_medio_fim_dia) AS custo_fim_dia
            FROM est01_estoque_diario
            WHERE est01_data BETWEEN %s AND %s
            GROUP BY mcd03_mercadoria_filial_id, est01_data
        ),
        inv_mov AS (
            SELECT
                ii_mov.est03_inventario_id AS inventario_id,
                MIN(e.est05_data) AS data_movimento
            FROM est05_estoque_movimento e
            JOIN est04_inventario_item ii_mov ON ii_mov.est04_id = e.est04_inventario_item_id
            JOIN mcd03_mercadoria_filial mf_mov ON mf_mov.mcd03_id = e.mcd03_mercadoria_filial_id
            JOIN cfg06_filial f_mov ON f_mov.cfg06_id = mf_mov.cfg06_filial_id
            WHERE e.est05_data BETWEEN %s AND %s
              {loja_mov_sql}
            GROUP BY ii_mov.est03_inventario_id
        )
        SELECT
            f.cfg06_numero AS loja,
            f.cfg06_nome AS nome_loja,
            i.est03_id AS inventario_id,
            i.est03_descricao AS descricao_inventario,
            COALESCE(DATE(i.est03_data_hora_fim), inv_mov.data_movimento, i.est03_data_criacao) AS data_inventario,
            i.est03_data_criacao AS data_criacao,
            i.est03_data_hora_inicio AS inicio,
            i.est03_data_hora_fim AS fim,
            i.est03_flgfechado AS fechado,
            i.est03_flgcancelado AS cancelado,
            COUNT(ii.est04_id) AS itens,
            ROUND(SUM(ii.est04_qtd_sistema), 3) AS qtd_sistema,
            ROUND(SUM(ii.est04_qtd_sistema * COALESCE(ed.custo_fim_dia, 0)), 2) AS valor_sistema_custo,
            ROUND(SUM(ii.est04_contagem_final), 3) AS qtd_contagem,
            ROUND(SUM(ii.est04_contagem_final * COALESCE(ed.custo_fim_dia, 0)), 2) AS valor_contagem_custo,
            ROUND(SUM(ii.est04_contagem_final - ii.est04_qtd_sistema), 3) AS diferenca_qtd,
            ROUND(SUM((ii.est04_contagem_final - ii.est04_qtd_sistema) * COALESCE(ed.custo_fim_dia, 0)), 2) AS diferenca_valor_custo
        FROM est03_inventario i
        JOIN cfg06_filial f ON f.cfg06_id = i.cfg06_filial_id
        LEFT JOIN inv_mov ON inv_mov.inventario_id = i.est03_id
        LEFT JOIN est04_inventario_item ii ON ii.est03_inventario_id = i.est03_id
        LEFT JOIN ed_custo ed
            ON ed.mcd03_mercadoria_filial_id = ii.mcd03_mercadoria_filial_id
           AND ed.est01_data = COALESCE(DATE(i.est03_data_hora_fim), inv_mov.data_movimento, i.est03_data_criacao)
        WHERE (COALESCE(DATE(i.est03_data_hora_fim), inv_mov.data_movimento, i.est03_data_criacao) BETWEEN %s AND %s
               OR inv_mov.inventario_id IS NOT NULL)
          {loja_sql}
        GROUP BY f.cfg06_numero, f.cfg06_nome, i.est03_id, i.est03_descricao, data_inventario, data_criacao,
                 i.est03_data_hora_inicio, i.est03_data_hora_fim, i.est03_flgfechado, i.est03_flgcancelado
        ORDER BY f.cfg06_numero, data_inventario, i.est03_id
        """,
        params,
    )

    params = [start_date, end_date, start_date, end_date]
    loja_mov_sql = loja_filter("f_mov", lojas, params)
    params.extend([start_date, end_date])
    loja_sql = loja_filter("f", lojas, params)
    result["inventario_itens"] = (
        f"""
        WITH ed_custo AS (
            SELECT
                mcd03_mercadoria_filial_id,
                est01_data,
                MAX(est01_vlr_custo_medio_fim_dia) AS custo_fim_dia
            FROM est01_estoque_diario
            WHERE est01_data BETWEEN %s AND %s
            GROUP BY mcd03_mercadoria_filial_id, est01_data
        ),
        item_mov AS (
            SELECT
                e.est04_inventario_item_id AS inventario_item_id,
                MIN(e.est05_data) AS data_movimento
            FROM est05_estoque_movimento e
            JOIN mcd03_mercadoria_filial mf_mov ON mf_mov.mcd03_id = e.mcd03_mercadoria_filial_id
            JOIN cfg06_filial f_mov ON f_mov.cfg06_id = mf_mov.cfg06_filial_id
            WHERE e.est05_data BETWEEN %s AND %s
              AND e.est04_inventario_item_id IS NOT NULL
              {loja_mov_sql}
            GROUP BY e.est04_inventario_item_id
        )
        SELECT
            f.cfg06_numero AS loja,
            f.cfg06_nome AS nome_loja,
            i.est03_id AS inventario_id,
            i.est03_descricao AS descricao_inventario,
            COALESCE(DATE(i.est03_data_hora_fim), item_mov.data_movimento, i.est03_data_criacao) AS data_inventario,
            i.est03_data_criacao AS data_criacao,
            i.est03_data_hora_inicio AS inicio,
            i.est03_data_hora_fim AS fim,
            i.est03_flgfechado AS fechado,
            i.est03_flgcancelado AS cancelado,
            m.mcd01_codint AS sku,
            LEFT(COALESCE(m.mcd01_descricao_curta, m.mcd01_descricao), 120) AS descricao,
            ROUND(COALESCE(ii.est04_qtd_sistema, 0), 3) AS qtd_sistema,
            ROUND(COALESCE(ii.est04_qtd_sistema, 0) * COALESCE(ed.custo_fim_dia, 0), 2) AS valor_sistema_custo,
            ROUND(COALESCE(ii.est04_contagem_final, 0), 3) AS qtd_contagem,
            ROUND(COALESCE(ii.est04_contagem_final, 0) * COALESCE(ed.custo_fim_dia, 0), 2) AS valor_contagem_custo,
            ROUND(COALESCE(ii.est04_contagem_final, 0) * COALESCE(ed.custo_fim_dia, 0), 2) AS valor_contado_custo,
            ROUND(COALESCE(ii.est04_contagem_final, 0) - COALESCE(ii.est04_qtd_sistema, 0), 3) AS diferenca_qtd,
            ROUND((COALESCE(ii.est04_contagem_final, 0) - COALESCE(ii.est04_qtd_sistema, 0)) * COALESCE(ed.custo_fim_dia, 0), 2) AS diferenca_valor_custo
        FROM est03_inventario i
        JOIN cfg06_filial f ON f.cfg06_id = i.cfg06_filial_id
        JOIN est04_inventario_item ii ON ii.est03_inventario_id = i.est03_id
        JOIN mcd03_mercadoria_filial mf ON mf.mcd03_id = ii.mcd03_mercadoria_filial_id
        JOIN mcd01_mercadoria m ON m.mcd01_id = mf.mcd01_mercadoria_id
        LEFT JOIN item_mov ON item_mov.inventario_item_id = ii.est04_id
        LEFT JOIN ed_custo ed
            ON ed.mcd03_mercadoria_filial_id = ii.mcd03_mercadoria_filial_id
           AND ed.est01_data = COALESCE(DATE(i.est03_data_hora_fim), item_mov.data_movimento, i.est03_data_criacao)
        WHERE (COALESCE(DATE(i.est03_data_hora_fim), item_mov.data_movimento, i.est03_data_criacao) BETWEEN %s AND %s
               OR item_mov.inventario_item_id IS NOT NULL)
          {loja_sql}
        ORDER BY f.cfg06_numero, data_inventario, i.est03_id, m.mcd01_codint
        """,
        params,
    )

    params = [start_date, end_date, start_date, end_date]
    loja_sql = loja_filter("f", lojas, params)
    result["conciliacao_sku"] = (
        f"""
        WITH {ed_custo_cte},
        mov AS (
            SELECT
                e.mcd03_mercadoria_filial_id,
                e.est05_data,
                ROUND(SUM({signed_qty}), 3) AS qtd_movimento_auditoria,
                ROUND(SUM({signed_value}), 2) AS valor_movimento_auditoria,
                ROUND(SUM(CASE WHEN {inventario_ja_no_inicio} THEN 0 ELSE {signed_qty} END), 3) AS qtd_movimento_conciliacao,
                ROUND(SUM(CASE WHEN {inventario_ja_no_inicio} THEN 0 ELSE {signed_value} END), 2) AS valor_movimento_conciliacao,
                ROUND(SUM(CASE WHEN {inventario_ja_no_inicio} THEN {signed_qty} ELSE 0 END), 3) AS qtd_inventario_ja_no_inicio,
                ROUND(SUM(CASE WHEN {inventario_ja_no_inicio} THEN {signed_value} ELSE 0 END), 2) AS valor_inventario_ja_no_inicio,
                ROUND(SUM(CASE WHEN e.fcx02_cupom_item_id IS NOT NULL THEN -{signed_qty} ELSE 0 END), 3) AS qtd_venda_mov,
                ROUND(SUM(CASE WHEN e.fcx02_cupom_item_id IS NOT NULL THEN -{signed_value} ELSE 0 END), 2) AS valor_venda_mov_custo,
                ROUND(SUM(CASE WHEN e.fis02_notafiscal_item_id IS NOT NULL AND nf.fis01_entrada_saida = 'E' THEN {signed_qty} ELSE 0 END), 3) AS qtd_nf_entrada_mov,
                ROUND(SUM(CASE WHEN e.fis02_notafiscal_item_id IS NOT NULL AND nf.fis01_entrada_saida = 'E' THEN {signed_value} ELSE 0 END), 2) AS valor_nf_entrada_mov,
                ROUND(SUM(CASE WHEN e.est04_inventario_item_id IS NOT NULL THEN {signed_qty} ELSE 0 END), 3) AS qtd_inventario_mov,
                ROUND(SUM(CASE WHEN e.est04_inventario_item_id IS NOT NULL THEN {signed_value} ELSE 0 END), 2) AS valor_inventario_mov,
                ROUND(SUM(CASE
                    WHEN e.est04_inventario_item_id IS NULL
                     AND e.fis02_notafiscal_item_id IS NULL
                     AND e.fcx02_cupom_item_id IS NULL
                     AND e.est02_boletim_consumo_producao_id IS NULL
                    THEN {signed_qty} ELSE 0 END), 3) AS qtd_sem_causa_mov
                ,
                ROUND(SUM(CASE
                    WHEN e.est04_inventario_item_id IS NULL
                     AND e.fis02_notafiscal_item_id IS NULL
                     AND e.fcx02_cupom_item_id IS NULL
                     AND e.est02_boletim_consumo_producao_id IS NULL
                    THEN {signed_value} ELSE 0 END), 2) AS valor_sem_causa_mov
            FROM est05_estoque_movimento e
            LEFT JOIN ed_custo ed
                ON ed.mcd03_mercadoria_filial_id = e.mcd03_mercadoria_filial_id
               AND ed.est01_data = e.est05_data
            LEFT JOIN est04_inventario_item ii ON ii.est04_id = e.est04_inventario_item_id
            LEFT JOIN fis02_notafiscal_item ni ON ni.fis02_id = e.fis02_notafiscal_item_id
            LEFT JOIN fis01_notafiscal nf ON nf.fis01_id = ni.fis01_notafiscal_id
            LEFT JOIN fcx02_cupom_item ci ON ci.fcx02_id = e.fcx02_cupom_item_id
            LEFT JOIN est02_boletim_consumo_producao b ON b.est02_id = e.est02_boletim_consumo_producao_id
            WHERE e.est05_data BETWEEN %s AND %s
            GROUP BY e.mcd03_mercadoria_filial_id, e.est05_data
        ),
        venda AS (
            SELECT
                mf.mcd03_id AS mcd03_mercadoria_filial_id,
                c.fcx01_data,
                ROUND(SUM(i.fcx02_qtd), 3) AS qtd_vendida_cupom,
                ROUND(SUM(i.fcx02_vlrtot), 2) AS valor_vendido_cupom
            FROM fcx02_cupom_item i
            JOIN fcx01_cupom c ON c.fcx01_id = i.fcx01_cupom_id
            JOIN mcd03_mercadoria_filial mf
              ON mf.mcd01_mercadoria_id = i.mcd01_mercadoria_id
             AND mf.cfg06_filial_id = c.cfg06_filial_id
            WHERE c.fcx01_data BETWEEN %s AND %s
              AND IFNULL(c.fcx01_flgestornado, 0) = 0
              AND IFNULL(c.fcx01_cupom_id_cancelado, 0) = 0
              AND IFNULL(i.fcx02_flgestornado, 0) = 0
            GROUP BY mf.mcd03_id, c.fcx01_data
        ),
        previous_stock AS (
            SELECT *
            FROM est01_estoque_diario
            WHERE est01_data = '{previous_start_date}'
        ),
        base AS (
            SELECT DISTINCT mcd03_mercadoria_filial_id, dom18_finalidadenf_id
            FROM est01_estoque_diario
            WHERE est01_data BETWEEN '{start_date}' AND '{end_date}'
            UNION
            SELECT DISTINCT mcd03_mercadoria_filial_id, dom18_finalidadenf_id
            FROM previous_stock
        )
        SELECT
            f.cfg06_numero AS loja,
            f.cfg06_nome AS nome_loja,
            '{start_date}' AS data_movimento,
            m.mcd01_codint AS sku,
            base.dom18_finalidadenf_id AS finalidade_estoque,
            LEFT(COALESCE(m.mcd01_descricao_curta, m.mcd01_descricao), 120) AS descricao,
            ROUND(COALESCE(prev.est01_qtd_fim_dia, ed.est01_qtd_inicio_dia, 0), 3) AS qtd_inicio,
            ROUND(COALESCE(prev.est01_qtd_fim_dia, ed.est01_qtd_inicio_dia, 0) *
                  COALESCE(prev.est01_vlr_custo_medio_fim_dia, ed.est01_vlr_custo_medio_inicio_dia, 0), 2) AS valor_inicio_custo,
            ROUND(COALESCE(mov.qtd_movimento_auditoria, 0), 3) AS qtd_movimento_auditoria,
            ROUND(COALESCE(mov.valor_movimento_auditoria, 0), 2) AS valor_movimento_auditoria,
            ROUND(COALESCE(mov.qtd_inventario_ja_no_inicio, 0), 3) AS qtd_inventario_ja_no_inicio,
            ROUND(COALESCE(mov.valor_inventario_ja_no_inicio, 0), 2) AS valor_inventario_ja_no_inicio,
            ROUND(COALESCE(mov.qtd_movimento_conciliacao, 0), 3) AS qtd_movimento,
            ROUND(COALESCE(mov.valor_movimento_conciliacao, 0), 2) AS valor_movimento_custo,
            ROUND(COALESCE(prev.est01_qtd_fim_dia, ed.est01_qtd_inicio_dia, 0) + COALESCE(mov.qtd_movimento_conciliacao, 0), 3) AS qtd_fim_esperado,
            ROUND((COALESCE(prev.est01_qtd_fim_dia, ed.est01_qtd_inicio_dia, 0) *
                   COALESCE(prev.est01_vlr_custo_medio_fim_dia, ed.est01_vlr_custo_medio_inicio_dia, 0)) +
                  COALESCE(mov.valor_movimento_conciliacao, 0), 2) AS valor_fim_esperado_custo,
            ROUND(COALESCE(ed.est01_qtd_fim_dia, prev.est01_qtd_fim_dia, 0), 3) AS qtd_fim_pleno,
            ROUND(COALESCE(ed.est01_qtd_fim_dia, prev.est01_qtd_fim_dia, 0) *
                  COALESCE(ed.est01_vlr_custo_medio_fim_dia, prev.est01_vlr_custo_medio_fim_dia, 0), 2) AS valor_fim_pleno_custo,
            ROUND(COALESCE(ed.est01_qtd_fim_dia, prev.est01_qtd_fim_dia, 0) -
                  (COALESCE(prev.est01_qtd_fim_dia, ed.est01_qtd_inicio_dia, 0) + COALESCE(mov.qtd_movimento_conciliacao, 0)), 3) AS divergencia_qtd,
            ROUND(COALESCE(venda.qtd_vendida_cupom, 0), 3) AS qtd_vendida_cupom,
            ROUND(COALESCE(venda.valor_vendido_cupom, 0), 2) AS valor_vendido_cupom,
            ROUND(COALESCE(mov.qtd_venda_mov, 0), 3) AS qtd_venda_movimento,
            ROUND(COALESCE(mov.valor_venda_mov_custo, 0), 2) AS valor_venda_movimento_custo,
            ROUND(COALESCE(mov.qtd_nf_entrada_mov, 0), 3) AS qtd_nf_entrada_movimento,
            ROUND(COALESCE(mov.valor_nf_entrada_mov, 0), 2) AS valor_nf_entrada_movimento,
            ROUND(COALESCE(mov.qtd_inventario_mov, 0), 3) AS qtd_inventario_movimento,
            ROUND(COALESCE(mov.valor_inventario_mov, 0), 2) AS valor_inventario_movimento,
            ROUND(COALESCE(mov.qtd_sem_causa_mov, 0), 3) AS qtd_sem_causa_movimento,
            ROUND(COALESCE(mov.valor_sem_causa_mov, 0), 2) AS valor_sem_causa_movimento,
            ROUND((COALESCE(ed.est01_qtd_fim_dia, prev.est01_qtd_fim_dia, 0) -
                   (COALESCE(prev.est01_qtd_fim_dia, ed.est01_qtd_inicio_dia, 0) + COALESCE(mov.qtd_movimento_conciliacao, 0))) *
                  COALESCE(ed.est01_vlr_custo_medio_fim_dia, prev.est01_vlr_custo_medio_fim_dia, 0), 2) AS divergencia_valor_custo
        FROM base
        JOIN mcd03_mercadoria_filial mf ON mf.mcd03_id = base.mcd03_mercadoria_filial_id
        JOIN cfg06_filial f ON f.cfg06_id = mf.cfg06_filial_id
        JOIN mcd01_mercadoria m ON m.mcd01_id = mf.mcd01_mercadoria_id
        LEFT JOIN est01_estoque_diario ed
          ON ed.mcd03_mercadoria_filial_id = base.mcd03_mercadoria_filial_id
         AND ed.dom18_finalidadenf_id = base.dom18_finalidadenf_id
         AND ed.est01_data BETWEEN '{start_date}' AND '{end_date}'
        LEFT JOIN previous_stock prev
          ON prev.mcd03_mercadoria_filial_id = base.mcd03_mercadoria_filial_id
         AND prev.dom18_finalidadenf_id = base.dom18_finalidadenf_id
        LEFT JOIN mov
          ON mov.mcd03_mercadoria_filial_id = base.mcd03_mercadoria_filial_id
         AND mov.est05_data BETWEEN '{start_date}' AND '{end_date}'
        LEFT JOIN venda
          ON venda.mcd03_mercadoria_filial_id = base.mcd03_mercadoria_filial_id
         AND venda.fcx01_data BETWEEN '{start_date}' AND '{end_date}'
        WHERE 1 = 1
          {loja_sql}
        ORDER BY ABS((COALESCE(ed.est01_qtd_fim_dia, prev.est01_qtd_fim_dia, 0) -
                      (COALESCE(prev.est01_qtd_fim_dia, ed.est01_qtd_inicio_dia, 0) + COALESCE(mov.qtd_movimento_conciliacao, 0))) *
                     COALESCE(ed.est01_vlr_custo_medio_fim_dia, prev.est01_vlr_custo_medio_fim_dia, 0)) DESC,
                 f.cfg06_numero, data_movimento, m.mcd01_codint
        """,
        params,
    )

    params = [start_date, end_date]
    loja_sql = loja_filter("f", lojas, params)
    result["top_movimentos"] = (
        f"""
        WITH {ed_custo_cte}
        SELECT
            f.cfg06_numero AS loja,
            f.cfg06_nome AS nome_loja,
            e.est05_data AS data_movimento,
            m.mcd01_codint AS sku,
            LEFT(COALESCE(m.mcd01_descricao_curta, m.mcd01_descricao), 120) AS descricao,
            {origem} AS origem,
            ROUND(SUM({signed_qty}), 3) AS qtd_movimento,
            ROUND(SUM({signed_value}), 2) AS valor_movimento_custo,
            COUNT(*) AS linhas
        FROM est05_estoque_movimento e
        JOIN mcd03_mercadoria_filial mf ON mf.mcd03_id = e.mcd03_mercadoria_filial_id
        JOIN cfg06_filial f ON f.cfg06_id = mf.cfg06_filial_id
        JOIN mcd01_mercadoria m ON m.mcd01_id = mf.mcd01_mercadoria_id
        LEFT JOIN ed_custo ed
            ON ed.mcd03_mercadoria_filial_id = e.mcd03_mercadoria_filial_id
           AND ed.est01_data = e.est05_data
        LEFT JOIN est04_inventario_item ii ON ii.est04_id = e.est04_inventario_item_id
        LEFT JOIN fis02_notafiscal_item ni ON ni.fis02_id = e.fis02_notafiscal_item_id
        LEFT JOIN fis01_notafiscal nf ON nf.fis01_id = ni.fis01_notafiscal_id
        LEFT JOIN fcx02_cupom_item ci ON ci.fcx02_id = e.fcx02_cupom_item_id
        LEFT JOIN est02_boletim_consumo_producao b ON b.est02_id = e.est02_boletim_consumo_producao_id
        WHERE e.est05_data BETWEEN %s AND %s
          {loja_sql}
        GROUP BY f.cfg06_numero, f.cfg06_nome, e.est05_data, m.mcd01_codint, descricao, origem
        ORDER BY ABS(SUM({signed_value})) DESC
        LIMIT {int(limit_top)}
        """,
        params,
    )

    return result


def main() -> None:
    args = parse_args()
    import pymysql

    start_date, end_date = resolve_period(args)
    lojas = parse_lojas(args.lojas)
    env = load_env()
    stamp = start_date if start_date == end_date else f"{start_date}_a_{end_date}"
    if args.all_lojas:
        stamp = f"{stamp}_lojas_todas"
    elif lojas:
        stamp = f"{stamp}_lojas_{'-'.join(map(str, lojas))}"
    out_dir = args.out_dir / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = pymysql.connect(
        host=env["MYSQL_HOST"],
        port=int(env["MYSQL_PORT"]),
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        database=env["MYSQL_DATABASE"],
        charset="latin1",
        cursorclass=pymysql.cursors.DictCursor,
    )

    manifest: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "start_date": start_date,
        "end_date": end_date,
        "lojas": lojas or "todas",
        "files": {},
    }

    try:
        for name, (sql, params) in queries(start_date, end_date, lojas, args.limit_top).items():
            data = fetch_all(conn, sql, params)
            path = out_dir / f"{name}.csv"
            write_csv(path, data)
            manifest["files"][name] = {"path": str(path), "rows": len(data)}
            print(f"{name}: {len(data)} linha(s)")
    finally:
        conn.close()

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifest: {manifest_path}")


if __name__ == "__main__":
    main()
