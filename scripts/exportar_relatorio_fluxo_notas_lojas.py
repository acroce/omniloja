#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".python_packages"))

DEFAULT_START_DATE = "2026-08-01"
DEFAULT_ORIGIN_STORE = 704
DEFAULT_OUTPUT = ROOT / "outputs" / "pleno_fluxo_notas_lojas" / "fluxo_notas_lojas.json"


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
    env: dict[str, str] = {}
    env.update(load_env_file(ROOT / ".env"))
    env.update(os.environ)
    return env


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def to_float(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def to_int(value: Any) -> int:
    if value is None:
        return 0
    return int(value)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")


def main() -> None:
    env = load_env()
    start_date = env.get("RELATORIO_FLUXO_NOTAS_START_DATE") or DEFAULT_START_DATE
    cd_store = int(env.get("RELATORIO_FLUXO_NOTAS_CD") or DEFAULT_ORIGIN_STORE)
    output = Path(env.get("RELATORIO_FLUXO_NOTAS_OUTPUT") or DEFAULT_OUTPUT)

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

    sql = """
        SELECT
            nf.fis01_id AS id_pleno,
            nf.fis01_nronf AS nota,
            nf.fis01_serienf AS serie,
            nf.fis01_entrada_saida AS entrada_saida_tipo,
            nf.fis01_data_emissao AS emissao,
            nf.fis01_data_entrada_saida AS data_entrada_saida,
            nf.fis01_hora_entrada_saida AS hora_entrada_saida,
            COALESCE(nf.fis01_flgcancelada, 0) AS cancelada,
            nf.fis01_nfe_cstat AS nfe_status,
            nf.fis01_nfe_xmotivo AS nfe_motivo,
            nf.adm05_usuario_checkin_id AS usuario_checkin_id,
            uc.adm05_usuario AS usuario_checkin,
            uc.adm05_nome_apresentacao AS nome_checkin,
            COALESCE(MIN(f_origem.cfg06_numero), 0) AS loja_origem,
            COALESCE(MIN(f_origem.cfg06_nome), '') AS nome_origem,
            COALESCE(MIN(f_destino.cfg06_numero), 0) AS loja_destino,
            COALESCE(MIN(f_destino.cfg06_nome), '') AS nome_destino,
            COUNT(DISTINCT ni.fis02_id) AS itens,
            ROUND(SUM(COALESCE(ni.fis02_qtd, 0)), 3) AS qtd,
            ROUND(SUM(COALESCE(ni.fis02_qtd, 0) * COALESCE(NULLIF(ni.fis02_vlrunit_liquido, 0), ni.fis02_vlrunit, 0)), 2) AS valor
        FROM fis01_notafiscal nf
        JOIN fis02_notafiscal_item ni
            ON ni.fis01_notafiscal_id = nf.fis01_id
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
        LEFT JOIN adm05_usuario uc
            ON uc.adm05_id = nf.adm05_usuario_checkin_id
        WHERE COALESCE(nf.fis01_flgcancelada, 0) = 0
          AND (
              nf.fis01_data_emissao >= %s
              OR nf.fis01_data_entrada_saida >= %s
          )
          AND f_origem.cfg06_numero IS NOT NULL
          AND f_destino.cfg06_numero IS NOT NULL
          AND (
              (f_origem.cfg06_numero = %s AND f_destino.cfg06_numero <> %s)
              OR (f_destino.cfg06_numero = %s AND f_origem.cfg06_numero <> %s)
              OR (f_origem.cfg06_numero = f_destino.cfg06_numero AND f_origem.cfg06_numero <> %s)
          )
        GROUP BY
            nf.fis01_id,
            nf.fis01_nronf,
            nf.fis01_serienf,
            nf.fis01_entrada_saida,
            nf.fis01_data_emissao,
            nf.fis01_data_entrada_saida,
            nf.fis01_hora_entrada_saida,
            nf.fis01_flgcancelada,
            nf.fis01_nfe_cstat,
            nf.fis01_nfe_xmotivo,
            nf.adm05_usuario_checkin_id,
            uc.adm05_usuario,
            uc.adm05_nome_apresentacao
        ORDER BY loja_origem, loja_destino, nf.fis01_data_emissao, nf.fis01_nronf
    """

    params = (start_date, start_date, cd_store, cd_store, cd_store, cd_store, cd_store)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = list(cur.fetchall())
    finally:
        conn.close()

    details: list[dict[str, Any]] = []
    summary: dict[tuple[Any, ...], dict[str, Any]] = {}
    by_store: dict[tuple[Any, ...], dict[str, Any]] = {}

    for row in rows:
        origem = to_int(row["loja_origem"])
        destino = to_int(row["loja_destino"])
        if origem == cd_store and destino != cd_store:
            fluxo = f"CD {cd_store} -> Loja"
            loja_ref = destino
            nome_loja_ref = row["nome_destino"]
        elif destino == cd_store and origem != cd_store:
            fluxo = f"Loja -> CD {cd_store}"
            loja_ref = origem
            nome_loja_ref = row["nome_origem"]
        elif origem == destino and origem != cd_store:
            fluxo = "Loja -> mesma loja"
            loja_ref = origem
            nome_loja_ref = row["nome_origem"]
        else:
            fluxo = "Outro"
            loja_ref = destino or origem
            nome_loja_ref = row["nome_destino"] or row["nome_origem"]

        status_confirmacao = "CONFIRMADA" if row["usuario_checkin_id"] is not None else "PENDENTE_CONFIRMAR"
        detail = {
            "fluxo": fluxo,
            "status_confirmacao": status_confirmacao,
            "loja_ref": loja_ref,
            "nome_loja_ref": nome_loja_ref,
            "loja_origem": origem,
            "nome_origem": row["nome_origem"],
            "loja_destino": destino,
            "nome_destino": row["nome_destino"],
            "nota": row["nota"],
            "serie": row["serie"],
            "tipo_nf": row["entrada_saida_tipo"],
            "emissao": row["emissao"],
            "data_entrada_saida": row["data_entrada_saida"],
            "hora_entrada_saida": row["hora_entrada_saida"],
            "itens": to_int(row["itens"]),
            "qtd": to_float(row["qtd"]),
            "valor": to_float(row["valor"]),
            "nfe_status": row["nfe_status"],
            "nfe_motivo": row["nfe_motivo"],
            "usuario_checkin": row["usuario_checkin"],
            "nome_checkin": row["nome_checkin"],
            "id_pleno": row["id_pleno"],
        }
        details.append(detail)

        key = (fluxo, status_confirmacao)
        if key not in summary:
            summary[key] = {
                "fluxo": fluxo,
                "status_confirmacao": status_confirmacao,
                "notas": 0,
                "itens": 0,
                "qtd": 0.0,
                "valor": 0.0,
                "lojas": set(),
            }
        summary[key]["notas"] += 1
        summary[key]["itens"] += detail["itens"]
        summary[key]["qtd"] += detail["qtd"]
        summary[key]["valor"] += detail["valor"]
        summary[key]["lojas"].add(loja_ref)

        store_key = (loja_ref, nome_loja_ref, fluxo)
        if store_key not in by_store:
            by_store[store_key] = {
                "loja": loja_ref,
                "nome_loja": nome_loja_ref,
                "fluxo": fluxo,
                "confirmadas": 0,
                "pendentes": 0,
                "total": 0,
                "valor": 0.0,
            }
        by_store[store_key]["total"] += 1
        by_store[store_key]["valor"] += detail["valor"]
        if status_confirmacao == "CONFIRMADA":
            by_store[store_key]["confirmadas"] += 1
        else:
            by_store[store_key]["pendentes"] += 1

    summary_rows = []
    for item in summary.values():
        summary_rows.append({
            "fluxo": item["fluxo"],
            "status_confirmacao": item["status_confirmacao"],
            "lojas": len(item["lojas"]),
            "notas": item["notas"],
            "itens": item["itens"],
            "qtd": round(item["qtd"], 3),
            "valor": round(item["valor"], 2),
        })
    summary_rows.sort(key=lambda row: (row["fluxo"], row["status_confirmacao"]))

    by_store_rows = list(by_store.values())
    by_store_rows.sort(key=lambda row: (row["fluxo"], -row["pendentes"], -row["total"], row["loja"]))

    data = {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "startDate": start_date,
        "endDate": date.today().isoformat(),
        "cdStore": cd_store,
        "source": f"{env['MYSQL_USER']}@{env['MYSQL_HOST']}:{env.get('MYSQL_PORT', '3306')}/{env['MYSQL_DATABASE']}",
        "rules": [
            "Inclui notas nao canceladas no Pleno com data de emissao ou entrada/saida desde a data inicial.",
            "CONFIRMADA = nota com adm05_usuario_checkin_id preenchido.",
            "PENDENTE_CONFIRMAR = nota sem usuario de check-in.",
            "Faltas de emissao so podem ser apuradas com uma base esperada de notas/pedidos; este relatorio lista notas existentes no Pleno.",
        ],
        "summary": summary_rows,
        "byStore": by_store_rows,
        "details": details,
    }
    write_json(output, data)
    print(f"Relatorio JSON gerado: {output}")
    print(f"detalhes={len(details)} resumo={len(summary_rows)} lojas_fluxo={len(by_store_rows)}")


if __name__ == "__main__":
    main()
