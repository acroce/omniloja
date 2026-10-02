#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".python_packages"))

DEFAULT_STATUS = ROOT / "outputs" / "pleno_business_monitor" / "pedidos.json"
DEFAULT_SQL = ROOT / "config" / "pedidos_entrada_mysql.sql"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Atualiza a etapa MySQL do monitor de pedidos."
    )
    parser.add_argument("--status-file", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--sql-file", type=Path, default=DEFAULT_SQL)
    parser.add_argument("--event-id", default="checagem_0805")
    parser.add_argument("--target-time", default="08:05")
    return parser.parse_args()


def load_env() -> dict[str, str]:
    env_path = ROOT / ".env"
    if not env_path.exists():
        raise SystemExit(f"Arquivo .env nao encontrado em {env_path}")
    env: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        env[key] = value.strip().strip('"').strip("'")
    return env


def to_number(value: Any) -> float:
    if value is None:
        return 0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_status(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {"collector": "pedidos-monitor", "events": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def write_status(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def mysql_source(env: dict[str, str]) -> str:
    if not env:
        return "mysql"
    return f"{env.get('MYSQL_USER', '')}@{env.get('MYSQL_HOST', '')}:{env.get('MYSQL_PORT', '')}/{env.get('MYSQL_DATABASE', '')}"


def event_is_today_ok(event: dict[str, Any], now: str) -> bool:
    return str(event.get("status") or "").lower() == "ok" and str(event.get("actualAt") or "").startswith(now[:10])


def run_query(env: dict[str, str], sql: str) -> list[dict[str, Any]]:
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
            cur.execute(sql)
            return list(cur.fetchall())
    finally:
        conn.close()


def main() -> None:
    args = parse_args()
    now = iso_now()
    status = load_status(args.status_file)
    status["collector"] = "pedidos-monitor"
    status["updatedAt"] = now
    status.setdefault("events", {})
    previous = status["events"].get(args.event_id) or {}
    env: dict[str, str] = {}

    try:
        env = load_env()
        sql = args.sql_file.read_text(encoding="utf-8")
        rows = run_query(env, sql)
    except Exception as exc:  # noqa: BLE001 - monitor must persist failed attempts.
        status["events"][args.event_id] = {
            "targetTime": args.target_time,
            "status": "erro",
            "actualAt": now,
            "lastFailedAt": now,
            "firstSuccessAt": previous.get("firstSuccessAt") or "",
            "count": previous.get("count") or 0,
            "source": mysql_source(env),
            "details": f"MySQL com erro na consulta. Ultima tentativa com falha: {now}. Erro: {str(exc)[:500]}",
        }
        write_status(args.status_file, status)
        print(status["events"][args.event_id]["details"])
        raise SystemExit(1)

    total_linhas = 0
    total_pedidos = 0
    entrada_linhas = 0
    pendente_linhas = 0
    for row in rows:
        situacao = str(row.get("Situacao") or "")
        linhas = int(to_number(row.get("linhas")))
        pedidos = int(to_number(row.get("pedidos")))
        total_linhas += linhas
        total_pedidos += pedidos
        if situacao == "Entrada realizada":
            entrada_linhas = linhas
        elif situacao == "Pendente Entrada":
            pendente_linhas = linhas

    actual_at = previous.get("actualAt") if event_is_today_ok(previous, now) else now
    details = (
        f"MySQL OK. Linhas: {total_linhas}. Pedidos: {total_pedidos}. "
        f"Entrada realizada: {entrada_linhas}. Pendente Entrada: {pendente_linhas}."
    )
    status["events"][args.event_id] = {
        "targetTime": args.target_time,
        "status": "ok",
        "actualAt": actual_at,
        "firstSuccessAt": actual_at,
        "lastFailedAt": previous.get("lastFailedAt") or "",
        "count": total_linhas,
        "source": mysql_source(env),
        "details": details,
    }
    write_status(args.status_file, status)
    print(details)


if __name__ == "__main__":
    main()
