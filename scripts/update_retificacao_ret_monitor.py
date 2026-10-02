#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATUS = ROOT / "outputs" / "pleno_business_monitor" / "retificacao_ret.json"
DEFAULT_REMOTE_DIR = "/servpleno/importacao"
DEFAULT_PATTERN = "RETIFICACAO_RET_*.*"
DEFAULT_MAX_FILES = 3


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
    # As credenciais do Linux sao fornecidas pelo Docker Compose a partir do
    # .env central; os arquivos locais continuam apenas como fallback.
    env.update(os.environ)
    return env


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def remote_config(env: dict[str, str]) -> tuple[str, str, str, str]:
    user = env.get("RETIFICACAO_RET_REMOTE_USER") or env.get("STOCK_REMOTE_USER") or ""
    host = env.get("RETIFICACAO_RET_REMOTE_HOST") or env.get("STOCK_REMOTE_HOST") or ""
    port = env.get("RETIFICACAO_RET_REMOTE_PORT") or env.get("STOCK_REMOTE_PORT") or "22"
    password = env.get("RETIFICACAO_RET_REMOTE_PASSWORD") or env.get("STOCK_REMOTE_PASSWORD") or ""
    if not user or not host:
        raise SystemExit("Configure RETIFICACAO_RET_REMOTE_USER/HOST ou STOCK_REMOTE_USER/HOST.")
    return user, host, port, password


def run_remote_check(env: dict[str, str]) -> tuple[int, str, str]:
    user, host, port, password = remote_config(env)
    remote_dir = env.get("RETIFICACAO_RET_REMOTE_DIR") or DEFAULT_REMOTE_DIR
    pattern = env.get("RETIFICACAO_RET_PATTERN") or DEFAULT_PATTERN
    remote_script = f"""
set -eu
dir={sh_quote(remote_dir)}
pattern={sh_quote(pattern)}
printf 'DIR|%s\\n' "$dir"
printf 'PATTERN|%s\\n' "$pattern"
find "$dir" -maxdepth 1 -type f -name "$pattern" -print 2>/dev/null | sort |
while IFS= read -r file; do
  name="$(basename "$file")"
  bytes="$(wc -c < "$file" | tr -d ' ')"
  if stat -c '%y' "$file" >/dev/null 2>&1; then
    mtime="$(stat -c '%y' "$file")"
  else
    mtime="$(stat -f '%Sm' "$file")"
  fi
  printf 'FILE|%s|%s|%s\\n' "$name" "$bytes" "$mtime"
done
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
        fd, askpass_path = tempfile.mkstemp(prefix="retificacao-ret-askpass.", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write('#!/bin/sh\nprintf "%s\\n" "$RETIFICACAO_RET_SSH_PASSWORD"\n')
        os.chmod(askpass_path, 0o700)
        proc_env.update(
            {
                "DISPLAY": proc_env.get("DISPLAY", ":0"),
                "SSH_ASKPASS": askpass_path,
                "SSH_ASKPASS_REQUIRE": "force",
                "RETIFICACAO_RET_SSH_PASSWORD": password,
            }
        )
    try:
        try:
            completed = subprocess.run(
                cmd,
                input=remote_script,
                text=True,
                capture_output=True,
                env=proc_env,
                timeout=90,
                check=False,
            )
            return completed.returncode, completed.stdout, completed.stderr
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            return 124, stdout, stderr or "Timeout ao acessar servidor."
    finally:
        if askpass_path:
            Path(askpass_path).unlink(missing_ok=True)


def parse_remote_output(output: str) -> dict[str, Any]:
    remote_dir = DEFAULT_REMOTE_DIR
    pattern = DEFAULT_PATTERN
    files: list[dict[str, Any]] = []
    for line in output.splitlines():
        parts = line.split("|", 3)
        if not parts:
            continue
        if parts[0] == "DIR" and len(parts) >= 2:
            remote_dir = parts[1]
        elif parts[0] == "PATTERN" and len(parts) >= 2:
            pattern = parts[1]
        elif parts[0] == "FILE" and len(parts) >= 4:
            files.append({"name": parts[1], "bytes": int(parts[2] or 0), "mtime": parts[3]})
    return {"remoteDir": remote_dir, "pattern": pattern, "files": files}


def write_status(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def build_event(env: dict[str, str]) -> dict[str, Any]:
    max_files = int(env.get("RETIFICACAO_RET_MAX_FILES") or DEFAULT_MAX_FILES)
    code, stdout, stderr = run_remote_check(env)
    if code != 0:
        details = (stderr or stdout or "Falha ao conectar no servidor.").strip()
        return {
            "targetTime": "00:00",
            "status": "sem_acesso",
            "actualAt": "",
            "count": 0,
            "source": env.get("RETIFICACAO_RET_REMOTE_DIR") or DEFAULT_REMOTE_DIR,
            "details": f"Sem acesso ao servidor: {details[:500]}",
            "files": [],
            "maxFiles": max_files,
        }

    parsed = parse_remote_output(stdout)
    files = parsed["files"]
    count = len(files)
    names = ", ".join(item["name"] for item in files[:12])
    suffix = f" (+{count - 12})" if count > 12 else ""
    files_text = f" Arquivos: {names}{suffix}." if files else " Pasta sem arquivos pendentes."
    status = "ok" if count <= max_files else "error"
    details = (
        f"Retificacao RET em {parsed['remoteDir']}: {count} arquivo(s) para limite {max_files}."
        f"{files_text}"
    )
    return {
        "targetTime": "00:00",
        "status": status,
        "actualAt": iso_now(),
        "count": count,
        "source": parsed["remoteDir"],
        "details": details,
        "files": files,
        "maxFiles": max_files,
        "pattern": parsed["pattern"],
    }


def main() -> None:
    env = load_env()
    status = {
        "collector": "retificacao-ret-monitor",
        "updatedAt": iso_now(),
        "events": {
            "arquivos_pendentes": build_event(env),
        },
    }
    write_status(DEFAULT_STATUS, status)
    print(f"Monitor retificacao RET atualizado em {DEFAULT_STATUS}")


if __name__ == "__main__":
    main()
