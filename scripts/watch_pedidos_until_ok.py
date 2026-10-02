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
STATUS_FILE = ROOT / "outputs" / "pleno_business_monitor" / "pedidos.json"
POLICY_FILE = ROOT / "outputs" / "pleno_business_monitor" / "noc_alert_policy.json"
LOG_FILE = ROOT / "outputs" / "pleno_business_monitor" / "logs" / "pedidos_watch.log"
RUNNER = ROOT / "scripts" / "run_pedidos_business_monitor_step.sh"
ALERT = ROOT / "scripts" / "alert_telegram_monitor.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitora blocos do processo de pedidos ate OK ou limite.")
    parser.add_argument("--block", choices=["entrada", "relex"], required=True)
    parser.add_argument("--until", required=True, help="Horario limite, exemplo: 08:20.")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--no-alert", action="store_true", help="Nao envia resumo/alerta Telegram ao concluir ou atingir limite.")
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
        scope = (policy.get("scopes") or {}).get("pedidos") or {}
        value = scope.get("failureCheckIntervalSeconds", defaults.get("failureCheckIntervalSeconds", fallback))
        return max(1, int(value))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return fallback


def event_ok(event: dict[str, Any]) -> bool:
    details = str(event.get("details") or "")
    return (
        int(event.get("count") or 0) >= 2
        and bool(event.get("actualAt"))
        and str(event.get("status") or "ok").lower() in {"", "ok", "concluido", "concluido_ok"}
        and "pendente" not in details.lower()
        and "faltando" not in details.lower()
    )


def mysql_ok(event: dict[str, Any]) -> bool:
    return (
        str(event.get("status") or "").lower() == "ok"
        and bool(event.get("actualAt"))
        and int(event.get("count") or 0) > 0
    )


def pending_summary(status: dict[str, Any], block: str) -> str:
    events = status.get("events") or {}
    if block == "entrada":
        checks = [
            ("arquivo_original", "originais"),
            ("arquivo_chegada", "importados imp"),
            ("arquivo_vs_pleno", "pedidos no Pleno"),
            ("checagem_0805", "MySQL 08:05"),
            ("checagem_0810", "MySQL 08:10"),
        ]
        pending = []
        for key, label in checks:
            event = events.get(key) or {}
            ok = mysql_ok(event) if key.startswith("checagem") else event_ok(event)
            if not ok:
                pending.append(label)
        return ", ".join(pending)

    checks = [
        ("envio_relex", "arquivo RELEX gerado"),
        ("relex_processados", "enviado ao RELEX"),
    ]
    pending = []
    for key, label in checks:
        if not event_ok(events.get(key) or {}):
            pending.append(label)
    return ", ".join(pending)


def run_block_collection(block: str) -> None:
    now = datetime.now()
    if block == "entrada":
        run_step(["sh", str(RUNNER), "lojas_esperadas"])
        run_step(["sh", str(RUNNER), "remote"])
        if now >= today_at("08:10"):
            run_step(["sh", str(RUNNER), "arquivo_vs_pleno"])
        if now >= today_at("08:05"):
            run_step(["sh", str(RUNNER), "mysql_0805"])
        if now >= today_at("08:10"):
            run_step(["sh", str(RUNNER), "mysql_0810"])
    else:
        run_step(["sh", str(RUNNER), "remote"])


def send_summary() -> None:
    run_step(["python3", str(ALERT), "--force", "--scope", "pedidos"])


def send_pending_alert() -> None:
    # The alert runner deduplicates and repeats according to the policy, so
    # the watcher can check every pending cycle without flooding recipients.
    run_step(["python3", str(ALERT), "--only-errors", "--scope", "pedidos"])


def send_critical_entry_alert() -> None:
    # A missing source/imported order file blocks the entire morning flow.
    # Force the configured destinations every watcher cycle until it recovers
    # or the incident is acknowledged in the alert settings.
    run_step(["python3", str(ALERT), "--force", "--only-errors", "--scope", "pedidos"])


def has_critical_entry_failure(status: dict[str, Any]) -> bool:
    events = status.get("events") or {}
    critical_steps = (
        ("arquivo_original", "07:55"),
        ("arquivo_chegada", "08:10"),
        ("arquivo_vs_pleno", "08:10"),
    )
    now = datetime.now()
    for key, deadline in critical_steps:
        event = events.get(key) or {}
        raw_status = str(event.get("status") or "").lower()
        if raw_status in {"error", "erro", "atrasado", "sem_acesso"}:
            return True
        # The panel derives 'atrasado' when a raw event is absent or blank
        # after its deadline. Mirror that rule in the alert watcher.
        if now >= today_at(deadline) and not event_ok(event):
            return True
    return False


def main() -> None:
    args = parse_args()
    deadline = today_at(args.until)
    if deadline <= datetime.now():
        deadline = deadline + timedelta(days=1)

    log(f"Iniciando watcher pedidos bloco {args.block} ate {args.until}.")
    last_pending = ""
    while True:
        cycle_started = time.monotonic()
        run_block_collection(args.block)
        status = load_status()
        pending = pending_summary(status, args.block)
        if not pending:
            if args.no_alert:
                log(f"Bloco {args.block} OK. Sem envio Telegram.")
            else:
                log(f"Bloco {args.block} OK. Enviando resumo.")
                send_summary()
            return

        if pending != last_pending:
            log(f"Ainda pendente: {pending}")
            last_pending = pending
        if not args.no_alert:
            if args.block == "entrada" and has_critical_entry_failure(status):
                send_critical_entry_alert()
            else:
                send_pending_alert()

        if datetime.now() >= deadline:
            if args.block == "entrada" and has_critical_entry_failure(status):
                log(f"Limite {args.until} atingido com falha critica: {pending}. Mantendo monitoramento e alerta a cada ciclo.")
                time.sleep(max(0, 10 - (time.monotonic() - cycle_started)))
                continue
            if args.no_alert:
                log(f"Limite {args.until} atingido com pendencia: {pending}. Sem envio Telegram.")
            else:
                log(f"Limite {args.until} atingido com pendencia: {pending}. Enviando alerta.")
                send_summary()
            return

        interval = 10 if args.block == "entrada" and has_critical_entry_failure(status) else failure_interval_seconds(args.interval_seconds)
        sleep_for = min(interval, max(1, int((deadline - datetime.now()).total_seconds())))
        time.sleep(max(0, sleep_for - (time.monotonic() - cycle_started)))


if __name__ == "__main__":
    main()
