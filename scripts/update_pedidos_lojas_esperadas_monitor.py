#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import argparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".python_packages"))

DEFAULT_STATUS = ROOT / "outputs" / "pleno_business_monitor" / "pedidos.json"


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


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return str(value)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {"collector": "pedidos-monitor", "events": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")
    tmp.replace(path)


def parse_int_list(value: str, default: list[int]) -> list[int]:
    result = []
    for item in str(value or "").split(","):
        item = item.strip()
        if item.isdigit():
            result.append(int(item))
    return result or default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Atualiza lojas esperadas de pedidos no Pleno.")
    parser.add_argument("--status-file", type=Path, default=DEFAULT_STATUS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    env = load_env()
    status_file = Path(env.get("PEDIDOS_MONITOR_STATUS_FILE") or args.status_file)
    tipos_esperados = parse_int_list(env.get("PEDIDOS_DIAFLEX_TIPOS", env.get("PEDIDOS_EXPECTED_TIPOS", "3")), [3])
    max_store = int(env.get("PEDIDOS_MAX_STORE_NUMBER", "2999") or "2999")
    placeholders = ", ".join(["%s"] * len(tipos_esperados))

    import pymysql

    conn = pymysql.connect(
        host=env["MYSQL_HOST"],
        port=int(env["MYSQL_PORT"]),
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        database=env["MYSQL_DATABASE"],
        charset="latin1",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    f.cfg06_numero AS loja,
                    MIN(f.cfg06_nome) AS nome_loja,
                    COUNT(DISTINCT p.com16_id) AS registros,
                    COALESCE(SUM(item_stats.itens), 0) AS itens,
                    COALESCE(SUM(item_stats.qtd_confirmada_preenchida), 0) AS itens_confirmados,
                    COUNT(DISTINCT CASE
                        WHEN item_stats.itens > 0
                         AND item_stats.qtd_confirmada_preenchida >= item_stats.itens
                        THEN p.com16_id
                    END) AS pedidos_confirmados,
                    COUNT(DISTINCT CASE
                        WHEN p.com16_flgrevisado = 1
                         AND p.com16_dthr_cancelado IS NULL
                        THEN p.com16_id
                    END) AS pedidos_concluidos,
                    COUNT(DISTINCT CASE WHEN p.com16_dthr_cancelado IS NOT NULL THEN p.com16_id END) AS pedidos_cancelados,
                    COUNT(DISTINCT CASE WHEN p.com16_dthr_exportado_trd IS NOT NULL THEN p.com16_id END) AS pedidos_exportados,
                    MIN(CASE WHEN p.com16_dthr_exportado_trd IS NOT NULL THEN p.com16_dthr_exportado_trd END) AS primeira_exportacao,
                    MAX(p.com16_dthr_exportado_trd) AS ultima_exportacao,
                    GROUP_CONCAT(DISTINCT p.dom83_tipo_pedtransf_id ORDER BY p.dom83_tipo_pedtransf_id SEPARATOR ',') AS tipos
                FROM pleno.com16_pretransferencia p
                INNER JOIN pleno.cfg06_filial f
                    ON f.cfg06_id = p.cfg06_filial_dest_id
                LEFT JOIN (
                    SELECT
                        com16_pretransferencia_id,
                        COUNT(*) AS itens,
                        SUM(CASE WHEN com19_qtd_confirmada IS NOT NULL THEN 1 ELSE 0 END) AS qtd_confirmada_preenchida
                    FROM pleno.com19_pretransferencia_item
                    GROUP BY com16_pretransferencia_id
                ) item_stats
                    ON item_stats.com16_pretransferencia_id = p.com16_id
                WHERE p.com16_dthr >= CURDATE()
                  AND p.com16_dthr < CURDATE() + INTERVAL 1 DAY
                  AND f.cfg06_numero > 0
                  AND f.cfg06_numero <= %s
                  AND p.dom83_tipo_pedtransf_id IN ({placeholders})
                GROUP BY f.cfg06_numero
                ORDER BY f.cfg06_numero
                """,
                [max_store, *tipos_esperados],
            )
            rows = list(cur.fetchall())
    finally:
        conn.close()

    expected = sorted(int(row["loja"]) for row in rows if row.get("loja") is not None)
    confirmed = sorted(
        int(row["loja"])
        for row in rows
        if row.get("loja") is not None
        and int(row.get("pedidos_confirmados") or 0) > 0
    )
    concluded = sorted(
        int(row["loja"])
        for row in rows
        if row.get("loja") is not None
        and int(row.get("pedidos_concluidos") or 0) > 0
    )
    exported = sorted(int(row["loja"]) for row in rows if int(row.get("pedidos_exportados") or 0) > 0)
    cancelled = sorted(int(row["loja"]) for row in rows if int(row.get("pedidos_cancelados") or 0) > 0)
    pending = sorted(set(expected) - set(concluded))
    first_times = [row.get("primeira_exportacao") for row in rows if row.get("primeira_exportacao")]
    last_times = [row.get("ultima_exportacao") for row in rows if row.get("ultima_exportacao")]
    first_time = min(first_times) if first_times else None
    last_time = max(last_times) if last_times else None
    now = iso_now()
    total = len(expected)
    done = len(concluded)
    total_items = sum(int(row.get("itens") or 0) for row in rows)
    confirmed_items = sum(int(row.get("itens_confirmados") or 0) for row in rows)
    details = (
        f"Fluxo Diaflex pedidos hoje: {done}/{total} loja(s) concluida(s). "
        f"Itens confirmados: {confirmed_items}/{total_items}. "
        f"Lojas com itens confirmados: {len(confirmed)}/{total}. "
        f"Exportadas AS400: {len(exported)}/{total}. "
        f"Tipos considerados: {','.join(str(item) for item in tipos_esperados)}. "
        "Concluida conforme a situacao do Pleno: pelo menos um pedido da loja foi revisado e nao foi cancelado."
    )
    if pending:
        details += " Pendentes: " + ", ".join(str(item) for item in pending[:30])
        if len(pending) > 30:
            details += f" (+{len(pending) - 30})"
        details += "."
    if cancelled:
        details += " Canceladas: " + ", ".join(str(item) for item in cancelled[:30])
        if len(cancelled) > 30:
            details += f" (+{len(cancelled) - 30})"
        details += "."
    status = "ok" if total and not pending else "warning" if total else "aguardando"

    data = load_json(status_file)
    data["collector"] = "pedidos-monitor"
    data["updatedAt"] = now
    data.setdefault("events", {})
    data["events"]["lojas_diaflex"] = {
        "targetTime": "09:30",
        "status": status,
        "actualAt": now if total and not pending else "",
        "count": done,
        "source": "pleno.com16_pretransferencia.com16_flgrevisado (nao cancelado)",
        "details": details,
        "pedidosArquivo": total,
        "pedidosImportados": done,
        "lojasEsperadas": total,
        "lojasPleno": done,
        "lojasConcluidas": done,
        "lojasExportadas": len(exported),
        "lojasNumerosEsperadas": expected,
        "lojasNumerosConfirmadas": confirmed,
        "lojasNumerosPleno": concluded,
        "lojasNumerosConcluidas": concluded,
        "lojasNumerosExportadas": exported,
        "lojasNumerosCanceladas": cancelled,
        "pendingStores": pending,
        "itensTotal": total_items,
        "itensConfirmados": confirmed_items,
        "firstExportAt": first_time,
        "lastExportAt": last_time,
    }
    write_json(status_file, data)
    print(details)


if __name__ == "__main__":
    main()
