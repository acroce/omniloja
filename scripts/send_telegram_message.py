from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from argparse import ArgumentParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> dict[str, str]:
    env_path = ROOT / ".env"
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def send_telegram(token: str, chat_id: str, message: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    request = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("ok"):
        raise RuntimeError(f"Telegram recusou a mensagem para {chat_id}: {body}")


def parse_args() -> ArgumentParser:
    parser = ArgumentParser(description="Send a plain Telegram message from stdin.")
    parser.add_argument(
        "--chat-ids-env",
        default="TELEGRAM_CHAT_IDS",
        help="Environment key in .env containing comma-separated Telegram chat IDs.",
    )
    return parser


def main() -> int:
    parser = parse_args()
    args = parser.parse_args()
    message = sys.stdin.read().strip()
    if not message:
        print("Mensagem vazia; Telegram nao enviado.", file=sys.stderr)
        return 64

    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chat_ids = [item.strip() for item in env.get(args.chat_ids_env, "").split(",") if item.strip()]
    if not token or not chat_ids:
        print(f"Configure TELEGRAM_BOT_TOKEN e {args.chat_ids_env} no .env.", file=sys.stderr)
        return 64

    for chat_id in chat_ids:
        send_telegram(token, chat_id, message)

    print(f"Mensagem Telegram enviada para {len(chat_ids)} destino(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
