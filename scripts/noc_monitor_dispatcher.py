#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import fcntl
from datetime import datetime, time
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "pleno_business_monitor"
LOG = OUT / "logs" / "noc_dispatcher.log"
STATE_FILE = OUT / "noc_scheduler_state.json"
POLICY_FILE = OUT / "noc_alert_policy.json"
LOCK_FILE = OUT / "noc_dispatcher.lock"


def now_local() -> datetime:
    return datetime.now()


def stamp() -> str:
    return now_local().strftime("%Y-%m-%d %H:%M:%S")


def log(message: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp()}] {message}\n")


def load_state() -> dict[str, str]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_state(state: dict[str, str]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(STATE_FILE)


def minute_of_day(value: datetime) -> int:
    return value.hour * 60 + value.minute


def at(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def within(start: str, end: str, value: datetime) -> bool:
    current = minute_of_day(value)
    return at(start) <= current <= at(end)


def scope_enabled(scope: str, value: datetime) -> bool:
    defaults: dict[str, object] = {"weekdays": list(range(7))}
    scope_defaults: dict[str, dict[str, object]] = {"pedidos": {"weekdays": list(range(6))}}
    try:
        policy = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
        defaults.update(policy.get("defaults") or {})
        rule = {**scope_defaults.get(scope, {}), **((policy.get("scopes") or {}).get(scope) or {})}
        weekdays = rule.get("weekdays", defaults["weekdays"])
        return value.weekday() in {int(day) for day in weekdays}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return value.weekday() in set(scope_defaults.get(scope, defaults)["weekdays"])


def scope_setting(scope: str, key: str, fallback: object) -> object:
    try:
        policy = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
        defaults = policy.get("defaults") or {}
        rule = (policy.get("scopes") or {}).get(scope) or {}
        return rule.get(key, defaults.get(key, fallback))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return fallback


def today_key(name: str, value: datetime) -> str:
    return f"{value.date().isoformat()}:{name}"


def run_once(state: dict[str, str], name: str, action: Callable[[], None], *, due: str | None = None) -> None:
    now = now_local()
    if due and minute_of_day(now) < at(due):
        return
    key = today_key(name, now)
    if key in state:
        return
    log(f"Executando {name}.")
    try:
        action()
    except Exception as exc:  # noqa: BLE001 - scheduler must keep running.
        state[key] = f"erro: {exc}"
        log(f"Falha em {name}: {exc}")
    else:
        state[key] = stamp()
        log(f"Concluido {name}.")
    save_state(state)


def run_interval(state: dict[str, str], name: str, interval_seconds: int, action: Callable[[], None]) -> None:
    now = now_local()
    key = f"interval:{today_key(name, now)}"
    try:
        previous = datetime.fromisoformat(str(state.get(key) or ""))
    except ValueError:
        previous = None
    if previous and (now - previous).total_seconds() < max(60, interval_seconds):
        return
    log(f"Executando {name}.")
    try:
        action()
    except Exception as exc:  # noqa: BLE001 - scheduler must keep running.
        log(f"Falha em {name}: {exc}")
        return
    state[key] = now.isoformat(timespec="seconds")
    save_state(state)
    log(f"Concluido {name}.")


def run_command(args: list[str], log_name: str) -> None:
    log_path = OUT / "logs" / log_name
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp()}] Dispatcher iniciou: {' '.join(args)}\n")
        completed = subprocess.run(args, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, text=True, check=False)
        handle.write(f"[{stamp()}] Dispatcher finalizou codigo {completed.returncode}\n")


def launch_command(args: list[str], log_name: str) -> None:
    log_path = OUT / "logs" / log_name
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("a", encoding="utf-8")
    handle.write(f"[{stamp()}] Dispatcher iniciou em background: {' '.join(args)}\n")
    handle.flush()
    subprocess.Popen(args, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, text=True, start_new_session=True)


def pedidos_check_0810() -> None:
    runner = str(ROOT / "scripts" / "run_pedidos_business_monitor_step.sh")
    alert = str(ROOT / "scripts" / "alert_telegram_monitor.py")
    run_command(["sh", runner, "check_0810"], "pedidos_cron.log")
    run_command(["python3", alert, "--force", "--scope", "pedidos"], "telegram_alert.log")


def pedidos_remote_alert() -> None:
    runner = str(ROOT / "scripts" / "run_pedidos_business_monitor_step.sh")
    alert = str(ROOT / "scripts" / "alert_telegram_monitor.py")
    run_command(["sh", runner, "remote"], "pedidos_cron.log")
    run_command(["python3", alert, "--scope", "pedidos"], "telegram_alert.log")


def pedidos_entrada_retry() -> None:
    runner = str(ROOT / "scripts" / "run_pedidos_business_monitor_step.sh")
    run_command(["sh", runner, "all"], "pedidos_cron.log")


def pedidos_progress_summary() -> None:
    run_command(
        ["python3", str(ROOT / "scripts" / "alert_telegram_monitor.py"), "--force", "--scope", "pedidos"],
        "telegram_alert.log",
    )


def estoque_relex() -> None:
    run_command(["python3", str(ROOT / "scripts" / "update_estoque_relex_monitor.py")], "estoque_relex_cron.log")


def estoque_relex_alert() -> None:
    run_command(["python3", str(ROOT / "scripts" / "update_estoque_relex_monitor.py")], "estoque_relex_cron.log")
    run_command(
        ["python3", str(ROOT / "scripts" / "alert_telegram_monitor.py"), "--only-errors", "--scope", "estoque-relex"],
        "telegram_alert.log",
    )


def estoque_relex_consumido_watch() -> None:
    launch_command(
        ["python3", str(ROOT / "scripts" / "watch_estoque_relex_consumido.py"), "--interval-seconds", "5"],
        "estoque_relex_watch.log",
    )


def nightly_summary() -> None:
    run_command(["python3", str(ROOT / "scripts" / "update_estoque_relex_monitor.py")], "estoque_relex_cron.log")
    run_command(["python3", str(ROOT / "scripts" / "update_retificacao_ret_monitor.py")], "retificacao_ret_cron.log")
    run_command(["python3", str(ROOT / "scripts" / "update_devolucao_as400_monitor.py")], "devolucao_as400_cron.log")
    run_command(["python3", str(ROOT / "scripts" / "update_mercadoria_filial_monitor.py")], "mercadoria_filial_cron.log")
    run_command(
        ["python3", str(ROOT / "scripts" / "alert_telegram_monitor.py"), "--force", "--scope", "night"],
        "telegram_alert.log",
    )


def retificacao_ret() -> None:
    run_command(["python3", str(ROOT / "scripts" / "update_retificacao_ret_monitor.py")], "retificacao_ret_cron.log")
    run_command(
        ["python3", str(ROOT / "scripts" / "alert_telegram_monitor.py"), "--only-errors", "--scope", "retificacao-ret"],
        "telegram_alert.log",
    )


def devolucao_as400() -> None:
    run_command(["python3", str(ROOT / "scripts" / "update_devolucao_as400_monitor.py")], "devolucao_as400_cron.log")
    run_command(
        ["python3", str(ROOT / "scripts" / "alert_telegram_monitor.py"), "--only-errors", "--scope", "devolucao-as400"],
        "telegram_alert.log",
    )


def mercadoria_filial() -> None:
    run_command(["python3", str(ROOT / "scripts" / "update_mercadoria_filial_monitor.py")], "mercadoria_filial_cron.log")
    run_command(
        ["python3", str(ROOT / "scripts" / "alert_telegram_monitor.py"), "--only-errors", "--scope", "mercadoria-filial"],
        "telegram_alert.log",
    )


def promopreco_refresh() -> None:
    run_command(["python3", str(ROOT / "scripts" / "update_promopreco_monitor.py"), "--server", "all"], "promopreco_cron.log")


def notas_rejeitadas() -> None:
    run_command(["python3", str(ROOT / "scripts" / "update_notas_rejeitadas_monitor.py")], "notas_rejeitadas_cron.log")
    run_command(
        ["python3", str(ROOT / "scripts" / "alert_telegram_monitor.py"), "--only-errors", "--scope", "notas-rejeitadas"],
        "telegram_alert.log",
    )


def process_resources() -> None:
    run_command(["python3", str(ROOT / "scripts" / "update_process_resource_monitor.py")], "process_resources_cron.log")


def sg_estoque_custo() -> None:
    launch_command(["python3", str(ROOT / "scripts" / "alert_sg_estoque_custo_watch.py")], "sg_estoque_custo_cron.log")


def pdv_processes() -> None:
    launch_command(["python3", str(ROOT / "scripts" / "alert_pdv_process_watch.py")], "pdv_processes_cron.log")


def pdv_queue() -> None:
    run_command(["python3", str(ROOT / "scripts" / "update_pdv_queue_monitor.py")], "pdv_queue_cron.log")


def launch_pedidos(block: str, until: str, interval: str) -> Callable[[], None]:
    def _launch() -> None:
        launch_command(
            [
                "python3",
                str(ROOT / "scripts" / "watch_pedidos_until_ok.py"),
                "--block",
                block,
                "--until",
                until,
                "--interval-seconds",
                interval,
            ],
            "pedidos_cron.log",
        )

    return _launch


def launch_promopreco(run_time: str, until: str) -> Callable[[], None]:
    def _launch() -> None:
        launch_command(
            [
                "python3",
                str(ROOT / "scripts" / "watch_promopreco_until_ok.py"),
                "--run-time",
                run_time,
                "--until",
                until,
            ],
            "promopreco_cron.log",
        )

    return _launch


def _main() -> None:
    os.chdir(ROOT)
    state = load_state()
    now = now_local()

    if scope_enabled("promopreco", now) and within("04:30", "06:30", now):
        run_once(state, "promopreco_0430_watch", launch_promopreco("04:30", "06:30"))
    if scope_enabled("promopreco", now) and within("06:30", "09:00", now):
        run_once(state, "promopreco_0630_watch", launch_promopreco("06:30", "09:00"))
    if minute_of_day(now) >= at("07:30"):
        run_once(
            state,
            "telegram_resumo_0730",
            lambda: run_command(
                ["python3", str(ROOT / "scripts" / "alert_telegram_monitor.py"), "--force", "--scope", "morning"],
                "telegram_alert.log",
            ),
        )

    pedidos_day = scope_enabled("pedidos", now)
    if pedidos_day:
        if within("07:50", "09:30", now):
            run_once(state, "pedidos_entrada_watch", launch_pedidos("entrada", "09:30", "10"))
        run_once(state, "pedidos_0810_check", pedidos_check_0810, due="08:10")
        if within("09:30", "10:00", now):
            run_once(state, "pedidos_relex_watch", launch_pedidos("relex", "10:00", "60"))
        run_once(state, "pedidos_0935_backup", pedidos_remote_alert, due="09:35")
        run_once(state, "pedidos_0955_backup", pedidos_remote_alert, due="09:55")

        if within("08:05", "10:00", now) and now.minute % 5 == 0:
            run_once(state, f"pedidos_entrada_retry_{now.hour:02d}{now.minute:02d}", pedidos_entrada_retry)
        if within("07:50", "09:30", now) and bool(scope_setting("pedidos", "sendProgressSummary", False)):
            try:
                interval = max(60, int(scope_setting("pedidos", "progressSummaryEverySeconds", 600)))
            except (TypeError, ValueError):
                interval = 600
            run_interval(state, "pedidos_progress_summary", interval, pedidos_progress_summary)

    if scope_enabled("promopreco", now) and within("04:30", "12:00", now) and now.minute % 10 == 0:
        run_once(state, f"promopreco_refresh_{now.hour:02d}{now.minute:02d}", promopreco_refresh)

    if 4 <= now.hour <= 9 and now.minute % 5 == 0:
        run_once(state, f"process_resources_{now.hour:02d}{now.minute:02d}", process_resources)

    run_once(state, f"sg_estoque_custo_{now.hour:02d}{now.minute:02d}", sg_estoque_custo)
    run_once(state, f"pdv_processes_{now.hour:02d}{now.minute:02d}", pdv_processes)
    if now.minute % 5 == 0:
        run_once(state, f"pdv_queue_{now.hour:02d}{now.minute:02d}", pdv_queue)

    if now.minute == 0:
        run_once(state, f"retificacao_ret_{now.hour:02d}", retificacao_ret)
        run_once(state, f"notas_rejeitadas_{now.hour:02d}", notas_rejeitadas)
        run_once(state, f"devolucao_as400_{now.hour:02d}", devolucao_as400)
        run_once(state, f"mercadoria_filial_{now.hour:02d}", mercadoria_filial)

    run_once(state, "devolucao_as400_1815", devolucao_as400, due="18:15")
    run_once(state, "estoque_relex_consumido_0605", estoque_relex_consumido_watch, due="06:05")
    run_once(state, "telegram_resumo_2300", nightly_summary, due="23:00")


def main() -> None:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("Dispatcher ja esta em execucao; este tick foi ignorado.")
            return
        _main()


if __name__ == "__main__":
    main()
