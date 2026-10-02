#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import time
import fcntl
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATUS_FILE = ROOT / "outputs" / "pleno_business_monitor" / "pdv_processes.json"
STATE_FILE = ROOT / "outputs" / "pleno_business_monitor" / "pdv_process_alert_state.json"
LOCK_FILE = ROOT / "outputs" / "pleno_business_monitor" / "pdv_process_watch.lock"
MONITOR_SCRIPT = ROOT / "scripts" / "update_pdv_process_monitor.py"


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
    env = load_env_file(ROOT / ".env")
    env.update(os.environ)
    return env


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def send_telegram(env: dict[str, str], message: str) -> None:
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chat_ids = [item.strip() for item in env.get("TELEGRAM_CHAT_IDS", "").split(",") if item.strip()]
    if not token or not chat_ids:
        raise RuntimeError("Configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_IDS no .env.")
    for chat_id in chat_ids:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        body = urllib.parse.urlencode(
            {
                "chat_id": chat_id,
                "text": message,
                "disable_web_page_preview": "true",
            }
        ).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST")
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not result.get("ok"):
            raise RuntimeError(f"Telegram recusou a mensagem para {chat_id}: {result}")


def run_monitor() -> None:
    subprocess.run(["python3", str(MONITOR_SCRIPT)], cwd=ROOT, check=False, timeout=120)


def current_events() -> dict[str, dict[str, Any]]:
    status = load_json(STATUS_FILE, {})
    return status.get("events") or {}


def down_events(events: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events.values() if str(event.get("status") or "").lower() == "erro"]


def recovered_keys(events: dict[str, dict[str, Any]], down_state: dict[str, Any]) -> list[str]:
    recovered: list[str] = []
    for key in down_state:
        status = str((events.get(key) or {}).get("status") or "").lower()
        if status in {"ok", "concluido", "concluido_ok"}:
            recovered.append(key)
    return recovered


def line_for(event: dict[str, Any]) -> str:
    title = event.get("serverTitle") or event.get("serverKey") or "PDV"
    label = event.get("label") or "-"
    return f"{title} - {label}"


def message_down(events: list[dict[str, Any]]) -> str:
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    lines = ["NOC Pleno", now, "❌ Processo PDV caiu"]
    lines.extend(line_for(event) for event in events)
    return "\n".join(lines)


def message_up(keys: list[str], events: dict[str, dict[str, Any]]) -> str:
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    lines = ["NOC Pleno", now, "✅ Processo PDV voltou"]
    lines.extend(line_for(events.get(key) or {"label": key}) for key in keys)
    return "\n".join(lines)


def quiet_hours(env: dict[str, str], now: datetime | None = None) -> bool:
    """Returns whether PDV notifications are muted while monitoring continues."""
    current = now or datetime.now()
    start = env.get("PDV_PROCESS_ALERT_QUIET_START", "23:00")
    end = env.get("PDV_PROCESS_ALERT_QUIET_END", "06:00")
    try:
        start_hour, start_minute = (int(value) for value in start.split(":", 1))
        end_hour, end_minute = (int(value) for value in end.split(":", 1))
        value = current.hour * 60 + current.minute
        start_value = start_hour * 60 + start_minute
        end_value = end_hour * 60 + end_minute
    except (TypeError, ValueError):
        return False
    if start_value == end_value:
        return False
    if start_value < end_value:
        return start_value <= value < end_value
    return value >= start_value or value < end_value


def check_once(env: dict[str, str]) -> None:
    run_monitor()
    events = current_events()
    state = load_json(STATE_FILE, {})
    down_state = state.get("down") or {}
    muted = quiet_hours(env)

    failed = down_events(events)
    if failed:
        new_alerts: list[dict[str, Any]] = []
        for event in failed:
            key = event.get("id") or f"{event.get('serverKey')}_{event.get('label')}"
            previous = down_state.get(key) or {}
            if not previous.get("alerted"):
                new_alerts.append(event)
            down_state[key] = {
                "lastDownAt": previous.get("lastDownAt") or datetime.now().isoformat(timespec="seconds"),
                "label": line_for(event),
                "alerted": bool(previous.get("alerted")),
            }
        state["down"] = down_state
        if new_alerts and not muted:
            send_telegram(env, message_down(new_alerts))
            for event in new_alerts:
                key = event.get("id") or f"{event.get('serverKey')}_{event.get('label')}"
                down_state[key]["alerted"] = True
            state["lastAlertAt"] = datetime.now().isoformat(timespec="seconds")
            print(f"Alerta PDV enviado para {len(new_alerts)} processo(s).")
        elif new_alerts:
            state["lastSuppressedAt"] = datetime.now().isoformat(timespec="seconds")
            print("Alerta PDV registrado, mas suprimido no horario silencioso (23:00-06:00).")
        else:
            print("Processos PDV continuam em alerta; sem reenvio duplicado.")
        write_json(STATE_FILE, state)
        return

    all_recovered = recovered_keys(events, down_state)
    recovered = [key for key in all_recovered if down_state.get(key, {}).get("alerted")]
    if all_recovered:
        if not muted:
            if recovered:
                send_telegram(env, message_up(recovered, events))
                state["lastRecoveredAt"] = datetime.now().isoformat(timespec="seconds")
                print(f"Normalizacao PDV enviada para {len(recovered)} processo(s).")
            else:
                print("Processos PDV normalizados sem alerta anterior.")
        elif recovered:
            state["lastRecoveredSuppressedAt"] = datetime.now().isoformat(timespec="seconds")
            print("Normalizacao PDV registrada, mas suprimida no horario silencioso (23:00-06:00).")
        for key in all_recovered:
            down_state.pop(key, None)
        state["down"] = down_state
        write_json(STATE_FILE, state)
        return

    state["lastSeenAt"] = datetime.now().isoformat(timespec="seconds")
    write_json(STATE_FILE, state)
    print("Processos PDV sem alerta.")


def main() -> None:
    env = load_env()
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Watcher de processos PDV ja esta em execucao; ignorado.")
            return
        checks = int(env.get("PDV_PROCESS_ALERT_CHECKS", "2") or "2")
        interval = int(env.get("PDV_PROCESS_ALERT_INTERVAL_SECONDS", "30") or "30")
        for index in range(max(checks, 1)):
            check_once(env)
            if index < checks - 1:
                time.sleep(max(interval, 1))


if __name__ == "__main__":
    main()
