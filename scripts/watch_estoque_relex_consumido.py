#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATUS_FILE = ROOT / "outputs" / "pleno_business_monitor" / "estoque_relex.json"
LOG_FILE = ROOT / "outputs" / "pleno_business_monitor" / "logs" / "estoque_relex_watch.log"
MONITOR_SCRIPT = ROOT / "scripts" / "update_estoque_relex_monitor.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitora consumo do estoque RELEX a cada poucos segundos.")
    parser.add_argument("--interval-seconds", type=int, default=5)
    parser.add_argument("--max-hours", type=float, default=0, help="0 = roda ate consumir.")
    return parser.parse_args()


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


def log(message: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] {message}\n")
    print(message)


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
    completed = subprocess.run(["python3", str(MONITOR_SCRIPT)], cwd=ROOT, text=True, capture_output=True, check=False, timeout=120)
    if completed.stdout.strip():
        log(completed.stdout.strip())
    if completed.stderr.strip():
        log(completed.stderr.strip())


def load_consumed_event() -> dict[str, Any]:
    status = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    return (status.get("events") or {}).get("arquivo_consumido") or {}


def consumed_ok(event: dict[str, Any]) -> bool:
    return str(event.get("status") or "").lower() == "ok" and bool(event.get("actualAt"))


def message_error() -> str:
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    return "\n".join(["NOC Pleno", now, "❌ Estoque RELEX - Erro: Estoque consumido"])


def message_ok(event: dict[str, Any]) -> str:
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    actual = event.get("actualAt") or "-"
    return "\n".join(["NOC Pleno", now, "✅ Estoque RELEX - Consumido", f"Realizado {actual}"])


def main() -> None:
    args = parse_args()
    env = load_env()
    deadline = None
    if args.max_hours and args.max_hours > 0:
        deadline = datetime.now() + timedelta(hours=args.max_hours)

    had_error = False
    log("Iniciando watcher Estoque RELEX consumido.")
    while True:
        run_monitor()
        event = load_consumed_event()
        if consumed_ok(event):
            if had_error:
                send_telegram(env, message_ok(event))
                log("Estoque RELEX consumido; normalizacao enviada.")
            else:
                log("Estoque RELEX consumido; sem alerta anterior.")
            return

        status = str(event.get("status") or "").lower()
        if status == "sem_acesso":
            log("Sem acesso ao servidor; nao enviado como erro de consumo.")
        else:
            send_telegram(env, message_error())
            had_error = True
            log("Alerta Estoque RELEX consumido enviado.")

        if deadline and datetime.now() >= deadline:
            log("Limite do watcher atingido; encerrando.")
            return

        time.sleep(max(1, args.interval_seconds))


if __name__ == "__main__":
    main()
