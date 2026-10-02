#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".python_packages"))

DEFAULT_STATUS = ROOT / "outputs" / "pleno_business_monitor" / "checkin_notas_monitor.json"
DEFAULT_ORIGIN_STORE = 704
DEFAULT_HISTORY_HOURS = 12
DEFAULT_HISTORY_LIMIT = DEFAULT_HISTORY_HOURS * 6


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


def first_day_current_month() -> str:
    today = date.today()
    return today.replace(day=1).isoformat()


def write_status(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_previous_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    history = data.get("history")
    return history if isinstance(history, list) else []


def parse_iso(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def recent_hours_history(history: list[dict[str, Any]], hours: int = DEFAULT_HISTORY_HOURS) -> list[dict[str, Any]]:
    cutoff = datetime.now().astimezone() - timedelta(hours=hours)
    dated = [(parse_iso(row.get("collectedAt")), row) for row in history]
    dated = sorted((dt, row) for dt, row in dated if dt is not None)
    result = []
    for dt, row in dated:
        if dt < cutoff:
            continue
        total = int(row.get("total") or 0)
        done = int(row.get("comCheckin") or 0)
        pending = int(row.get("semCheckin") or 0)
        result.append({
            "collectedAt": row.get("collectedAt"),
            "metric": row.get("metric") or "pendingStoresTotal",
            "windowStartDate": row.get("windowStartDate") or "",
            "total": total,
            "comCheckin": done,
            "semCheckin": pending,
            "doneRate": row.get("doneRate", 0),
            "pendingRate": row.get("pendingRate", 0),
        })
    return result


def main() -> None:
    env = load_env()
    start_date = env.get("CHECKIN_NOTAS_START_DATE") or first_day_current_month()
    status_file = Path(env.get("CHECKIN_NOTAS_STATUS_FILE") or DEFAULT_STATUS)
    history_limit = int(env.get("CHECKIN_NOTAS_HISTORY_LIMIT") or str(DEFAULT_HISTORY_LIMIT))
    origin_store = int(env.get("CHECKIN_NOTAS_ORIGIN_STORE") or DEFAULT_ORIGIN_STORE)

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
        with conn.cursor() as cur:
            base_cte = """
                WITH notas_base AS (
                    SELECT
                        nf.fis01_id,
                        nf.fis01_nronf AS nota,
                        nf.fis01_serienf AS serie,
                        nf.fis01_data_emissao AS emissao,
                        nf.fis01_data_entrada_saida AS entrada_saida,
                        nf.fis01_hora_entrada_saida AS hora_entrada_saida,
                        nf.fis01_flgcancelada AS cancelada,
                        nf.adm05_usuario_checkin_id AS usuario_checkin_id,
                        COALESCE(MIN(f_origem.cfg06_numero), 0) AS loja_origem,
                        COALESCE(MIN(f_origem.cfg06_nome), '') AS nome_origem,
                        COALESCE(MIN(f_destino.cfg06_numero), 0) AS loja,
                        COALESCE(MIN(f_destino.cfg06_nome), '') AS nome_loja,
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
                    WHERE nf.fis01_entrada_saida = 'S'
                      AND COALESCE(nf.fis01_flgcancelada, 0) = 0
                      AND f_origem.cfg06_numero = %s
                      AND f_destino.cfg06_numero IS NOT NULL
                      AND f_destino.cfg06_numero > 0
                      AND f_destino.cfg06_numero < 3000
                      AND f_destino.cfg06_numero <> %s
                      AND (
                          nf.fis01_data_emissao >= %s
                          OR nf.fis01_data_entrada_saida >= %s
                      )
                    GROUP BY
                        nf.fis01_id,
                        nf.fis01_nronf,
                        nf.fis01_serienf,
                        nf.fis01_data_emissao,
                        nf.fis01_data_entrada_saida,
                        nf.fis01_hora_entrada_saida,
                        nf.fis01_flgcancelada,
                        nf.adm05_usuario_checkin_id
                )
            """
            base_params = (origin_store, origin_store, start_date, start_date)

            cur.execute(
                base_cte + """
                SELECT MIN(COALESCE(entrada_saida, emissao)) AS oldest_pending_date
                FROM notas_base
                WHERE usuario_checkin_id IS NULL
                """,
                base_params,
            )
            oldest_pending_date = (cur.fetchone() or {}).get("oldest_pending_date")
            effective_start_date = max(
                date.fromisoformat(start_date),
                oldest_pending_date if isinstance(oldest_pending_date, date) else date.today(),
            ).isoformat()
            window_cte = base_cte + """
                , notas AS (
                    SELECT *
                    FROM notas_base
                    WHERE COALESCE(entrada_saida, emissao) >= %s
                )
            """
            params = (*base_params, effective_start_date)

            cur.execute(
                window_cte
                + """
                SELECT
                    CASE WHEN usuario_checkin_id IS NULL THEN 'SEM_CHECKIN' ELSE 'COM_CHECKIN' END AS status,
                    COUNT(*) AS notas,
                    COALESCE(SUM(itens), 0) AS itens,
                    COALESCE(SUM(qtd), 0) AS qtd,
                    COALESCE(SUM(valor), 0) AS valor
                FROM notas
                GROUP BY status
                ORDER BY status
                """,
                params,
            )
            resumo = list(cur.fetchall())

            cur.execute(
                window_cte
                + """
                SELECT
                    COALESCE(entrada_saida, emissao) AS data_ref,
                    COUNT(*) AS total,
                    SUM(CASE WHEN usuario_checkin_id IS NULL THEN 1 ELSE 0 END) AS sem_checkin,
                    SUM(CASE WHEN usuario_checkin_id IS NULL THEN 0 ELSE 1 END) AS com_checkin
                FROM notas
                GROUP BY data_ref
                ORDER BY data_ref
                """,
                params,
            )
            por_dia = list(cur.fetchall())

            cur.execute(
                window_cte
                + """
                SELECT
                    loja,
                    nome_loja,
                    COUNT(*) AS total,
                    SUM(CASE WHEN usuario_checkin_id IS NULL THEN 1 ELSE 0 END) AS sem_checkin,
                    SUM(CASE WHEN usuario_checkin_id IS NULL THEN 0 ELSE 1 END) AS com_checkin
                FROM notas
                GROUP BY loja, nome_loja
                HAVING sem_checkin > 0
                ORDER BY sem_checkin DESC, total DESC, loja
                """,
                params,
            )
            lojas_pendentes = list(cur.fetchall())

            cur.execute(
                window_cte
                + f"""
                SELECT
                    loja,
                    nome_loja,
                    loja_origem,
                    nome_origem,
                    nota,
                    serie,
                    emissao,
                    entrada_saida,
                    hora_entrada_saida,
                    itens,
                    qtd,
                    valor
                FROM notas
                WHERE usuario_checkin_id IS NULL
                ORDER BY COALESCE(entrada_saida, emissao) DESC, nota DESC
                """,
                params,
            )
            pendentes = list(cur.fetchall())
    finally:
        conn.close()

    total = sum(int(row.get("notas") or 0) for row in resumo)
    sem_checkin = sum(int(row.get("notas") or 0) for row in resumo if row.get("status") == "SEM_CHECKIN")
    com_checkin = sum(int(row.get("notas") or 0) for row in resumo if row.get("status") == "COM_CHECKIN")
    updated_at = iso_now()
    totals = {
        "total": total,
        "comCheckin": com_checkin,
        "semCheckin": sem_checkin,
        "doneRate": round(com_checkin / total * 100, 2) if total else 0,
        "pendingRate": round(sem_checkin / total * 100, 2) if total else 0,
    }
    pending_store_total = sum(int(row.get("total") or 0) for row in lojas_pendentes)
    pending_store_sem_checkin = sum(int(row.get("sem_checkin") or 0) for row in lojas_pendentes)
    pending_store_com_checkin = sum(int(row.get("com_checkin") or 0) for row in lojas_pendentes)
    pending_store_totals = {
        "total": pending_store_total,
        "comCheckin": pending_store_com_checkin,
        "semCheckin": pending_store_sem_checkin,
        "doneRate": round(pending_store_com_checkin / pending_store_total * 100, 2) if pending_store_total else 0,
        "pendingRate": round(pending_store_sem_checkin / pending_store_total * 100, 2) if pending_store_total else 0,
    }
    point = {
        "collectedAt": updated_at,
        "metric": "pendingStoresTotal",
        "windowStartDate": effective_start_date,
        "total": pending_store_total,
        "comCheckin": pending_store_com_checkin,
        "semCheckin": pending_store_sem_checkin,
        "doneRate": pending_store_totals["doneRate"],
        "pendingRate": pending_store_totals["pendingRate"],
    }
    history = [
        row for row in load_previous_history(status_file)
        if row.get("metric") == "pendingStoresTotal"
        and row.get("windowStartDate") == effective_start_date
    ]
    if not history or history[-1].get("collectedAt") != updated_at:
        history.append(point)
    history = recent_hours_history(history[-history_limit:])
    status = {
        "collector": "checkin-notas-monitor",
        "updatedAt": updated_at,
        "startDate": effective_start_date,
        "configuredStartDate": start_date,
        "endDate": date.today().isoformat(),
        "originStore": origin_store,
        "historyLimit": history_limit,
        "source": f"{env['MYSQL_USER']}@{env['MYSQL_HOST']}:{env.get('MYSQL_PORT', '3306')}/{env['MYSQL_DATABASE']}",
        "totals": totals,
        "pendingStoreTotals": pending_store_totals,
        "summary": resumo,
        "byDay": por_dia,
        "history": history,
        "last12HoursHistory": history,
        "pendingStores": lojas_pendentes,
        "pendingNotes": pendentes,
    }
    write_status(status_file, status)
    print(
        f"Check-in notas CD {origin_store} atualizado: total={total}, com_checkin={com_checkin}, "
        f"sem_checkin={sem_checkin}, desde={effective_start_date}"
    )


if __name__ == "__main__":
    main()
