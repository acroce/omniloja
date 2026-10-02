#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATUS = ROOT / "outputs" / "pleno_business_monitor" / "process_resources.json"


@dataclass
class ServerConfig:
    key: str
    label: str
    host: str
    user: str
    port: int
    password: str


def load_env() -> dict[str, str]:
    env_path = ROOT / ".env"
    env: dict[str, str] = {}
    if not env_path.exists():
        return env
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key] = value.strip().strip('"').strip("'")
    return env


def server_configs(env: dict[str, str]) -> list[ServerConfig]:
    configs: list[ServerConfig] = []
    for key in ("s1", "s2"):
        prefix = f"PROMOPRECO_{key.upper()}_"
        configs.append(ServerConfig(
            key=key,
            label=env.get(prefix + "LABEL", f"Servidor {key[-1]}"),
            host=env.get(prefix + "HOST", ""),
            user=env.get(prefix + "USER", ""),
            port=int(env.get(prefix + "PORT", "22") or "22"),
            password=env.get(prefix + "PASSWORD", ""),
        ))
    return configs


REMOTE_SCRIPT = r'''
set -u
now_epoch=$(date +%s)
printf 'META|host|%s\n' "$(hostname 2>/dev/null || echo '-')"
printf 'META|date|%s\n' "$(date '+%F %T %z')"
printf 'META|nowEpoch|%s\n' "$now_epoch"
printf 'META|cores|%s\n' "$(nproc 2>/dev/null || echo 1)"
read load1 load5 load15 rest < /proc/loadavg
printf 'META|load1|%s\nMETA|load5|%s\nMETA|load15|%s\n' "$load1" "$load5" "$load15"
free -m | awk '/^Mem:/ {printf "MEM|totalMb|%s\nMEM|usedMb|%s\nMEM|freeMb|%s\nMEM|availableMb|%s\n", $2, $3, $4, $7}'
df -P / 2>/dev/null | awk 'NR==2 {gsub("%","",$5); printf "DISK|rootUsedPct|%s\nDISK|rootAvailKb|%s\n", $5, $4}'
vmstat 1 3 | awk 'END {printf "CPU|userPct|%s\nCPU|systemPct|%s\nCPU|idlePct|%s\nCPU|iowaitPct|%s\n", $13, $14, $15, $16}'
ps -eo pid=,ppid=,etimes=,pcpu=,pmem=,rss=,args= | awk '/\/retag\/(cargas|cargas2|importa|gerabd)/ && !/awk/ {
  pid=$1; ppid=$2; etimes=$3; pcpu=$4; pmem=$5; rss=$6
  $1=$2=$3=$4=$5=$6=""
  sub(/^ +/, "")
  printf "PROC|%s|%s|%s|%s|%s|%s|%s\n", pid, ppid, etimes, pcpu, pmem, rss, $0
}'
'''


def askpass_env(config: ServerConfig) -> tuple[dict[str, str], str | None]:
    env = os.environ.copy()
    askpass_path = None
    if config.password:
        fd, askpass_path = tempfile.mkstemp(prefix="process-resource-askpass.")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write('#!/bin/sh\nprintf "%s\\n" "$RESOURCE_SSH_PASSWORD"\n')
        os.chmod(askpass_path, 0o700)
        env["DISPLAY"] = env.get("DISPLAY", ":0")
        env["SSH_ASKPASS"] = askpass_path
        env["SSH_ASKPASS_REQUIRE"] = "force"
        env["RESOURCE_SSH_PASSWORD"] = config.password
    return env, askpass_path


def ssh_command(config: ServerConfig) -> list[str]:
    return [
        "ssh",
        "-p", str(config.port),
        "-o", "BatchMode=no" if config.password else "BatchMode=yes",
        "-o", "ConnectTimeout=45",
        "-o", "StrictHostKeyChecking=accept-new",
        f"{config.user}@{config.host}",
        "sh", "-s",
    ]


def run_remote(config: ServerConfig) -> tuple[int, str, str]:
    env, askpass_path = askpass_env(config)
    try:
        completed = subprocess.run(
            ssh_command(config),
            input=REMOTE_SCRIPT,
            text=True,
            capture_output=True,
            env=env,
            timeout=90,
            check=False,
        )
        return completed.returncode, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        return 124, exc.stdout or "", exc.stderr or "Timeout ao coletar recursos."
    finally:
        if askpass_path:
            Path(askpass_path).unlink(missing_ok=True)


def number(value: Any, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def status_level(server: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    metrics = server.get("metrics", {})
    cores = max(number(metrics.get("cores"), 1), 1)
    load1 = number(metrics.get("load1"))
    idle = number(metrics.get("idlePct"))
    iowait = number(metrics.get("iowaitPct"))
    mem_total = number(metrics.get("memTotalMb"))
    mem_avail = number(metrics.get("memAvailableMb"))
    disk_used = number(metrics.get("rootUsedPct"))
    proc_cpu = sum(number(proc.get("cpuPct")) for proc in server.get("processes", []))
    max_proc_cpu = max((number(proc.get("cpuPct")) for proc in server.get("processes", [])), default=0)

    status = "ok"
    if load1 > cores * 1.5 or idle < 15 or iowait >= 20 or disk_used >= 92 or (mem_total and mem_avail / mem_total < 0.08) or max_proc_cpu >= 90:
        status = "error"
    elif load1 > cores or idle < 35 or iowait >= 8 or disk_used >= 85 or (mem_total and mem_avail / mem_total < 0.18) or max_proc_cpu >= 60 or proc_cpu >= 120:
        status = "warning"

    if load1 > cores:
        reasons.append(f"load {load1:.2f} acima de {cores:.0f} cores")
    if idle < 35:
        reasons.append(f"CPU idle {idle:.0f}%")
    if iowait >= 8:
        reasons.append(f"I/O wait {iowait:.0f}%")
    if disk_used >= 85:
        reasons.append(f"disco {disk_used:.0f}%")
    if mem_total and mem_avail / mem_total < 0.18:
        reasons.append(f"memoria disponivel {mem_avail / 1024:.1f} GiB")
    if max_proc_cpu >= 60:
        reasons.append(f"processo com CPU {max_proc_cpu:.0f}%")
    elif proc_cpu >= 120:
        reasons.append(f"processos somam CPU {proc_cpu:.0f}%")
    return status, reasons


def parse_output(config: ServerConfig, stdout: str, stderr: str, code: int) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    processes: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}
    for line in stdout.splitlines():
        parts = line.split("|")
        if len(parts) < 3:
            continue
        section, key = parts[0], parts[1]
        value = "|".join(parts[2:])
        if section == "META":
            meta[key] = value
        elif section == "MEM":
            metrics["mem" + key[0].upper() + key[1:]] = number(value)
        elif section == "DISK":
            metrics[key] = number(value)
        elif section == "CPU":
            metrics[key] = number(value)
        elif section == "PROC" and len(parts) >= 8:
            _, pid, ppid, etimes, pcpu, pmem, rss, command = parts[:8]
            processes.append({
                "pid": pid,
                "ppid": ppid,
                "elapsedSeconds": int(number(etimes)),
                "cpuPct": number(pcpu),
                "memPct": number(pmem),
                "rssMb": round(number(rss) / 1024, 1),
                "command": command,
            })
    metrics.update({
        "cores": number(meta.get("cores"), 1),
        "load1": number(meta.get("load1")),
        "load5": number(meta.get("load5")),
        "load15": number(meta.get("load15")),
    })
    server = {
        "key": config.key,
        "label": config.label,
        "source": f"{config.user}@{config.host}",
        "host": meta.get("host", config.host),
        "remoteDate": meta.get("date", ""),
        "status": "ok" if code == 0 else "error",
        "details": "",
        "metrics": metrics,
        "processes": processes,
    }
    if code != 0:
        server["details"] = (stderr or stdout or "Falha ao coletar recursos.").strip().splitlines()[-1]
        return server
    status, reasons = status_level(server)
    server["status"] = status
    server["details"] = "; ".join(reasons) if reasons else "Recursos com folga."
    return server


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_status(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    env = load_env()
    servers = []
    for config in server_configs(env):
        if not config.host or not config.user:
            servers.append({
                "key": config.key,
                "label": config.label,
                "source": "",
                "host": config.host,
                "status": "error",
                "details": "Servidor nao configurado no .env.",
                "metrics": {},
                "processes": [],
            })
            continue
        code, stdout, stderr = run_remote(config)
        servers.append(parse_output(config, stdout, stderr, code))
    data = {
        "collector": "process-resource-monitor",
        "updatedAt": iso_now(),
        "servers": servers,
    }
    write_status(DEFAULT_STATUS, data)
    print(f"Monitor recursos/processos atualizado em {DEFAULT_STATUS}")


if __name__ == "__main__":
    main()
