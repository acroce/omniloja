#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATUS_FILE = ROOT / "outputs" / "pleno_business_monitor" / "promopreco.json"
POLICY_FILE = ROOT / "outputs" / "pleno_business_monitor" / "noc_alert_policy.json"
LOG_FILE = ROOT / "outputs" / "pleno_business_monitor" / "logs" / "promopreco_watch.log"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitora uma rodada de promocao/precos ate importar ou estourar o limite.")
    parser.add_argument("--run-time", required=True, help="Rodada monitorada, exemplo: 04:30.")
    parser.add_argument("--until", required=True, help="Horario limite, exemplo: 06:30.")
    parser.add_argument("--interval-seconds", type=int, default=600)
    return parser.parse_args()


def log(message: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] {message}\n")
    print(message)


def today_at(value: str) -> datetime:
    hour, minute = value.split(":", 1)
    now = datetime.now()
    return now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)


def run_key(run_time: str) -> str:
    return "r" + run_time.replace(":", "")


def run_step(command: list[str]) -> int:
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    if completed.stdout.strip():
        log(completed.stdout.strip())
    if completed.stderr.strip():
        log(completed.stderr.strip())
    return completed.returncode


def load_status() -> dict[str, Any]:
    return json.loads(STATUS_FILE.read_text(encoding="utf-8"))


def failure_interval_seconds(fallback: int) -> int:
    """Read the configured cadence each loop so a saved change takes effect immediately."""
    try:
        policy = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
        defaults = policy.get("defaults") or {}
        scope = (policy.get("scopes") or {}).get("promopreco") or {}
        value = scope.get("failureCheckIntervalSeconds", defaults.get("failureCheckIntervalSeconds", fallback))
        return max(1, int(value))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return fallback


def watched_events(status: dict[str, Any], run_time: str) -> list[tuple[str, dict[str, Any]]]:
    prefix = run_key(run_time)
    events: list[tuple[str, dict[str, Any]]] = []
    for key, event in (status.get("events") or {}).items():
        if key.startswith(prefix) and (key.endswith("_arquivo_importado") or key.endswith("_processo_carga")):
            events.append((key, event))
    return events


def pending_events(status: dict[str, Any], run_time: str) -> list[tuple[str, dict[str, Any]]]:
    pending: list[tuple[str, dict[str, Any]]] = []
    for key, event in watched_events(status, run_time):
        pending_count = int(event.get("pendingCount") or 0)
        event_status = str(event.get("status") or "")
        if event_status in {"error", "running"}:
            pending.append((key, event))
        elif event_status not in {"warning", "ok"} and pending_count > 0:
            pending.append((key, event))
    return pending


def pending_summary(pending: list[tuple[str, dict[str, Any]]]) -> str:
    parts = []
    for key, event in pending:
        if key.endswith("_processo_carga"):
            parts.append(f"{key}: processo rodando desde {event.get('processStartTime') or '-'}")
        else:
            parts.append(f"{key}: {event.get('pendingCount', 0)} sem imp.")
    return ", ".join(parts)


def update_monitor() -> None:
    code = run_step(["python3", str(ROOT / "scripts" / "update_promopreco_monitor.py"), "--server", "all"])
    if code != 0:
        log(f"Coleta retornou codigo {code}.")


def send_summary() -> None:
    command = ["python3", str(ROOT / "scripts" / "alert_telegram_monitor.py"), "--scope", "promopreco"]
    command.append("--only-errors")
    run_step(command)


def main() -> None:
    args = parse_args()
    deadline = today_at(args.until)
    if deadline <= datetime.now():
        deadline = deadline + timedelta(days=1)

    log(f"Iniciando watcher rodada {args.run_time} ate {args.until}.")
    last_pending = ""
    while True:
        update_monitor()
        status = load_status()
        pending = pending_events(status, args.run_time)
        if not pending:
            log(f"Rodada {args.run_time} OK. Enviando normalizacao apenas se havia erro anterior.")
            send_summary()
            return

        summary = pending_summary(pending)
        if summary != last_pending:
            log(f"Ainda pendente: {summary}")
            last_pending = summary

        if datetime.now() >= deadline:
            log(f"Limite {args.until} atingido com pendencia: {summary}. Enviando alerta.")
            send_summary()
            return

        interval = failure_interval_seconds(args.interval_seconds)
        sleep_for = min(interval, max(1, int((deadline - datetime.now()).total_seconds())))
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
