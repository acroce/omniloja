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
STATUS_FILE = ROOT / "outputs" / "pleno_business_monitor" / "sg_estoque_custo.json"
STATE_FILE = ROOT / "outputs" / "pleno_business_monitor" / "sg_estoque_custo_alert_state.json"
LOCK_FILE = ROOT / "outputs" / "pleno_business_monitor" / "sg_estoque_custo_watch.lock"
MONITOR_SCRIPT = ROOT / "scripts" / "update_sg_estoque_custo_monitor.py"


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

    payload = {
        "text": message,
        "disable_web_page_preview": "true",
    }
    for chat_id in chat_ids:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        body = urllib.parse.urlencode({**payload, "chat_id": chat_id}).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST")
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not result.get("ok"):
            raise RuntimeError(f"Telegram recusou a mensagem para {chat_id}: {result}")


def run_monitor() -> None:
    subprocess.run(["python3", str(MONITOR_SCRIPT)], cwd=ROOT, check=False, timeout=90)


def current_stage() -> dict[str, Any]:
    status = load_json(STATUS_FILE, {})
    events = status.get("events") or {}
    return events.get("processo_ativo") or {}


def message_down(stage: dict[str, Any]) -> str:
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    details = str(stage.get("details") or "Processo sg_estoque_custo nao encontrado no ps.")
    return "\n".join([
        "NOC Pleno",
        now,
        "❌ sg_estoque_custo caiu",
        details,
    ])


def message_up(stage: dict[str, Any]) -> str:
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    details = str(stage.get("details") or "Processo sg_estoque_custo ativo novamente.")
    return "\n".join([
        "NOC Pleno",
        now,
        "✅ sg_estoque_custo voltou",
        details,
    ])


def check_once(env: dict[str, str]) -> None:
    run_monitor()
    stage = current_stage()
    state = load_json(STATE_FILE, {})
    status = str(stage.get("status") or "").lower()

    if status == "erro":
        send_telegram(env, message_down(stage))
        state.update({
            "down": True,
            "lastDownAt": datetime.now().isoformat(timespec="seconds"),
            "lastStatus": status,
        })
        write_json(STATE_FILE, state)
        print("Alerta sg_estoque_custo enviado.")
        return

    if state.get("down") and status in {"ok", "concluido", "concluido_ok"}:
        send_telegram(env, message_up(stage))
        state.update({
            "down": False,
            "lastRecoveredAt": datetime.now().isoformat(timespec="seconds"),
            "lastStatus": status,
        })
        write_json(STATE_FILE, state)
        print("Normalizacao sg_estoque_custo enviada.")
        return

    state["lastStatus"] = status
    state["lastSeenAt"] = datetime.now().isoformat(timespec="seconds")
    write_json(STATE_FILE, state)
    print(f"sg_estoque_custo sem alerta. status={status or '-'}")


def main() -> None:
    env = load_env()
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Watcher sg_estoque_custo ja esta em execucao; ignorado.")
            return
        checks = int(env.get("SG_ESTOQUE_CUSTO_ALERT_CHECKS", "2") or "2")
        interval = int(env.get("SG_ESTOQUE_CUSTO_ALERT_INTERVAL_SECONDS", "30") or "30")
        for index in range(max(checks, 1)):
            check_once(env)
            if index < checks - 1:
                time.sleep(max(interval, 1))


if __name__ == "__main__":
    main()
