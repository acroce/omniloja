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
DEFAULT_STATUS = ROOT / "outputs" / "pleno_business_monitor" / "pdv_queue.json"
DEFAULT_UPGRADE_DIR = "/servidor/pdv/linux/upgrade"
DEFAULT_RETAG_DIR = "/retag"
DEFAULT_STALE_MINUTES = 15


@dataclass
class ServerConfig:
    key: str
    title: str
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


def server_configs(env: dict[str, str]) -> list[ServerConfig]:
    result: list[ServerConfig] = []
    for key, title, fallback in (
        ("preprod", "Pré Produção", "PROMOPRECO_S1_"),
        ("prod", "Produção", "PROMOPRECO_S2_"),
    ):
        explicit = f"PDV_QUEUE_{key.upper()}_"
        result.append(
            ServerConfig(
                key=key,
                title=env.get(explicit + "TITLE", title),
                host=env.get(explicit + "HOST") or env.get(fallback + "HOST", ""),
                user=env.get(explicit + "USER") or env.get(fallback + "USER", ""),
                port=int(env.get(explicit + "PORT") or env.get(fallback + "PORT", "22") or "22"),
                password=env.get(explicit + "PASSWORD") or env.get(fallback + "PASSWORD", ""),
            )
        )
    return result


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def askpass_env(config: ServerConfig) -> tuple[dict[str, str], str | None]:
    env = os.environ.copy()
    askpass_path = None
    if config.password:
        fd, askpass_path = tempfile.mkstemp(prefix=f"pdv-queue-{config.key}-askpass.", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write('#!/bin/sh\nprintf "%s\\n" "$PDV_QUEUE_SSH_PASSWORD"\n')
        os.chmod(askpass_path, 0o700)
        env.update({
            "DISPLAY": env.get("DISPLAY", ":0"),
            "SSH_ASKPASS": askpass_path,
            "SSH_ASKPASS_REQUIRE": "force",
            "PDV_QUEUE_SSH_PASSWORD": config.password,
        })
    return env, askpass_path


def remote_script(env: dict[str, str]) -> str:
    upgrade_dir = env.get("PDV_QUEUE_UPGRADE_DIR") or DEFAULT_UPGRADE_DIR
    retag_dir = env.get("PDV_QUEUE_RETAG_DIR") or DEFAULT_RETAG_DIR
    max_items = int(env.get("PDV_QUEUE_DETAIL_LIMIT") or "80")
    return f"""
set -eu
python3 - <<'PY'
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

upgrade_dir = Path({sh_quote(upgrade_dir)})
retag_dir = Path({sh_quote(retag_dir)})
max_items = {max_items}
now = datetime.now().astimezone()
today = now.date()

def iso_from_stat(path):
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).astimezone().isoformat(timespec='seconds')

def age_minutes(path):
    return round((now.timestamp() - path.stat().st_mtime) / 60, 1)

def store_from_path(path):
    match = re.search(r'loja(\\d+)', str(path), re.I)
    return str(int(match.group(1))) if match else ''

files = []
if upgrade_dir.exists():
    for path in upgrade_dir.glob('loja*/tab*.tar.gz'):
        try:
            st = path.stat()
        except OSError:
            continue
        changed = datetime.fromtimestamp(st.st_mtime).astimezone()
        if changed.date() != today:
            continue
        files.append({{
            'store': store_from_path(path),
            'file': path.name,
            'path': str(path),
            'mtime': iso_from_stat(path),
            'ageMinutes': age_minutes(path),
            'size': st.st_size,
        }})
files.sort(key=lambda item: item['mtime'], reverse=True)

latest_by_store = {{}}
for item in files:
    latest_by_store.setdefault(item['store'], item)

imports = []
if retag_dir.exists():
    reps = {{}}
    locks = {{}}
    for path in retag_dir.glob('importa.rep.*.txt'):
        match = re.search(r'importa\\.rep\\.(\\d+)\\.txt$', path.name)
        if match:
            reps[str(int(match.group(1)))] = path
    for path in retag_dir.glob('importa.*.lock'):
        match = re.search(r'importa\\.(\\d+)\\.lock$', path.name)
        if match:
            locks[str(int(match.group(1)))] = path
    for store in sorted(set(reps) | set(locks), key=lambda value: int(value)):
        rep = reps.get(store)
        lock = locks.get(store)
        candidates = [item for item in (rep, lock) if item is not None]
        if not candidates:
            continue
        newest = max(candidates, key=lambda item: item.stat().st_mtime)
        if datetime.fromtimestamp(newest.stat().st_mtime).astimezone().date() != today:
            continue
        duration = None
        if rep is not None and lock is not None and rep.stat().st_mtime >= lock.stat().st_mtime:
            duration = round(rep.stat().st_mtime - lock.stat().st_mtime, 1)
        active = lock is not None and (rep is None or lock.stat().st_mtime > rep.stat().st_mtime)
        tail = ''
        if rep is not None:
            try:
                lines = rep.read_text(encoding='latin1', errors='replace').splitlines()
                tail = ' | '.join([line.strip() for line in lines[-4:] if line.strip()])
            except OSError:
                tail = ''
        imports.append({{
            'store': store,
            'lockAt': iso_from_stat(lock) if lock else '',
            'repAt': iso_from_stat(rep) if rep else '',
            'durationSeconds': duration,
            'active': active,
            'ageMinutes': age_minutes(lock if active and lock else newest),
            'summary': tail[:260],
        }})
imports.sort(key=lambda item: item.get('repAt') or item.get('lockAt') or '', reverse=True)

latest_import_by_store = {{}}
for item in imports:
    latest_import_by_store.setdefault(item['store'], item)

def completed_after_file(import_item, file_item):
    if not import_item or not import_item.get('repAt'):
        return False
    if import_item.get('active'):
        return False
    if 'erro na importacao' in str(import_item.get('summary') or '').lower():
        return False
    try:
        return datetime.fromisoformat(import_item['repAt']) >= datetime.fromisoformat(file_item['mtime'])
    except (TypeError, ValueError):
        return False

store_progress = []
for store, file_item in sorted(latest_by_store.items(), key=lambda item: int(item[0] or 0)):
    import_item = latest_import_by_store.get(store)
    updated = completed_after_file(import_item, file_item)
    store_progress.append({{
        'store': store,
        'state': 'updated' if updated else 'pending',
        'file': file_item['file'],
        'fileAt': file_item['mtime'],
        'importedAt': import_item.get('repAt', '') if import_item else '',
        'active': bool(import_item and import_item.get('active')),
        'summary': import_item.get('summary', '') if import_item else '',
    }})

print(json.dumps({{
    'remoteDate': now.isoformat(timespec='seconds'),
    'upgradeDir': str(upgrade_dir),
    'retagDir': str(retag_dir),
    'files': list(latest_by_store.values())[:max_items],
    'fileTotal': len(latest_by_store),
    'imports': imports[:max_items],
    'importTotal': len(imports),
    'storeProgress': store_progress,
}}, ensure_ascii=False))
PY
"""


def run_remote(config: ServerConfig, env: dict[str, str]) -> tuple[int, str, str]:
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
        completed = subprocess.run(
            cmd,
            input=remote_script(env),
            text=True,
            capture_output=True,
            env=proc_env,
            timeout=120,
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


def elapsed_label(seconds: int | float | None) -> str:
    if seconds is None:
        return "-"
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}"
    if seconds >= 60:
        return f"{seconds // 60}min{seconds % 60:02d}s"
    return f"{seconds}s"


def event_from_remote(config: ServerConfig, env: dict[str, str], data: dict[str, Any]) -> dict[str, Any]:
    stale_minutes = int(env.get("PDV_QUEUE_STALE_MINUTES") or DEFAULT_STALE_MINUTES)
    active_imports = [item for item in data.get("imports", []) if item.get("active")]
    stale_imports = [item for item in active_imports if float(item.get("ageMinutes") or 0) >= stale_minutes]
    recent_files = int(data.get("fileTotal") or 0)
    recent_imports = int(data.get("importTotal") or 0)
    store_progress = data.get("storeProgress", [])
    updated_stores = [item for item in store_progress if item.get("state") == "updated"]
    pending_stores = [item for item in store_progress if item.get("state") != "updated"]
    max_import_age = max([float(item.get("ageMinutes") or 0) for item in active_imports] or [0])
    if stale_imports:
        status = "erro"
        details = f"{len(stale_imports)} carga(s) parada(s) ha mais de {stale_minutes} min."
    elif active_imports:
        status = "rodando"
        details = f"{len(active_imports)} carga(s) em andamento."
    elif pending_stores:
        status = "aguardando"
        details = f"{len(pending_stores)} loja(s) aguardando importacao."
    else:
        status = "ok"
        details = "Sem fila parada."
    return {
        "id": f"{config.key}_pdv_queue",
        "targetTime": "00:00",
        "status": status,
        "actualAt": data.get("remoteDate") or iso_now(),
        "source": f"{config.user}@{config.host}",
        "serverKey": config.key,
        "serverTitle": config.title,
        "label": config.title,
        "count": len(active_imports),
        "pendingCount": len(stale_imports),
        "storeTotal": recent_files,
        "storeImported": recent_imports,
        "pdvStoresUpdated": len(updated_stores),
        "pdvStoresPending": len(pending_stores),
        "pdvUpdatedStores": updated_stores,
        "pdvPendingStores": pending_stores,
        "details": details,
        "maxImportAgeMinutes": max_import_age,
        "staleMinutes": stale_minutes,
        "files": data.get("files", []),
        "imports": data.get("imports", []),
        "staleImports": stale_imports,
        "fileTotal": recent_files,
        "importTotal": recent_imports,
        "upgradeDir": data.get("upgradeDir") or DEFAULT_UPGRADE_DIR,
        "retagDir": data.get("retagDir") or DEFAULT_RETAG_DIR,
    }


def build_events(env: dict[str, str]) -> dict[str, Any]:
    events: dict[str, Any] = {}
    for config in server_configs(env):
        if not config.host or not config.user:
            events[f"{config.key}_pdv_queue"] = {
                "id": f"{config.key}_pdv_queue",
                "targetTime": "00:00",
                "status": "sem_acesso",
                "serverKey": config.key,
                "serverTitle": config.title,
                "label": config.title,
                "details": f"Servidor {config.title} nao configurado.",
            }
            continue
        code, stdout, stderr = run_remote(config, env)
        if code != 0:
            detail = (stderr or stdout or "Falha ao conectar no servidor.").strip().splitlines()
            events[f"{config.key}_pdv_queue"] = {
                "id": f"{config.key}_pdv_queue",
                "targetTime": "00:00",
                "status": "sem_acesso",
                "serverKey": config.key,
                "serverTitle": config.title,
                "label": config.title,
                "source": f"{config.user}@{config.host}",
                "details": f"Sem acesso ao servidor: {(detail[-1] if detail else '')[:240]}",
            }
            continue
        data = json.loads(stdout.strip().splitlines()[-1])
        events[f"{config.key}_pdv_queue"] = event_from_remote(config, env, data)
    return events


def write_status(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    env = load_env()
    status_path = Path(env.get("PDV_QUEUE_STATUS_FILE") or DEFAULT_STATUS)
    data = {
        "collector": "pdv-queue-monitor",
        "updatedAt": iso_now(),
        "events": build_events(env),
    }
    write_status(status_path, data)
    print(f"Monitor fila/envio PDV atualizado em {status_path}")


if __name__ == "__main__":
    main()
