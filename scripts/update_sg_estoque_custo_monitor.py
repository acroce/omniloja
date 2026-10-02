#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATUS = ROOT / "outputs" / "pleno_business_monitor" / "sg_estoque_custo.json"
DEFAULT_SERVICE_PATH = "/usr/share/pleno/cgi/sg_estoque_custo"


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


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def remote_config(env: dict[str, str]) -> tuple[str, str, str, str]:
    user = env.get("SG_ESTOQUE_CUSTO_REMOTE_USER") or env.get("STOCK_REMOTE_USER") or env.get("REMOTE_USER") or ""
    host = env.get("SG_ESTOQUE_CUSTO_REMOTE_HOST") or env.get("STOCK_REMOTE_HOST") or env.get("REMOTE_HOST") or ""
    port = env.get("SG_ESTOQUE_CUSTO_REMOTE_PORT") or env.get("STOCK_REMOTE_PORT") or env.get("REMOTE_PORT") or "22"
    password = env.get("SG_ESTOQUE_CUSTO_REMOTE_PASSWORD") or env.get("STOCK_REMOTE_PASSWORD") or env.get("REMOTE_PASSWORD") or ""
    if not user or not host:
        raise SystemExit("Configure SG_ESTOQUE_CUSTO_REMOTE_USER/HOST ou STOCK_REMOTE_USER/HOST.")
    return user, host, port, password


def run_remote_check(env: dict[str, str]) -> tuple[int, str, str]:
    user, host, port, password = remote_config(env)
    service_path = env.get("SG_ESTOQUE_CUSTO_PATH") or DEFAULT_SERVICE_PATH
    remote_script = f"""
set -eu
python3 - <<'PY'
import json
import re
import subprocess
from datetime import datetime, timedelta

service_path = {sh_quote(service_path)}
service_name = service_path.rstrip("/").split("/")[-1]
now = datetime.now().astimezone()
completed = subprocess.run(
    ["ps", "-eo", "pid=,etimes=,pcpu=,pmem=,args="],
    text=True,
    capture_output=True,
    check=False,
)
processes = []
for line in completed.stdout.splitlines():
    parts = line.strip().split(None, 4)
    if len(parts) < 5:
        continue
    pid, elapsed, cpu, mem, command = parts
    if service_path not in command and not re.search(r"(^|[\\s/])" + re.escape(service_name) + r"(\\s|$)", command):
        continue
    if "update_sg_estoque_custo_monitor" in command:
        continue
    seconds = int(float(elapsed))
    started = now - timedelta(seconds=seconds)
    processes.append({{
        "pid": pid,
        "elapsedSeconds": seconds,
        "startedAt": started.isoformat(timespec="seconds"),
        "cpuPct": float(cpu),
        "memPct": float(mem),
        "command": command,
    }})
print("JSON|" + json.dumps({{
    "servicePath": service_path,
    "remoteDate": now.isoformat(timespec="seconds"),
    "processes": processes,
}}, ensure_ascii=False))
PY
"""
    cmd = [
        "ssh",
        "-p",
        str(port),
        "-o",
        "BatchMode=no" if password else "BatchMode=yes",
        "-o",
        "ConnectTimeout=45",
        "-o",
        "StrictHostKeyChecking=accept-new",
        f"{user}@{host}",
        "sh",
        "-s",
    ]
    proc_env = os.environ.copy()
    askpass_path = None
    if password:
        fd, askpass_path = tempfile.mkstemp(prefix="sg-estoque-custo-askpass.", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write('#!/bin/sh\nprintf "%s\\n" "$SG_ESTOQUE_CUSTO_SSH_PASSWORD"\n')
        os.chmod(askpass_path, 0o700)
        proc_env.update(
            {
                "DISPLAY": proc_env.get("DISPLAY", ":0"),
                "SSH_ASKPASS": askpass_path,
                "SSH_ASKPASS_REQUIRE": "force",
                "SG_ESTOQUE_CUSTO_SSH_PASSWORD": password,
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
                timeout=75,
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


def parse_remote(output: str) -> dict[str, Any]:
    for line in output.splitlines():
        if line.startswith("JSON|"):
            return json.loads(line.split("|", 1)[1])
    return {"processes": []}


def format_elapsed(seconds: int) -> str:
    if seconds >= 3600:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}"
    if seconds >= 60:
        return f"{seconds // 60}min"
    return f"{seconds}s"


def build_events(env: dict[str, str]) -> dict[str, Any]:
    service_path = env.get("SG_ESTOQUE_CUSTO_PATH") or DEFAULT_SERVICE_PATH
    code, stdout, stderr = run_remote_check(env)
    if code != 0:
        details = (stderr or stdout or "Falha ao conectar no servidor.").strip().splitlines()
        return {
            "processo_ativo": {
                "targetTime": "00:00",
                "status": "sem_acesso",
                "actualAt": "",
                "count": 0,
                "source": service_path,
                "details": f"Sem acesso ao servidor para verificar {service_path}: {(details[-1] if details else '-')[:400]}",
            }
        }

    parsed = parse_remote(stdout)
    processes = parsed.get("processes") or []
    if processes:
        newest = sorted(processes, key=lambda item: int(item.get("elapsedSeconds") or 0))[0]
        elapsed = int(newest.get("elapsedSeconds") or 0)
        details = (
            f"Processo ativo em {service_path}. "
            f"PID {newest.get('pid')}, rodando ha {format_elapsed(elapsed)}, "
            f"CPU {newest.get('cpuPct')}%, memoria {newest.get('memPct')}%."
        )
        return {
            "processo_ativo": {
                "targetTime": "00:00",
                "status": "ok",
                "actualAt": parsed.get("remoteDate") or iso_now(),
                "count": len(processes),
                "source": service_path,
                "details": details,
                "processDetails": processes,
                "processRunning": True,
                "processStartTime": newest.get("startedAt") or "",
            }
        }

    return {
        "processo_ativo": {
            "targetTime": "00:00",
            "status": "erro",
            "actualAt": "",
            "count": 0,
            "source": service_path,
            "details": f"Processo {service_path} nao encontrado no ps.",
            "processDetails": [],
            "processRunning": False,
        }
    }


def write_status(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    env = load_env()
    status_path = Path(env.get("SG_ESTOQUE_CUSTO_STATUS_FILE") or DEFAULT_STATUS)
    data = {
        "collector": "sg-estoque-custo-monitor",
        "updatedAt": iso_now(),
        "events": build_events(env),
    }
    write_status(status_path, data)
    print(f"Monitor sg_estoque_custo atualizado em {status_path}")


if __name__ == "__main__":
    main()
