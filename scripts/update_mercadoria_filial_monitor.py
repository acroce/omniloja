#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATUS = ROOT / "outputs" / "pleno_business_monitor" / "mercadoria_filial.json"
DEFAULT_REMOTE_DIR = "/servpleno/importacao"
DEFAULT_RECEIVED_TARGET = "08:30"
DEFAULT_CONSUMED_TARGET = "09:30"
DEFAULT_FILE_TYPES = ["MERCADORIA_CODIGOS", "MERCADORIA", "MERCADORIA_FILIAL"]


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
    env.update(load_env_file(ROOT / "config" / "pleno_fetch_remote.env"))
    env.update(os.environ)
    return env


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def wanted_file_date() -> date:
    return datetime.now().date() - timedelta(days=1)


def after_target(time_text: str) -> bool:
    try:
        hour, minute = time_text.split(":", 1)
        target = datetime.now().replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    except ValueError:
        return True
    return datetime.now() >= target


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def remote_config(env: dict[str, str]) -> tuple[str, str, str, str]:
    user = env.get("MERCADORIA_FILIAL_REMOTE_USER") or env.get("STOCK_REMOTE_USER") or env.get("REMOTE_USER") or ""
    host = env.get("MERCADORIA_FILIAL_REMOTE_HOST") or env.get("STOCK_REMOTE_HOST") or env.get("REMOTE_HOST") or ""
    port = env.get("MERCADORIA_FILIAL_REMOTE_PORT") or env.get("STOCK_REMOTE_PORT") or env.get("REMOTE_PORT") or "22"
    password = env.get("MERCADORIA_FILIAL_REMOTE_PASSWORD") or env.get("STOCK_REMOTE_PASSWORD") or env.get("REMOTE_PASSWORD") or ""
    if not user or not host:
        raise SystemExit("Configure MERCADORIA_FILIAL_REMOTE_USER/HOST ou STOCK_REMOTE_USER/HOST.")
    return user, host, port, password


def configured_file_types(env: dict[str, str]) -> list[str]:
    raw = env.get("MERCADORIA_FILIAL_FILE_TYPES") or ""
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values or DEFAULT_FILE_TYPES


def run_remote_scan(env: dict[str, str], wanted: date) -> tuple[int, str, str]:
    user, host, port, password = remote_config(env)
    remote_dir = env.get("MERCADORIA_FILIAL_REMOTE_DIR") or DEFAULT_REMOTE_DIR
    wanted_yyyymmdd = wanted.strftime("%Y%m%d")
    file_types_json = json.dumps(configured_file_types(env))
    remote_script = f"""
set -eu
python3 - <<'PY'
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

base = Path({sh_quote(remote_dir)})
wanted = {sh_quote(wanted_yyyymmdd)}
file_types = json.loads({sh_quote(file_types_json)})
patterns = []
for file_type in file_types:
    patterns.append(f"{{file_type}}_{{wanted}}*.csv")
    patterns.append(f"imp.*.{{file_type}}_{{wanted}}*.csv")
files = []
for pattern in patterns:
    files.extend(base.glob(pattern))
    files.extend((base / "processados").glob(pattern))
    files.extend((base / "mercadoria_processados").glob(pattern))
rows = []
for path in sorted({{str(p): p for p in files if p.is_file()}}.values()):
    st = path.stat()
    consumed = path.name.startswith("imp.") or "processados" in path.parts or "mercadoria_processados" in path.parts
    raw_name = path.name[4:] if path.name.startswith("imp.") else path.name
    file_type = ""
    for candidate in sorted(file_types, key=len, reverse=True):
        # Imported files keep their source timestamp before the business filename,
        # e.g. imp.202608210610.MERCADORIA_FILIAL_20260820083000.csv.
        if re.search(rf"(?:^|\\.){{re.escape(candidate)}}_", raw_name):
            file_type = candidate
            break
    rows.append({{
        "path": str(path),
        "name": path.name,
        "fileType": file_type,
        "dir": str(path.parent),
        "bytes": st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).astimezone().isoformat(timespec="seconds"),
        "ctime": datetime.fromtimestamp(st.st_ctime, timezone.utc).astimezone().isoformat(timespec="seconds"),
        "consumed": consumed,
    }})
print("JSON|" + json.dumps({{"base": str(base), "wanted": wanted, "fileTypes": file_types, "files": rows}}, ensure_ascii=False))
PY
"""
    cmd = [
        "ssh",
        "-p",
        str(port),
        "-o",
        "BatchMode=no" if password else "BatchMode=yes",
        "-o",
        "ConnectTimeout=60",
        "-o",
        "StrictHostKeyChecking=accept-new",
        f"{user}@{host}",
        "sh",
        "-s",
    ]
    proc_env = os.environ.copy()
    askpass_path = None
    if password:
        fd, askpass_path = tempfile.mkstemp(prefix="mercadoria-filial-askpass.", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write('#!/bin/sh\nprintf "%s\\n" "$MERCADORIA_FILIAL_SSH_PASSWORD"\n')
        os.chmod(askpass_path, 0o700)
        proc_env.update({
            "DISPLAY": proc_env.get("DISPLAY", ":0"),
            "SSH_ASKPASS": askpass_path,
            "SSH_ASKPASS_REQUIRE": "force",
            "MERCADORIA_FILIAL_SSH_PASSWORD": password,
        })
    try:
        try:
            completed = subprocess.run(cmd, input=remote_script, text=True, capture_output=True, env=proc_env, timeout=120, check=False)
            return completed.returncode, completed.stdout, completed.stderr
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            return 124, stdout, stderr or "Timeout ao acessar servidor."
    finally:
        if askpass_path:
            Path(askpass_path).unlink(missing_ok=True)


def parse_remote(output: str) -> dict[str, Any]:
    for line in output.splitlines():
        if line.startswith("JSON|"):
            return json.loads(line.split("|", 1)[1])
    return {"files": []}


def newest(files: list[dict[str, Any]], *, consumed: bool | None = None) -> dict[str, Any] | None:
    selected = [item for item in files if consumed is None or bool(item.get("consumed")) is consumed]
    if not selected:
        return None
    return sorted(selected, key=lambda item: str(item.get("ctime") or item.get("mtime") or ""), reverse=True)[0]


def latest_by_type(files: list[dict[str, Any]], expected_types: list[str], *, consumed: bool | None = None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for file_type in expected_types:
        typed = [
            item for item in files
            if item.get("fileType") == file_type and (consumed is None or bool(item.get("consumed")) is consumed)
        ]
        item = newest(typed, consumed=consumed)
        if item:
            result[file_type] = item
    return result


def event_time(items: dict[str, dict[str, Any]], field: str = "ctime") -> str:
    values = [str(item.get(field) or item.get("mtime") or "") for item in items.values()]
    return max(values) if values else ""


def build_events(env: dict[str, str]) -> dict[str, Any]:
    wanted = wanted_file_date()
    code, stdout, stderr = run_remote_scan(env, wanted)
    received_target = env.get("MERCADORIA_FILIAL_RECEIVED_TARGET_TIME") or DEFAULT_RECEIVED_TARGET
    consumed_target = env.get("MERCADORIA_FILIAL_CONSUMED_TARGET_TIME") or DEFAULT_CONSUMED_TARGET
    if code != 0:
        details = (stderr or stdout or "Falha ao conectar no servidor.").strip()
        common = {
            "status": "sem_acesso",
            "actualAt": "",
            "count": 0,
            "source": env.get("MERCADORIA_FILIAL_REMOTE_DIR") or DEFAULT_REMOTE_DIR,
            "details": f"Sem acesso: {details[:500]}",
        }
        return {
            "arquivo_recebido": {"targetTime": received_target, **common},
            "arquivo_consumido": {"targetTime": consumed_target, **common},
        }

    parsed = parse_remote(stdout)
    files = parsed.get("files") or []
    expected_types = parsed.get("fileTypes") or configured_file_types(env)
    received_by_type = latest_by_type(files, expected_types)
    consumed_by_type = latest_by_type(files, expected_types, consumed=True)
    missing_received = [item for item in expected_types if item not in received_by_type]
    missing_consumed = [item for item in expected_types if item not in consumed_by_type]
    received = newest(list(received_by_type.values()))
    consumed = newest(list(consumed_by_type.values()), consumed=True)
    wanted_text = wanted.strftime("%d/%m/%Y")
    received_missing_status = "error" if after_target(received_target) else "warning"
    consumed_missing_status = "error" if after_target(consumed_target) else "warning"
    received_event = {
        "targetTime": received_target,
        "status": "ok" if not missing_received else received_missing_status,
        "actualAt": event_time(received_by_type),
        "count": len(received_by_type),
        "expectedCount": len(expected_types),
        "missingFiles": missing_received,
        "source": (received or {}).get("path") or parsed.get("base") or DEFAULT_REMOTE_DIR,
        "details": (
            f"Arquivos de mercadoria de {wanted_text} recebidos: {len(received_by_type)}/{len(expected_types)}."
            + (f" Faltando: {', '.join(missing_received)}." if missing_received else "")
        ),
        "files": files,
    }
    consumed_event = {
        "targetTime": consumed_target,
        "status": "ok" if not missing_consumed else consumed_missing_status,
        "actualAt": event_time(consumed_by_type),
        "count": len(consumed_by_type),
        "expectedCount": len(expected_types),
        "missingFiles": missing_consumed,
        "source": (consumed or {}).get("path") or parsed.get("base") or DEFAULT_REMOTE_DIR,
        "details": (
            f"Arquivos de mercadoria de {wanted_text} consumidos pelo Pleno: {len(consumed_by_type)}/{len(expected_types)}."
            + (f" Faltando: {', '.join(missing_consumed)}." if missing_consumed else "")
        ),
        "files": files,
    }
    return {"arquivo_recebido": received_event, "arquivo_consumido": consumed_event}


def write_status(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    env = load_env()
    status = {
        "collector": "mercadoria-filial-monitor",
        "updatedAt": iso_now(),
        "events": build_events(env),
    }
    write_status(DEFAULT_STATUS, status)
    print(f"Monitor mercadoria filial atualizado em {DEFAULT_STATUS}")


if __name__ == "__main__":
    main()
