#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".python_packages"))


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


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def valid_date(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or ""):
        raise argparse.ArgumentTypeError("Use data no formato YYYY-MM-DD.")
    datetime.strptime(value, "%Y-%m-%d")
    return value


def parse_lojas(value: str | None) -> list[int]:
    if not value:
        return []
    lojas: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if not item.isdigit():
            raise argparse.ArgumentTypeError("Informe lojas separadas por virgula.")
        lojas.append(int(item))
    return sorted(set(lojas))


def number(value: Any) -> float:
    if value is None:
        return 0
    return float(value)


def int_number(value: Any) -> int:
    if value is None:
        return 0
    return int(value)


def connect(env: dict[str, str]):
    import pymysql

    required = ["MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"]
    missing = [key for key in required if not env.get(key)]
    if missing:
        raise SystemExit(f"Variaveis MySQL ausentes: {', '.join(missing)}")
    return pymysql.connect(
        host=env["MYSQL_HOST"],
        port=int(env.get("MYSQL_PORT", "3306")),
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        database=env["MYSQL_DATABASE"],
        charset="latin1",
        cursorclass=pymysql.cursors.DictCursor,
    )


def query_monitor(start_date: str, end_date: str, lojas_filter: list[int], include_inactive: bool) -> dict[str, Any]:
    env = load_env()
    store_params = lojas_filter[:]
    loja_sql = ""
    if lojas_filter:
        loja_sql = " AND cfg06_numero IN (" + ",".join(["%s"] * len(lojas_filter)) + ")"
    active_sql = "" if include_inactive else " AND COALESCE(cfg06_situacao, 'A') = 'A'"

    inv_loja_sql = ""
    inv_params: list[Any] = [start_date, end_date]
    if lojas_filter:
        inv_loja_sql = " AND f.cfg06_numero IN (" + ",".join(["%s"] * len(lojas_filter)) + ")"
        inv_params.extend(lojas_filter)

    with connect(env) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    cfg06_id AS filial_id,
                    cfg06_numero AS loja,
                    cfg06_nome AS nome_loja,
                    cfg06_situacao AS situacao
                FROM cfg06_filial
                WHERE cfg06_numero IS NOT NULL
                  AND cfg06_numero > 0
                  {active_sql}
                  {loja_sql}
                ORDER BY cfg06_numero
                """,
                store_params,
            )
            lojas = list(cur.fetchall())

            cur.execute(
                f"""
                SELECT
                    f.cfg06_numero AS loja,
                    f.cfg06_nome AS nome_loja,
                    i.est03_id AS inventario_id,
                    i.est03_descricao AS descricao,
                    COALESCE(DATE(i.est03_data_hora_fim), DATE(i.est03_data_hora_inicio), DATE(i.est03_data_criacao)) AS data_contagem,
                    i.est03_data_criacao AS data_criacao,
                    i.est03_data_hora_inicio AS inicio,
                    i.est03_data_hora_fim AS fim,
                    COALESCE(i.est03_flgfechado, 0) AS fechado,
                    COALESCE(i.est03_flgcancelado, 0) AS cancelado,
                    COUNT(ii.est04_id) AS itens,
                    COALESCE(SUM(ii.est04_qtd_sistema), 0) AS qtd_sistema,
                    COALESCE(SUM(ii.est04_contagem_final), 0) AS qtd_contagem,
                    COALESCE(SUM(ii.est04_contagem_final - ii.est04_qtd_sistema), 0) AS diferenca_qtd
                FROM est03_inventario i
                JOIN cfg06_filial f ON f.cfg06_id = i.cfg06_filial_id
                LEFT JOIN est04_inventario_item ii ON ii.est03_inventario_id = i.est03_id
                WHERE COALESCE(DATE(i.est03_data_hora_fim), DATE(i.est03_data_hora_inicio), DATE(i.est03_data_criacao)) BETWEEN %s AND %s
                  {inv_loja_sql}
                GROUP BY
                    f.cfg06_numero,
                    f.cfg06_nome,
                    i.est03_id,
                    i.est03_descricao,
                    data_contagem,
                    i.est03_data_criacao,
                    i.est03_data_hora_inicio,
                    i.est03_data_hora_fim,
                    i.est03_flgfechado,
                    i.est03_flgcancelado
                ORDER BY f.cfg06_numero, data_contagem, i.est03_id
                """,
                inv_params,
            )
            inventarios = list(cur.fetchall())

    by_store: dict[int, dict[str, Any]] = {}
    for row in inventarios:
        loja = int(row["loja"])
        current = by_store.setdefault(
            loja,
            {
                "loja": row["loja"],
                "nome_loja": row["nome_loja"],
                "inventarios": 0,
                "inventariosValidos": 0,
                "inventariosCancelados": 0,
                "inventariosFechados": 0,
                "itens": 0,
                "qtdSistema": 0.0,
                "qtdContagem": 0.0,
                "diferencaQtd": 0.0,
                "primeiraContagem": "",
                "ultimaContagem": "",
                "inventarioIds": [],
            },
        )
        cancelado = int_number(row.get("cancelado")) == 1
        current["inventarios"] += 1
        current["inventariosValidos"] += 0 if cancelado else 1
        current["inventariosCancelados"] += 1 if cancelado else 0
        current["inventariosFechados"] += 1 if int_number(row.get("fechado")) == 1 else 0
        current["itens"] += int_number(row.get("itens"))
        current["qtdSistema"] += number(row.get("qtd_sistema"))
        current["qtdContagem"] += number(row.get("qtd_contagem"))
        current["diferencaQtd"] += number(row.get("diferenca_qtd"))
        data_contagem = str(row.get("data_contagem") or "")
        current["primeiraContagem"] = min(filter(None, [current["primeiraContagem"], data_contagem]), default="")
        current["ultimaContagem"] = max(filter(None, [current["ultimaContagem"], data_contagem]), default="")
        current["inventarioIds"].append(row["inventario_id"])

    stores_status: list[dict[str, Any]] = []
    for loja in lojas:
        summary = by_store.get(int(loja["loja"]))
        if not summary:
            summary = {
                "loja": loja["loja"],
                "nome_loja": loja["nome_loja"],
                "inventarios": 0,
                "inventariosValidos": 0,
                "inventariosCancelados": 0,
                "inventariosFechados": 0,
                "itens": 0,
                "qtdSistema": 0,
                "qtdContagem": 0,
                "diferencaQtd": 0,
                "primeiraContagem": "",
                "ultimaContagem": "",
                "inventarioIds": [],
            }
        status = "COM_CONTAGEM" if summary["inventariosValidos"] > 0 else "SOMENTE_CANCELADO" if summary["inventarios"] > 0 else "SEM_CONTAGEM"
        stores_status.append({**summary, "situacao": loja.get("situacao"), "status": status})

    counted = [row for row in stores_status if row["status"] == "COM_CONTAGEM"]
    missing = [row for row in stores_status if row["status"] == "SEM_CONTAGEM"]
    canceled_only = [row for row in stores_status if row["status"] == "SOMENTE_CANCELADO"]
    return {
        "process": "inventario-contagem",
        "title": "Monitor Inventario/Contagem",
        "now": iso_now(),
        "updatedAt": iso_now(),
        "startDate": start_date,
        "endDate": end_date,
        "onlyActive": not include_inactive,
        "storeFilter": lojas_filter,
        "source": f"{env['MYSQL_USER']}@{env['MYSQL_HOST']}:{env.get('MYSQL_PORT', '3306')}/{env['MYSQL_DATABASE']}",
        "totals": {
            "lojas": len(stores_status),
            "comContagem": len(counted),
            "semContagem": len(missing),
            "somenteCancelado": len(canceled_only),
            "inventarios": len(inventarios),
            "inventariosValidos": sum(int(row["inventariosValidos"]) for row in counted),
            "itens": sum(int(row["itens"]) for row in counted),
            "doneRate": round(len(counted) / len(stores_status) * 100, 2) if stores_status else 0,
        },
        "stores": stores_status,
        "countedStores": counted,
        "missingStores": missing,
        "canceledOnlyStores": canceled_only,
        "inventories": inventarios,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Consulta lojas com/sem inventario no Pleno.")
    parser.add_argument("--start-date", type=valid_date, required=True)
    parser.add_argument("--end-date", type=valid_date, required=True)
    parser.add_argument("--lojas", default="")
    parser.add_argument("--include-inactive", action="store_true")
    args = parser.parse_args()
    start_date, end_date = sorted([args.start_date, args.end_date])
    lojas = parse_lojas(args.lojas)
    print(json.dumps(query_monitor(start_date, end_date, lojas, args.include_inactive), ensure_ascii=False, default=json_default))


if __name__ == "__main__":
    main()
