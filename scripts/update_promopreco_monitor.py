#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATUS = ROOT / "outputs" / "pleno_business_monitor" / "promopreco.json"
DEFAULT_HISTORY = ROOT / "outputs" / "pleno_business_monitor" / "promopreco_history.json"
DEFAULT_DIRS = ["/servidor/importacao/PROM/", "/servidor/importacao/PROD/"]
DEFAULT_RUNS = ["04:30", "06:30"]


@dataclass
class ServerConfig:
    key: str
    label: str
    host: str
    user: str
    port: int
    password: str
    target: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Atualiza o monitor de promocao e precos.")
    parser.add_argument("--status-file", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--server", choices=["all", "s1", "s2"], default="all")
    return parser.parse_args()


def load_env() -> dict[str, str]:
    env_path = ROOT / ".env"
    env: dict[str, str] = {}
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key] = value.strip().strip('"').strip("'")
    # The container receives the official central environment at runtime.
    # The local file remains only as a fallback for development.
    env.update(os.environ)
    return env


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def add_minutes(time_text: str, minutes: int) -> str:
    base = datetime.strptime(time_text, "%H:%M")
    return (base + timedelta(minutes=minutes)).strftime("%H:%M")


def time_to_minutes(time_text: str) -> int:
    hours, minutes = time_text.split(":", 1)
    return int(hours) * 60 + int(minutes)


def file_time_to_minutes(time_text: str) -> int:
    clean = (time_text or "00:00:00")[:5]
    return time_to_minutes(clean)


def server_configs(env: dict[str, str]) -> list[ServerConfig]:
    result: list[ServerConfig] = []
    for key in ("s1", "s2"):
        prefix = f"PROMOPRECO_{key.upper()}_"
        host = env.get(prefix + "HOST", "")
        user = env.get(prefix + "USER", "")
        if not host or not user:
            result.append(ServerConfig(
                key=key,
                label=env.get(prefix + "LABEL", f"Servidor {key[-1]}"),
                host=host,
                user=user,
                port=int(env.get(prefix + "PORT", "22") or "22"),
                password=env.get(prefix + "PASSWORD", ""),
                target=env.get(prefix + "TARGET", "04:30" if key == "s1" else "04:40"),
            ))
            continue
        result.append(ServerConfig(
            key=key,
            label=env.get(prefix + "LABEL", f"Servidor {key[-1]}"),
            host=host,
            user=user,
            port=int(env.get(prefix + "PORT", "22") or "22"),
            password=env.get(prefix + "PASSWORD", ""),
            target=env.get(prefix + "TARGET", "04:30" if key == "s1" else "04:40"),
        ))
    return result


def configured_dirs(env: dict[str, str]) -> list[str]:
    raw = env.get("PROMOPRECO_DIRS", "")
    dirs = [item.strip() for item in raw.split(",") if item.strip()]
    return dirs or DEFAULT_DIRS


def configured_runs(env: dict[str, str]) -> list[str]:
    raw = env.get("PROMOPRECO_RUNS", "")
    runs = [item.strip() for item in raw.split(",") if item.strip()]
    return runs or DEFAULT_RUNS


def configured_preprod_stores(env: dict[str, str]) -> set[str]:
    raw = env.get("PROMOPRECO_PREPROD_STORE_IDS", "1155,1141,461,1174")
    return {item.strip() for item in raw.split(",") if item.strip()}


def configured_warning_files(env: dict[str, str]) -> set[str]:
    raw = env.get("PROMOPRECO_WARNING_PENDING_FILES", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def configured_window_minutes(env: dict[str, str]) -> int:
    try:
        return max(1, int(env.get("PROMOPRECO_WINDOW_MINUTES", "60") or "60"))
    except ValueError:
        return 60


def configured_run_servers(env: dict[str, str], run_time: str) -> set[str]:
    key = f"PROMOPRECO_RUN_SERVERS_{run_time.replace(':', '')}"
    raw = env.get(key, "all").strip().lower()
    if not raw or raw == "all":
        return {"s1", "s2"}
    return {item.strip() for item in raw.split(",") if item.strip()}


REMOTE_LIST_SCRIPT = r'''
today=$(date +%Y-%m-%d)
tomorrow=$(date -d "$today + 1 day" +%Y-%m-%d 2>/dev/null || date -v+1d +%Y-%m-%d)
for dir in "$@"; do
  if [ -d "$dir" ]; then
    find "$dir" -maxdepth 1 -type f -newermt "$today 00:00:00" ! -newermt "$tomorrow 00:00:00" -printf '%TY-%Tm-%Td|%TH:%TM:%TS|%C+|%p\n' 2>/dev/null
  else
    printf 'MISSING||%s\n' "$dir"
  fi
done
ps -eo pid=,lstart=,args= | awk '/\/retag\/(cargas|cargas2|importa|gerabd)/ && !/awk/ {
  pid=$1
  start=$5
  $1=$2=$3=$4=$5=$6=""
  sub(/^ +/, "")
  printf "PROCESS|%s|%s|%s\n", pid, start, $0
}'
'''


def askpass_env(config: ServerConfig) -> tuple[dict[str, str], str | None]:
    env = os.environ.copy()
    askpass_path = None
    if config.password:
        fd, askpass_path = tempfile.mkstemp(prefix="promopreco-askpass.")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write('#!/bin/sh\nprintf "%s\\n" "$PROMOPRECO_SSH_PASSWORD"\n')
        os.chmod(askpass_path, 0o700)
        env["DISPLAY"] = env.get("DISPLAY", ":0")
        env["SSH_ASKPASS"] = askpass_path
        env["SSH_ASKPASS_REQUIRE"] = "force"
        env["PROMOPRECO_SSH_PASSWORD"] = config.password
    return env, askpass_path


def ssh_base_command(config: ServerConfig) -> list[str]:
    return [
        "ssh",
        "-p", str(config.port),
        "-o", "BatchMode=no" if config.password else "BatchMode=yes",
        "-o", "ConnectTimeout=60",
        "-o", "StrictHostKeyChecking=accept-new",
        f"{config.user}@{config.host}",
    ]


def run_ssh(config: ServerConfig, dirs: list[str]) -> tuple[int, str, str]:
    ssh_cmd = ssh_base_command(config) + ["sh", "-s", "--", *dirs]
    env, askpass_path = askpass_env(config)
    try:
        completed = subprocess.run(
            ssh_cmd,
            input=REMOTE_LIST_SCRIPT,
            text=True,
            capture_output=True,
            env=env,
            timeout=120,
            check=False,
        )
        return completed.returncode, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        details = stderr or stdout or "Timeout ao listar arquivos no servidor."
        return 124, stdout, details
    finally:
        if askpass_path:
            Path(askpass_path).unlink(missing_ok=True)


REMOTE_V2_EVIDENCE_SCRIPT = r'''
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

today = datetime.now().strftime("%Y%m%d")
result = {"available": False, "rounds": {}}
config_path = Path("/home/retag/cws-v2/config.json")
try:
    config = json.loads(config_path.read_text())
    state = Path(config["state"])
    destination = Path(config["destination"])
    publication = json.loads((state / "publication.json").read_text())
    result.update(available=True, state=str(state), destination=str(destination))
    imp_files = {}
    for path in destination.glob(f"imp.{today}*.*"):
        match = re.match(r"^imp\.(\d{8})(\d{4})(\d{2})?\.(.+)$", path.name)
        if match and path.is_file():
            date, minute, second, name = match.groups()
            # Some ARIUS markers carry minute precision only. Preserve that fact instead of inventing seconds.
            imp_files.setdefault(name, []).append((f"{date}T{minute}{second or ''}", path))
    for folder in sorted((state / "rounds").glob(f"{today}-*")):
        receipt_path = folder / "receipt.json"
        try:
            receipt = json.loads(receipt_path.read_text())
        except (OSError, ValueError):
            continue
        round_id = str(receipt.get("roundId") or folder.name)
        if receipt.get("status") != "complete" or not re.fullmatch(rf"{today}-(0430|0630)(-r[1-9]\d*)?", round_id):
            continue
        deliveries = ((publication.get("rounds") or {}).get(round_id) or {}).get("deliveries") or {}
        published = [item for key, item in deliveries.items()
                     if key.startswith("enriched:") and isinstance(item, dict)
                     and item.get("status") == "published"
                     and item.get("receiptId") == receipt.get("receiptId")]
        delivery = max(published, key=lambda item: str(item.get("publishedAt") or ""), default=None)
        expected_hashes = (delivery or {}).get("hashes") or {}
        published_at = str((delivery or {}).get("publishedAt") or "")
        consumed = []
        if published_at and expected_hashes:
            # The imp marker is authoritative only to the minute on older importers.
            published_key = datetime.fromisoformat(published_at).astimezone().strftime("%Y%m%dT%H%M")
            for name, expected_hash in expected_hashes.items():
                candidates = imp_files.get(name, [])
                candidates = [item for item in candidates if item[0][:13] >= published_key]
                if not candidates:
                    continue
                stamp, path = max(candidates, key=lambda item: item[0])
                digest_value = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest_value.update(chunk)
                digest = digest_value.hexdigest()
                consumed.append({"name": name, "at": stamp, "hashMatch": digest == expected_hash})
        result["rounds"][round_id] = {
            "receipt": {"recordedAt": receipt.get("recordedAt", ""), "receiptId": receipt.get("receiptId", ""),
                        "stores": receipt.get("stores", []), "files": len(receipt.get("files", []))},
            "delivery": {"publishedAt": published_at, "deliveryId": (delivery or {}).get("deliveryId", ""),
                         "batchId": (delivery or {}).get("batchId", ""), "files": len(expected_hashes)},
            "consumed": consumed,
        }
except (OSError, ValueError, KeyError, TypeError) as exc:
    result["error"] = str(exc)
print(json.dumps(result))
'''


REMOTE_V2_EVIDENCE_SNAPSHOT_SCRIPT = r'''
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
import sys

snapshot = json.loads(Path(sys.argv[1]).read_text())
if snapshot.get("format") != 1 or snapshot.get("schemaVersion") != 1 or snapshot.get("status") != "ready":
    raise ValueError("Snapshot BaseV2 indisponível ou fora do contrato.")
today = datetime.now().strftime("%Y%m%d")
destination = Path(snapshot["destination"])
result = {"available": True, "destination": str(destination), "rounds": {}}
imp_files = {}
for path in destination.glob(f"imp.{today}*.*"):
    match = re.match(r"^imp\.(\d{8})(\d{4})(\d{2})?\.(.+)$", path.name)
    if match and path.is_file():
        date, minute, second, name = match.groups()
        imp_files.setdefault(name, []).append((f"{date}T{minute}{second or ''}", path))
for round_id, row in (snapshot.get("rounds") or {}).items():
    if not re.fullmatch(rf"{today}-(0430|0630)(-r[1-9]\d*)?", str(round_id)):
        continue
    receipt = row.get("receipt") or {}
    deliveries = row.get("deliveries") or {}
    published = [item for key, item in deliveries.items() if key.startswith("enriched:") and isinstance(item, dict)
                 and item.get("status") == "published" and item.get("receiptId") == receipt.get("receiptId")]
    delivery = max(published, key=lambda item: str(item.get("publishedAt") or ""), default=None)
    hashes = (delivery or {}).get("hashes") or {}
    published_at = str((delivery or {}).get("publishedAt") or "")
    consumed = []
    if published_at and hashes:
        published_key = datetime.fromisoformat(published_at).astimezone().strftime("%Y%m%dT%H%M")
        for name, expected_hash in hashes.items():
            candidates = [item for item in imp_files.get(name, []) if item[0][:13] >= published_key]
            if not candidates:
                continue
            stamp, path = max(candidates, key=lambda item: item[0])
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            consumed.append({"name": name, "at": stamp, "hashMatch": digest.hexdigest() == expected_hash})
    result["rounds"][round_id] = {
        "receipt": {"recordedAt": receipt.get("recordedAt", ""), "receiptId": receipt.get("receiptId", ""),
                    "stores": receipt.get("stores", []), "files": len(receipt.get("files") or [])},
        "delivery": {"publishedAt": published_at, "deliveryId": (delivery or {}).get("deliveryId", ""),
                     "batchId": (delivery or {}).get("batchId", ""), "files": len(hashes)},
        "consumed": consumed,
    }
print(json.dumps(result))
'''


def run_ssh_script(config: ServerConfig, script: str, *args: str) -> tuple[int, str, str]:
    ssh_cmd = ssh_base_command(config) + ["python3", "-", *args]
    env, askpass_path = askpass_env(config)
    try:
        completed = subprocess.run(ssh_cmd, input=script, text=True, capture_output=True, env=env, timeout=180, check=False)
        return completed.returncode, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        return 124, exc.stdout or "", exc.stderr or "Timeout ao consultar evidências da rodada."
    finally:
        if askpass_path:
            Path(askpass_path).unlink(missing_ok=True)


def v2_evidence(config: ServerConfig, env: dict[str, str]) -> dict[str, Any]:
    if config.key != "s2":
        return {}
    snapshot_path = env.get("PROMOPRECO_S2_EVIDENCE_FILE", "").strip()
    script = REMOTE_V2_EVIDENCE_SNAPSHOT_SCRIPT if snapshot_path else REMOTE_V2_EVIDENCE_SCRIPT
    code, stdout, stderr = run_ssh_script(config, script, *([snapshot_path] if snapshot_path else []))
    if code:
        return {"probeError": (stderr or stdout or "Falha ao consultar BaseV2.").strip().splitlines()[-1]}
    try:
        evidence = json.loads(stdout)
        if not evidence.get("available"):
            return {"probeError": evidence.get("error") or "BaseV2 não disponível na ARIUS."}
        return evidence
    except ValueError:
        return {"probeError": "Resposta BaseV2 inválida na ARIUS."}


def parse_remote_listing(output: str, dirs: list[str]) -> dict[str, list[dict[str, str]]]:
    data: dict[str, list[dict[str, str]]] = {directory: [] for directory in dirs}
    for line in output.splitlines():
        if line.startswith("PROCESS|"):
            continue
        parts = line.split("|", 3)
        if len(parts) == 3:
            file_date, file_time, full_path = parts
            change_time = ""
        elif len(parts) == 4:
            file_date, file_time, change_stamp, full_path = parts
            change_time = change_stamp.split("+", 1)[1][:8] if "+" in change_stamp else change_stamp[:8]
        else:
            continue
        if file_date == "MISSING":
            data.setdefault(full_path, [])
            continue
        directory = next((item for item in dirs if full_path.startswith(item.rstrip("/") + "/")), "")
        if not directory:
            continue
        name = Path(full_path).name
        data.setdefault(directory, []).append({
            "name": name,
            "path": full_path,
            "date": file_date,
            "time": file_time[:8],
            "changeTime": change_time,
        })
    return data


def parse_remote_processes(output: str) -> list[dict[str, str]]:
    processes: list[dict[str, str]] = []
    for line in output.splitlines():
        if not line.startswith("PROCESS|"):
            continue
        parts = line.split("|", 3)
        if len(parts) != 4:
            continue
        _, pid, start_time, command = parts
        processes.append({
            "pid": pid.strip(),
            "startTime": start_time.strip()[:8],
            "command": command.strip(),
        })
    return processes


def file_store_id(name: str) -> str:
    clean = re.sub(r"^imp\.\d+\.", "", name)
    match = re.match(r"^(\d{1,5})[_-]", clean)
    return match.group(1) if match else ""


def store_allowed(config: ServerConfig, name: str, preprod_stores: set[str]) -> bool:
    store_id = file_store_id(name)
    if config.key == "s1":
        return store_id in preprod_stores
    if config.key == "s2":
        return store_id not in preprod_stores
    return True


def imported_base_name(name: str) -> str:
    return re.sub(r"^imp\.\d+\.", "", name)


def imported_timestamp_from_name(name: str) -> str:
    match = re.match(r"^imp\.(\d{8})(\d{4})(\d{2})?\.", name)
    if not match:
        return ""
    _, hour_minute, seconds = match.groups()
    return f"{hour_minute[:2]}:{hour_minute[2:]}:{seconds or '00'}"


def classify_files(
    files_by_dir: dict[str, list[dict[str, str]]],
    start_time: str,
    end_time: str,
    config: ServerConfig,
    preprod_stores: set[str],
) -> dict[str, Any]:
    today = datetime.now().strftime("%Y-%m-%d")
    start_minutes = time_to_minutes(start_time)
    end_minutes = time_to_minutes(end_time)
    folders: list[dict[str, Any]] = []
    pending: list[str] = []
    imported: list[str] = []
    window_files: list[str] = []
    file_times: list[str] = []
    imported_change_times: list[str] = []
    ignored_store = 0
    for directory, files in files_by_dir.items():
        dir_originals: list[dict[str, str]] = []
        dir_imported: list[str] = []
        dir_times: list[str] = []
        dir_imported_change_times: list[str] = []
        dir_ignored_store = 0
        for item in files:
            name = item["name"]
            if item["date"] != today:
                continue
            item_minutes = file_time_to_minutes(item.get("time", "00:00"))
            if item_minutes < start_minutes:
                continue
            if item_minutes >= end_minutes:
                continue
            if not store_allowed(config, name, preprod_stores):
                ignored_store += 1
                dir_ignored_store += 1
                continue
            window_files.append(name)
            item_time = item.get("time", "")[:8]
            if item_time:
                dir_times.append(item_time)
                file_times.append(item_time)
            if name.startswith("imp."):
                dir_imported.append(name)
                imported.append(name)
                imported_time = imported_timestamp_from_name(name) or item.get("changeTime", "")[:8]
                if imported_time:
                    dir_imported_change_times.append(imported_time)
                    imported_change_times.append(imported_time)
            else:
                dir_originals.append(item)
        imported_bases = {imported_base_name(name) for name in dir_imported}
        dir_pending = [item["name"] for item in dir_originals if item["name"] not in imported_bases]
        pending.extend(dir_pending)
        folders.append({
            "dir": directory,
            "today": len(dir_originals) + len(dir_imported),
            "pending": dir_pending,
            "imported": dir_imported,
            "originalCount": len(dir_originals),
            "originalWithImportedCount": len(dir_originals) - len(dir_pending),
            "ignoredStore": dir_ignored_store,
            "firstTime": min(dir_times) if dir_times else "",
            "lastTime": max(dir_times) if dir_times else "",
            "lastImportedAt": max(dir_imported_change_times) if dir_imported_change_times else "",
        })
    return {
        "folders": folders,
        "today": window_files,
        "pending": pending,
        "imported": imported,
        "ignoredStore": ignored_store,
        "startTime": start_time,
        "endTime": f"{end_minutes // 60:02d}:{end_minutes % 60:02d}",
        "firstTime": min(file_times) if file_times else "",
        "lastTime": max(file_times) if file_times else "",
        "lastImportedAt": max(imported_change_times) if imported_change_times else "",
    }


def store_ids(names: list[str]) -> list[str]:
    return sorted({store_id for name in names if (store_id := file_store_id(name))}, key=lambda item: int(item) if item.isdigit() else item)


def format_stores(stores: list[str], limit: int = 12) -> str:
    if not stores:
        return ""
    visible = stores[:limit]
    suffix = f" (+{len(stores) - limit})" if len(stores) > limit else ""
    return f"Lojas: {', '.join(visible)}{suffix}."


def folder_stats(folders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stats: list[dict[str, Any]] = []
    for folder in folders:
        stats.append({
            "folder": Path(folder["dir"].rstrip("/")).name,
            "dir": folder["dir"],
            "count": folder["today"],
            "pendingCount": len(folder["pending"]),
            "importedCount": len(folder["imported"]),
            "originalCount": folder.get("originalCount", 0),
            "originalWithImportedCount": folder.get("originalWithImportedCount", 0),
            "firstFileTime": folder["firstTime"],
            "lastFileTime": folder["lastTime"],
            "lastImportedAt": folder.get("lastImportedAt", ""),
        })
    return stats


def event(
    status: str,
    target: str,
    source: str,
    details: str,
    count: int = 0,
    pending_count: int | str = "",
    imported_count: int | str = "",
    first_file_time: str = "",
    last_file_time: str = "",
    last_imported_at: str = "",
    pending_stores: list[str] | None = None,
    folder_stats_value: list[dict[str, Any]] | None = None,
    process_running: bool = False,
    process_details: list[dict[str, str]] | None = None,
    store_total: int | str = "",
    store_imported: int | str = "",
    store_pending: int | str = "",
    actual_at_override: str = "",
) -> dict[str, Any]:
    # actualAt is evidence of completion, never the time this monitor happened to run.
    actual_at = actual_at_override
    return {
        "targetTime": target,
        "status": status,
        "actualAt": actual_at,
        "count": count,
        "pendingCount": pending_count,
        "importedCount": imported_count,
        "firstFileTime": first_file_time,
        "lastFileTime": last_file_time,
        "lastImportedAt": last_imported_at,
        "pendingStores": pending_stores or [],
        "folderStats": folder_stats_value or [],
        "processRunning": process_running,
        "processDetails": process_details or [],
        "processStartTime": min((item.get("startTime", "") for item in (process_details or []) if item.get("startTime")), default=""),
        "storeTotal": store_total,
        "storeImported": store_imported,
        "storePending": store_pending,
        "source": source,
        "details": details,
    }


def target_has_passed(target: str) -> bool:
    try:
        return datetime.now().hour * 60 + datetime.now().minute >= time_to_minutes(target)
    except (ValueError, AttributeError):
        return True


def server_target_time(config: ServerConfig, run_time: str) -> str:
    return add_minutes(run_time, 30)


def build_server_error_events(
    config: ServerConfig,
    runs: list[str],
    detail: str,
    source: str = "",
    status: str = "error",
) -> dict[str, dict[str, Any]]:
    events: dict[str, dict[str, Any]] = {}
    for run_time in runs:
        run_key = run_time.replace(":", "")
        prefix = f"r{run_key}_{config.key}_"
        target = server_target_time(config, run_time)
        events[prefix + "arquivos_pasta"] = event(status, target, source, detail)
        events[prefix + "arquivo_importado"] = event(status, add_minutes(target, 5), source, detail)
    return events


def build_stage_pair(
    config: ServerConfig,
    run_time: str,
    window_start: str,
    window_end: str,
    files_by_dir: dict[str, list[dict[str, str]]],
    source: str,
    preprod_stores: set[str],
    warning_files: set[str],
    process_details: list[dict[str, str]],
) -> dict[str, dict[str, Any]]:
    run_key = run_time.replace(":", "")
    prefix = f"r{run_key}_{config.key}_"
    target = server_target_time(config, run_time)
    classified = classify_files(files_by_dir, window_start, window_end, config, preprod_stores)
    pending = classified["pending"]
    hard_pending = [name for name in pending if name not in warning_files]
    warning_pending = [name for name in pending if name in warning_files]
    imported = classified["imported"]
    process_running = bool(process_details)
    process_pending = process_running and bool(hard_pending)
    process_text = "; ".join(
        f"{item.get('startTime', '-')}: {item.get('command', '')}" for item in process_details[:3]
    )
    process_suffix = f" Processo ativo: {process_text}" if process_pending else ""
    today = classified["today"]
    pending_stores = store_ids(hard_pending)
    all_stores = store_ids(today)
    pending_store_set = set(pending_stores)
    imported_store_count = max(0, len([store for store in all_stores if store not in pending_store_set]))
    store_summary = f" {format_stores(pending_stores)}" if pending_stores else ""
    folders_stats = folder_stats(classified["folders"])
    folder_summary = "; ".join(
        f"{folder['dir']}: {folder['today']} na janela, {len(folder['pending'])} pendente(s), {len(folder['imported'])} importado(s), {folder['ignoredStore']} ignorado(s) por loja, hora {folder['firstTime'] or '-'} a {folder['lastTime'] or '-'}"
        for folder in classified["folders"]
    )
    time_summary = f" Janela {classified['startTime']} a {classified['endTime']}. Hora arquivos {classified['firstTime'] or '-'} a {classified['lastTime'] or '-'}."
    store_filter = (
        f" Filtro lojas Pre Producao: apenas {', '.join(sorted(preprod_stores))}."
        if config.key == "s1"
        else f" Filtro Producao: ignorando lojas {', '.join(sorted(preprod_stores))}."
    )

    folders_with_today = [folder for folder in classified["folders"] if folder["today"] > 0]
    missing_today = [folder["dir"] for folder in classified["folders"] if folder["today"] == 0]

    if len(folders_with_today) == len(classified["folders"]):
        file_stage = event(
            "ok",
            target,
            source,
            f"Arquivos encontrados na rodada {run_time}.{time_summary}{store_filter}{store_summary} {folder_summary}",
            len(today),
            len(hard_pending),
            len(imported),
            classified["firstTime"],
            classified["lastTime"],
            classified["lastImportedAt"],
            pending_stores,
            folders_stats,
            False,
            [],
            len(all_stores),
            imported_store_count,
            len(pending_stores),
            time_as_today(classified["lastTime"]),
        )
    elif pending:
        file_stage = event(
            "error",
            target,
            source,
            f"Arquivo encontrado parcialmente na rodada {run_time}.{time_summary}{store_filter}{store_summary} Sem arquivo em: {', '.join(missing_today)}. {folder_summary}",
            len(today),
            len(pending),
            len(imported),
            classified["firstTime"],
            classified["lastTime"],
            classified["lastImportedAt"],
            pending_stores,
            folders_stats,
            False,
            [],
            len(all_stores),
            imported_store_count,
            len(pending_stores),
        )
    elif imported:
        file_stage = event(
            "ok",
            target,
            source,
            f"Arquivos importados encontrados na rodada {run_time}, sem pendencia sem imp.{time_summary}{store_filter} Sem arquivo em: {', '.join(missing_today)}. {folder_summary}",
            len(today),
            0,
            len(imported),
            classified["firstTime"],
            classified["lastTime"],
            classified["lastImportedAt"],
            [],
            folders_stats,
            False,
            [],
            len(all_stores),
            imported_store_count,
            0,
            time_as_today(classified["lastTime"]),
        )
    else:
        file_stage = event(
            "error" if target_has_passed(target) else "aguardando",
            target,
            source,
            f"Nenhum arquivo encontrado na janela da rodada {run_time}. {folder_summary}",
            0,
            0,
            0,
            "",
            "",
            "",
            [],
            folders_stats,
            False,
            [],
            0,
            0,
            0,
        )

    folders_with_imported = [folder for folder in classified["folders"] if len(folder["imported"]) > 0]
    missing_imported = [folder["dir"] for folder in classified["folders"] if len(folder["imported"]) == 0]

    if imported and not hard_pending and len(folders_with_imported) == len(classified["folders"]):
        status = "ok"
        details = f"Arquivos importados da rodada {run_time}: {', '.join(imported[:8])}"
        if warning_pending:
            details = f"Rodada {run_time}: promos importadas; atencao para arquivo sem imp tratado como excecao: {', '.join(warning_pending)}"
        import_stage = event(
            status,
            add_minutes(target, 5),
            source,
            details,
            len(imported),
            len(warning_pending),
            len(imported),
            classified["firstTime"],
            classified["lastTime"],
            classified["lastImportedAt"],
            [],
            folders_stats,
            process_pending,
            process_details if process_pending else [],
            len(all_stores),
            imported_store_count,
            len(warning_pending),
            time_as_today(classified["lastImportedAt"]),
        )
    elif hard_pending:
        status = "running" if process_pending else "error"
        running_note = " Processo ainda ativo; aguardando finalizar importacao." if process_pending else ""
        import_stage = event(
            status,
            add_minutes(target, 5),
            source,
            f"Rodada {run_time}: ainda existem pendentes sem imp.{running_note} {format_stores(pending_stores)} Arquivos: {', '.join(hard_pending[:8])}",
            len(hard_pending),
            len(hard_pending),
            len(imported),
            classified["firstTime"],
            classified["lastTime"],
            classified["lastImportedAt"],
            pending_stores,
            folders_stats,
            process_pending,
            process_details if process_pending else [],
            len(all_stores),
            imported_store_count,
            len(pending_stores),
        )
    elif imported:
        status = "ok"
        details = f"Rodada {run_time}: importados encontrados e nenhuma pendencia sem imp. Sem arquivo em: {', '.join(missing_imported)}. Importados: {', '.join(imported[:8])}"
        import_stage = event(
            status,
            add_minutes(target, 5),
            source,
            details,
            len(imported),
            0,
            len(imported),
            classified["firstTime"],
            classified["lastTime"],
            classified["lastImportedAt"],
            [],
            folders_stats,
            False,
            [],
            len(all_stores),
            imported_store_count,
            0,
            time_as_today(classified["lastImportedAt"]),
        )
    else:
        status = "error" if target_has_passed(add_minutes(target, 5)) else "aguardando"
        details = f"Rodada {run_time}: nenhum arquivo importado na janela."
        import_stage = event(
            status,
            add_minutes(target, 5),
            source,
            details,
            0,
            0,
            0,
            "",
            "",
            "",
            [],
            folders_stats,
            process_pending,
            process_details if process_pending else [],
            len(all_stores),
            imported_store_count,
            len(pending_stores),
        )

    if process_pending:
        process_status = "running"
        process_details_text = f"Processos da rodada {run_time} ainda ativos.{process_suffix}"
    elif import_stage["status"] in {"error", "sem_acesso"}:
        process_status = "error"
        process_details_text = f"Importacao da rodada {run_time} nao foi concluida; nenhum processo ativo no momento."
    elif import_stage["status"] in {"running", "aguardando", "warning"}:
        process_status = "warning"
        process_details_text = f"Importacao da rodada {run_time} ainda pendente; nenhum processo ativo no momento."
    else:
        process_status = "ok"
        process_details_text = f"Nenhum processo pendente da rodada {run_time}."

    process_stage = event(
        process_status,
        target,
        source,
        process_details_text,
        len(process_details) if process_pending else 0,
        0,
        len(imported),
        classified["firstTime"],
        classified["lastTime"],
        classified["lastImportedAt"],
        [],
        folders_stats,
        process_pending,
        process_details if process_pending else [],
        len(all_stores),
        imported_store_count,
        len(pending_stores),
        time_as_today(classified["lastImportedAt"]) if process_status == "ok" else "",
    )

    return {
        prefix + "arquivos_pasta": file_stage,
        prefix + "arquivo_importado": import_stage,
        prefix + "processo_carga": process_stage,
    }


def mark_coverage_unverified(events: dict[str, dict[str, Any]], evidence_error: str = "") -> dict[str, dict[str, Any]]:
    """Avoid definitive cycle claims when only an ungrouped direct listing is available."""
    coverage_note = "Cobertura global por grupo de carga aguardando confirmacao."
    for item in events.values():
        details = str(item.get("details", ""))
        if item.get("status") == "ok":
            item["status"] = "warning"
            item["details"] = f"{details} Evidencia direta encontrada; {coverage_note}".strip()
        elif item.get("status") == "error":
            item["status"] = "warning"
            item["details"] = (
                "A leitura direta da ARIUS ainda nao comprovou a cobertura completa "
                f"da rodada. {details} {coverage_note}"
            ).strip()
        if evidence_error:
            item["details"] = f"{item.get('details', '')} Controle oficial indisponivel: {evidence_error}".strip()
    return events


def processes_for_run(
    processes: list[dict[str, str]],
    config: ServerConfig,
    run_time: str,
    runs: list[str],
) -> list[dict[str, str]]:
    target_minutes = time_to_minutes(run_time)
    ordered_runs = sorted(runs, key=time_to_minutes)
    next_target_minutes = target_minutes + 120
    for item in ordered_runs:
        if time_to_minutes(item) > time_to_minutes(run_time):
            next_target_minutes = time_to_minutes(item)
            break
    scoped: list[dict[str, str]] = []
    for process in processes:
        start_time = process.get("startTime", "")
        if not re.match(r"^\d{2}:\d{2}", start_time):
            continue
        start_minutes = file_time_to_minutes(start_time)
        if start_minutes < target_minutes:
            continue
        if next_target_minutes is not None and start_minutes >= next_target_minutes:
            continue
        scoped.append(process)
    return scoped


def v2_time_as_today(value: str) -> str:
    if not re.fullmatch(r"\d{8}T\d{4}(\d{2})?", str(value or "")):
        return ""
    seconds = f":{value[13:15]}" if len(value) == 15 else ""
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}T{value[9:11]}:{value[11:13]}{seconds}{datetime.now().astimezone().strftime('%z')[:3]}:{datetime.now().astimezone().strftime('%z')[3:]}"


def build_v2_stage_pair(config: ServerConfig, run_time: str, source: str, evidence: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    candidates = [(round_id, item) for round_id, item in (evidence.get("rounds") or {}).items()
                  if re.match(rf"^{datetime.now().strftime('%Y%m%d')}-{run_time.replace(':', '')}(-r[1-9]\d*)?$", round_id)]
    if not candidates:
        return None
    # A published revision is the operational record for the round; numeric revisions must sort r10 after r9.
    def record_order(pair: tuple[str, dict[str, Any]]) -> tuple[bool, str, int]:
        round_id, item = pair
        revision = re.search(r"-r(\d+)$", round_id)
        return (bool((item.get("delivery") or {}).get("publishedAt")),
                str((item.get("delivery") or {}).get("publishedAt") or ""), int(revision.group(1)) if revision else 0)
    round_id, record = max(candidates, key=record_order)
    receipt = record.get("receipt") or {}
    delivery = record.get("delivery") or {}
    if not receipt.get("receiptId"):
        return None
    target = server_target_time(config, run_time)
    prefix = f"r{run_time.replace(':', '')}_{config.key}_"
    stores = [str(store) for store in receipt.get("stores") or []]
    expected = int(delivery.get("files") or 0)
    consumed = [item for item in record.get("consumed") or [] if item.get("hashMatch")]
    invalid = [item for item in record.get("consumed") or [] if not item.get("hashMatch")]
    consumed_names = {item.get("name") for item in consumed}
    pending_names = [item.get("name") for item in record.get("consumed") or [] if not item.get("hashMatch")]
    missing_count = max(0, expected - len(consumed_names))
    consumed_stores = {file_store_id(name) for name in consumed_names if file_store_id(name)}
    pending_stores = sorted(set(stores) - consumed_stores, key=lambda item: int(item) if item.isdigit() else item)
    imported_at = max((item.get("at", "") for item in consumed), default="")
    receipt_at = str(receipt.get("recordedAt") or "")
    publication_at = str(delivery.get("publishedAt") or "")
    source_detail = f"BaseV2 {round_id}; recibo {receipt.get('receiptId', '')[:12]}; {len(stores)} lojas, {receipt.get('files', 0)} arquivos."
    file_stage = event("ok", target, source, f"Cópia validada. {source_detail}", int(receipt.get("files") or 0),
                       0, 0, "", "", "", [], [], False, [], len(stores), 0, len(stores), receipt_at)
    if not publication_at:
        import_stage = event("warning" if target_has_passed(add_minutes(target, 5)) else "aguardando", add_minutes(target, 5), source,
                             f"Cópia validada, aguardando publicação enriquecida. {source_detail}", 0, expected, 0,
                             "", "", "", stores, [], False, [], len(stores), 0, len(stores))
        process_stage = event("warning", target, source, "Publicação ainda não confirmada; consumo ARIUS não pode ser avaliado.",
                              0, expected, 0, pending_stores=stores, store_total=len(stores), store_imported=0, store_pending=len(stores))
    elif expected and missing_count == 0 and not invalid:
        detail = (f"Publicado {format_v2_time(publication_at)}; consumo ARIUS confirmado {len(consumed_names)}/{expected} por hash. "
                  f"Lojas importadas {len(consumed_stores)}/{len(stores)}. A confirmação no PDV é uma etapa separada.")
        import_stage = event("ok", add_minutes(target, 5), source, detail, len(consumed_names), 0, len(consumed_names),
                             "", "", imported_at, [], [], False, [], len(stores), len(consumed_stores), 0, v2_time_as_today(imported_at))
        process_stage = event("ok", target, source, detail, 0, 0, len(consumed_names), "", "", imported_at,
                              [], [], False, [], len(stores), len(consumed_stores), 0, v2_time_as_today(imported_at))
    else:
        detail = (f"Publicado {format_v2_time(publication_at)}; consumo ARIUS {len(consumed_names)}/{expected}. "
                  f"Pendentes: {', '.join(pending_stores[:12]) or missing_count}." + (" Hash divergente detectado." if invalid else ""))
        status = "error" if invalid else "running"
        import_stage = event(status, add_minutes(target, 5), source, detail, len(consumed_names), missing_count, len(consumed_names),
                             "", "", imported_at, pending_stores, [], status == "running", [], len(stores), len(consumed_stores), len(pending_stores))
        process_stage = event(status, target, source, detail, 0, missing_count, len(consumed_names), "", "", imported_at,
                              pending_stores, [], status == "running", [], len(stores), len(consumed_stores), len(pending_stores))
    result = {prefix + "arquivos_pasta": file_stage, prefix + "arquivo_importado": import_stage, prefix + "processo_carga": process_stage}
    for event_data in result.values():
        event_data.update(evidenceKind="basev2", roundId=round_id, receiptId=receipt.get("receiptId", ""),
                          deliveryId=delivery.get("deliveryId", ""), evidenceAt=event_data.get("actualAt", ""))
    return result


def format_v2_time(value: str) -> str:
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%H:%M")
    except ValueError:
        return value or "-"


def build_server_events(config: ServerConfig, env: dict[str, str], dirs: list[str], runs: list[str], preprod_stores: set[str]) -> dict[str, dict[str, Any]]:
    if not config.host or not config.user:
        details = "Servidor ainda nao configurado no .env."
        return build_server_error_events(config, runs, details)

    code, stdout, stderr = run_ssh(config, dirs)
    source = f"{config.user}@{config.host}"
    if code != 0:
        details = (stderr or stdout or "Falha ao conectar no servidor.").strip().splitlines()[-1]
        return build_server_error_events(config, runs, details, source, "sem_acesso")

    files_by_dir = parse_remote_listing(stdout, dirs)
    process_details = parse_remote_processes(stdout)
    v2 = v2_evidence(config, env)
    warning_files = configured_warning_files(env)
    events: dict[str, dict[str, Any]] = {}
    for index, run_time in enumerate(runs):
        if config.key not in configured_run_servers(env, run_time):
            continue
        v2_events = build_v2_stage_pair(config, run_time, source, v2)
        if v2_events:
            events.update(v2_events)
            continue
        # BaseV2 is the authoritative source whenever it is available.  A
        # connector failure must not be reported to operators as if no file
        # had arrived: retain the direct ARIUS check as a visible contingency.
        # A round can still be copying/importing after its nominal deadline,
        # so scan until the next round instead of truncating it after 30 min.
        window_start = run_time
        later_runs = [candidate for candidate in runs if time_to_minutes(candidate) > time_to_minutes(run_time)]
        window_end = min(later_runs, key=time_to_minutes) if later_runs else add_minutes(run_time, 120)
        target_minutes = time_to_minutes(run_time)
        current_minutes = datetime.now().hour * 60 + datetime.now().minute
        active_process_details = processes_for_run(process_details, config, run_time, runs) if current_minutes >= target_minutes else []
        fallback_events = build_stage_pair(
            config,
            run_time,
            window_start,
            window_end,
            files_by_dir,
            source,
            preprod_stores,
            warning_files,
            active_process_details,
        )
        if config.key == "s2" and v2.get("probeError"):
            fallback_events = mark_coverage_unverified(fallback_events, str(v2["probeError"]))
        events.update(fallback_events)
    return events


def load_status(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {"collector": "promopreco-monitor", "events": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def write_status(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_history(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {"days": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def write_history(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def status_is_from_today(status: dict[str, Any]) -> bool:
    value = str(status.get("updatedAt") or "")
    return value.startswith(datetime.now().strftime("%Y-%m-%d"))


def frozen_runs(status: dict[str, Any], runs: list[str]) -> set[str]:
    """Keep a completed cycle as the historical record once the next one starts."""
    if not status_is_from_today(status):
        return set()
    ordered = sorted(runs, key=time_to_minutes)
    now_minutes = datetime.now().hour * 60 + datetime.now().minute
    events = status.get("events") or {}
    frozen: set[str] = set()
    for index, run_time in enumerate(ordered[:-1]):
        next_run = ordered[index + 1]
        prefix = f"r{run_time.replace(':', '')}_"
        cycle_events = [event for key, event in events.items() if key.startswith(prefix) and isinstance(event, dict)]
        is_terminal = bool(cycle_events) and all(event.get("status") == "ok" for event in cycle_events)
        if now_minutes >= time_to_minutes(next_run) and is_terminal:
            frozen.add(run_time)
    return frozen


def time_as_today(value: str) -> str:
    clean = str(value or "")[:8]
    if not re.match(r"^\d{2}:\d{2}:\d{2}$", clean):
        return ""
    return f"{datetime.now().strftime('%Y-%m-%d')}T{clean}{datetime.now().astimezone().strftime('%z')[:3]}:{datetime.now().astimezone().strftime('%z')[3:]}"


def freeze_cycle_events(status: dict[str, Any], run_time: str) -> None:
    prefix = f"r{run_time.replace(':', '')}_"
    frozen_at = iso_now()
    for key, event_data in (status.get("events") or {}).items():
        if not key.startswith(prefix) or not isinstance(event_data, dict):
            continue
        if event_data.get("evidenceKind") == "basev2":
            evidence_at = event_data.get("evidenceAt") or event_data.get("actualAt") or ""
            event_data["cycleStartedAt"] = event_data.get("cycleStartedAt") or evidence_at
            event_data["cycleFinishedAt"] = evidence_at
            event_data["cycleFrozenAt"] = frozen_at
            event_data["cycleFrozen"] = True
            continue
        started_at = event_data.get("cycleStartedAt") or time_as_today(event_data.get("firstFileTime", "")) or event_data.get("actualAt", "")
        if key.endswith("_arquivos_pasta"):
            evidence_at = time_as_today(event_data.get("lastFileTime", ""))
        else:
            evidence_at = time_as_today(event_data.get("lastImportedAt", ""))
        finished_at = evidence_at
        event_data["cycleStartedAt"] = started_at
        event_data["cycleFinishedAt"] = finished_at
        event_data["cycleFrozenAt"] = frozen_at
        event_data["cycleFrozen"] = True


def normalize_frozen_evidence(status: dict[str, Any]) -> None:
    """Repair frozen cycles from their stored file evidence, not later checks."""
    for key, event_data in (status.get("events") or {}).items():
        if not isinstance(event_data, dict) or not event_data.get("cycleFrozen"):
            continue
        if event_data.get("evidenceKind") == "basev2":
            evidence_at = event_data.get("evidenceAt") or event_data.get("actualAt") or ""
            event_data["actualAt"] = evidence_at
            event_data["cycleFinishedAt"] = evidence_at
            continue
        run_match = re.match(r"^r(\d{2})(\d{2})_", key)
        if run_match:
            run_time = f"{run_match.group(1)}:{run_match.group(2)}"
            event_data["targetTime"] = add_minutes(run_time, 35 if key.endswith("_arquivo_importado") else 30)
        if event_data.get("status") != "ok":
            continue
        if key.endswith("_arquivos_pasta"):
            evidence_at = time_as_today(event_data.get("lastFileTime", ""))
        else:
            evidence_at = time_as_today(event_data.get("lastImportedAt", ""))
        event_data["actualAt"] = evidence_at
        event_data["cycleFinishedAt"] = evidence_at


def warning_files_in_details(details: str) -> list[str]:
    match = re.search(r"Arquivos:\s*(.+)$", str(details or ""))
    if not match:
        return []
    return [item.strip() for item in match.group(1).split(",") if item.strip()]


def normalize_warning_only_events(status: dict[str, Any], warning_files: set[str]) -> None:
    if not warning_files:
        return
    for key, event_data in (status.get("events") or {}).items():
        if not key.endswith("_arquivo_importado") or not isinstance(event_data, dict):
            continue
        if event_data.get("status") not in {"error", "running"}:
            continue
        pending_files = warning_files_in_details(event_data.get("details", ""))
        if not pending_files or any(name not in warning_files for name in pending_files):
            continue
        if event_data.get("pendingStores"):
            continue
        run_time = f"{key[1:3]}:{key[3:5]}" if re.match(r"^r\d{4}_", key) else ""
        prefix = f"Rodada {run_time}: " if run_time else ""
        event_data["status"] = "warning"
        event_data["pendingCount"] = len(pending_files)
        event_data["storePending"] = 0
        event_data["processRunning"] = False
        event_data["processDetails"] = []
        event_data["details"] = (
            f"{prefix}promos importadas; atencao para arquivo sem imp tratado como excecao: "
            f"{', '.join(pending_files)}"
        )


def update_history(status: dict[str, Any], path: Path = DEFAULT_HISTORY) -> None:
    history = load_history(path)
    days = history.setdefault("days", {})
    today = datetime.now().strftime("%Y-%m-%d")
    day = days.setdefault(today, {})
    day["updatedAt"] = status.get("updatedAt", iso_now())
    events = day.setdefault("events", {})
    for key, event_data in status.get("events", {}).items():
        if not key.endswith("_arquivo_importado"):
            continue
        events[key] = {
            "status": event_data.get("status", ""),
            "count": event_data.get("count", 0),
            "pendingCount": event_data.get("pendingCount", 0),
            "importedCount": event_data.get("importedCount", 0),
            "folderStats": event_data.get("folderStats", []),
            "firstFileTime": event_data.get("firstFileTime", ""),
            "lastFileTime": event_data.get("lastFileTime", ""),
            "lastImportedAt": event_data.get("lastImportedAt", ""),
            "processRunning": event_data.get("processRunning", False),
            "processDetails": event_data.get("processDetails", []),
        }
    write_history(path, history)


def main() -> None:
    args = parse_args()
    env = load_env()
    dirs = configured_dirs(env)
    runs = configured_runs(env)
    preprod_stores = configured_preprod_stores(env)
    configs = server_configs(env)
    selected = configs if args.server == "all" else [item for item in configs if item.key == args.server]
    status = load_status(args.status_file)
    frozen = frozen_runs(status, runs)
    status["collector"] = "promopreco-monitor"
    status["updatedAt"] = iso_now()
    status.setdefault("events", {})
    for run_time in frozen:
        freeze_cycle_events(status, run_time)
    normalize_frozen_evidence(status)
    for old_key in ("s1_base_pdv", "s2_base_pdv", "s1_arquivos_pasta", "s1_arquivo_importado", "s2_arquivos_pasta", "s2_arquivo_importado"):
        status["events"].pop(old_key, None)
    keys_to_remove = []
    selected_keys = {item.key for item in selected}
    for key in status["events"]:
        if not re.match(r"^r\d{4}_s[12]_", key):
            continue
        run_time = f"{key[1:3]}:{key[3:5]}"
        if run_time in frozen:
            continue
        if args.server == "all" or any(f"_{server_key}_" in key for server_key in selected_keys):
            keys_to_remove.append(key)
    for key in keys_to_remove:
        status["events"].pop(key, None)
    for config in selected:
        generated_events = build_server_events(config, env, dirs, runs, preprod_stores)
        for key, event_data in generated_events.items():
            run_time = f"{key[1:3]}:{key[3:5]}"
            if run_time not in frozen:
                status["events"][key] = event_data
    normalize_warning_only_events(status, configured_warning_files(env))
    write_status(args.status_file, status)
    update_history(status)
    print(f"Monitor promocao/precos atualizado em {args.status_file}")


if __name__ == "__main__":
    main()
