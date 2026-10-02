#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATUS = ROOT / "outputs" / "pleno_business_monitor" / "pdv_processes.json"
DEFAULT_PROCESSES = ["pdv_server", "scc", "nfx_server"]


@dataclass
class ServerConfig:
    key: str
    title: str
    env_prefix: str
    host: str
    user: str
    port: int
    password: str


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
    env.update(os.environ)
    return env


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def configured_processes(env: dict[str, str]) -> list[str]:
    raw = env.get("PDV_PROCESS_NAMES") or ""
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return values or DEFAULT_PROCESSES


def server_configs(env: dict[str, str]) -> list[ServerConfig]:
    configs = []
    for key, title, fallback_prefix in (
        ("preprod", "Pré Prod PDV", "PROMOPRECO_S1_"),
        ("prod", "Prod PDV", "PROMOPRECO_S2_"),
    ):
        explicit = f"PDV_{key.upper()}_"
        configs.append(
            ServerConfig(
                key=key,
                title=env.get(explicit + "TITLE", title),
                env_prefix=explicit,
                host=env.get(explicit + "HOST") or env.get(fallback_prefix + "HOST", ""),
                user=env.get(explicit + "USER") or env.get(fallback_prefix + "USER", ""),
                port=int(env.get(explicit + "PORT") or env.get(fallback_prefix + "PORT", "22") or "22"),
                password=env.get(explicit + "PASSWORD") or env.get(fallback_prefix + "PASSWORD", ""),
            )
        )
    return configs


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def remote_script(processes: list[str]) -> str:
    names_json = json.dumps(processes)
    return f"""
set -eu
python3 - <<'PY'
import json
import re
import subprocess
from datetime import datetime, timedelta

names = json.loads({sh_quote(names_json)})
now = datetime.now().astimezone()
completed = subprocess.run(
    ["ps", "-eo", "pid=,etimes=,pcpu=,pmem=,args="],
    text=True,
    capture_output=True,
    check=False,
)
items = {{name: [] for name in names}}
for line in completed.stdout.splitlines():
    parts = line.strip().split(None, 4)
    if len(parts) < 5:
        continue
    pid, elapsed, cpu, mem, command = parts
    if "update_pdv_process_monitor" in command:
        continue
    for name in names:
        if not re.search(r"(^|[\\s/./_-])" + re.escape(name) + r"(\\s|$)", command):
            continue
        seconds = int(float(elapsed))
        started = now - timedelta(seconds=seconds)
        items[name].append({{
            "pid": pid,
            "elapsedSeconds": seconds,
            "startedAt": started.isoformat(timespec="seconds"),
            "cpuPct": float(cpu),
            "memPct": float(mem),
            "command": command,
        }})
print("JSON|" + json.dumps({{
    "remoteDate": now.isoformat(timespec="seconds"),
    "processes": items,
}}, ensure_ascii=False))
PY
"""


def askpass_env(config: ServerConfig) -> tuple[dict[str, str], str | None]:
    env = os.environ.copy()
    askpass_path = None
    if config.password:
        fd, askpass_path = tempfile.mkstemp(prefix=f"pdv-process-{config.key}-askpass.", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write('#!/bin/sh\nprintf "%s\\n" "$PDV_PROCESS_SSH_PASSWORD"\n')
        os.chmod(askpass_path, 0o700)
        env.update(
            {
                "DISPLAY": env.get("DISPLAY", ":0"),
                "SSH_ASKPASS": askpass_path,
                "SSH_ASKPASS_REQUIRE": "force",
                "PDV_PROCESS_SSH_PASSWORD": config.password,
            }
        )
    return env, askpass_path


def run_remote(config: ServerConfig, processes: list[str]) -> tuple[int, str, str]:
    cmd = [
        "ssh",
        "-p",
        str(config.port),
        "-o",
        "BatchMode=no" if config.password else "BatchMode=yes",
        "-o",
        "ConnectTimeout=45",
        "-o",
        "StrictHostKeyChecking=accept-new",
        f"{config.user}@{config.host}",
        "sh",
        "-s",
    ]
    proc_env, askpass_path = askpass_env(config)
    try:
        try:
            completed = subprocess.run(
                cmd,
                input=remote_script(processes),
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
    return {"processes": {}}


def format_elapsed(seconds: int) -> str:
    if seconds >= 3600:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}"
    if seconds >= 60:
        return f"{seconds // 60}min"
    return f"{seconds}s"


def stage_from_process(config: ServerConfig, name: str, parsed: dict[str, Any]) -> dict[str, Any]:
    processes = (parsed.get("processes") or {}).get(name) or []
    if processes:
        newest = sorted(processes, key=lambda item: int(item.get("elapsedSeconds") or 0))[0]
        elapsed = int(newest.get("elapsedSeconds") or 0)
        return {
            "id": f"{config.key}_{name}",
            "serverKey": config.key,
            "serverTitle": config.title,
            "label": name,
            "targetTime": "00:00",
            "status": "ok",
            "actualAt": parsed.get("remoteDate") or iso_now(),
            "count": len(processes),
            "source": f"{config.user}@{config.host}",
            "details": f"{name} ativo. PID {newest.get('pid')}, rodando ha {format_elapsed(elapsed)}, CPU {newest.get('cpuPct')}%, memoria {newest.get('memPct')}%.",
            "processDetails": processes,
            "processRunning": True,
            "processStartTime": newest.get("startedAt") or "",
        }
    return {
        "id": f"{config.key}_{name}",
        "serverKey": config.key,
        "serverTitle": config.title,
        "label": name,
        "targetTime": "00:00",
        "status": "erro",
        "actualAt": "",
        "count": 0,
        "source": f"{config.user}@{config.host}",
        "details": f"Processo {name} nao encontrado no ps.",
        "processDetails": [],
        "processRunning": False,
    }


def build_events(env: dict[str, str]) -> dict[str, Any]:
    processes = configured_processes(env)
    events: dict[str, Any] = {}
    for config in server_configs(env):
        if not config.host or not config.user:
            for name in processes:
                events[f"{config.key}_{name}"] = {
                    "id": f"{config.key}_{name}",
                    "serverKey": config.key,
                    "serverTitle": config.title,
                    "label": name,
                    "targetTime": "00:00",
                    "status": "sem_acesso",
                    "details": f"Servidor {config.title} nao configurado.",
                    "source": "",
                    "count": 0,
                }
            continue
        code, stdout, stderr = run_remote(config, processes)
        if code != 0:
            detail = (stderr or stdout or "Falha ao conectar no servidor.").strip().splitlines()
            for name in processes:
                events[f"{config.key}_{name}"] = {
                    "id": f"{config.key}_{name}",
                    "serverKey": config.key,
                    "serverTitle": config.title,
                    "label": name,
                    "targetTime": "00:00",
                    "status": "sem_acesso",
                    "actualAt": "",
                    "count": 0,
                    "source": f"{config.user}@{config.host}",
                    "details": f"Sem acesso ao servidor {config.title}: {(detail[-1] if detail else '-')[:400]}",
                }
            continue
        parsed = parse_remote(stdout)
        for name in processes:
            events[f"{config.key}_{name}"] = stage_from_process(config, name, parsed)
    return events


def write_status(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    env = load_env()
    status_path = Path(env.get("PDV_PROCESS_STATUS_FILE") or DEFAULT_STATUS)
    data = {
        "collector": "pdv-process-monitor",
        "updatedAt": iso_now(),
        "events": build_events(env),
    }
    write_status(status_path, data)
    print(f"Monitor processos PDV atualizado em {status_path}")


if __name__ == "__main__":
    main()
