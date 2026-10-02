#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REMOTE_DIR = "/servpleno/importacao/NFE/rejeitado"
MAX_XML_BYTES = 2 * 1024 * 1024


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


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def remote_config(env: dict[str, str]) -> tuple[str, str, str, str]:
    user = env.get("NOTAS_REJEITADAS_REMOTE_USER") or env.get("STOCK_REMOTE_USER") or ""
    host = env.get("NOTAS_REJEITADAS_REMOTE_HOST") or env.get("STOCK_REMOTE_HOST") or ""
    port = env.get("NOTAS_REJEITADAS_REMOTE_PORT") or env.get("STOCK_REMOTE_PORT") or "22"
    password = env.get("NOTAS_REJEITADAS_REMOTE_PASSWORD") or env.get("STOCK_REMOTE_PASSWORD") or ""
    if not user or not host:
        raise SystemExit("Configure NOTAS_REJEITADAS_REMOTE_USER/HOST ou STOCK_REMOTE_USER/HOST.")
    return user, host, port, password


def validate_filename(value: str) -> str:
    filename = Path(value).name
    if not filename or filename != value or "/" in value or "\\" in value or ".." in value:
        raise SystemExit("Nome de arquivo invalido.")
    if not filename.lower().endswith(".xml"):
        raise SystemExit("Informe um arquivo XML.")
    return filename


def fetch_xml(env: dict[str, str], filename: str) -> dict[str, Any]:
    user, host, port, password = remote_config(env)
    remote_dir = env.get("NOTAS_REJEITADAS_REMOTE_DIR") or DEFAULT_REMOTE_DIR
    remote_script = f"""
set -eu
python3 - <<'PY'
import json
from datetime import datetime, timezone
from pathlib import Path

remote_dir = Path({sh_quote(remote_dir)})
filename = {sh_quote(filename)}
max_bytes = {MAX_XML_BYTES}

if not remote_dir.exists():
    raise SystemExit('Diretorio nao encontrado: ' + str(remote_dir))

direct = remote_dir / filename
matches = [direct] if direct.is_file() else []
if not matches:
    matches = [path for path in remote_dir.rglob(filename) if path.is_file()]
if not matches:
    raise SystemExit('Arquivo rejeitado nao encontrado: ' + filename)

target = max(matches, key=lambda path: path.stat().st_mtime)
st = target.stat()
with target.open('rb') as handle:
    raw = handle.read(max_bytes + 1)
truncated = len(raw) > max_bytes
if truncated:
    raw = raw[:max_bytes]
content = raw.decode('utf-8', errors='replace')

print(json.dumps({{
    'file': target.name,
    'path': str(target),
    'mtime': datetime.fromtimestamp(st.st_mtime, timezone.utc).astimezone().isoformat(timespec='seconds'),
    'size': st.st_size,
    'truncated': truncated,
    'content': content,
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
        fd, askpass_path = tempfile.mkstemp(prefix="nota-rejeitada-xml-askpass.", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write('#!/bin/sh\nprintf "%s\\n" "$NOTAS_REJEITADAS_SSH_PASSWORD"\n')
        os.chmod(askpass_path, 0o700)
        proc_env.update({
            "DISPLAY": proc_env.get("DISPLAY", ":0"),
            "SSH_ASKPASS": askpass_path,
            "SSH_ASKPASS_REQUIRE": "force",
            "NOTAS_REJEITADAS_SSH_PASSWORD": password,
        })
    try:
        completed = subprocess.run(
            cmd,
            input=remote_script,
            text=True,
            capture_output=True,
            env=proc_env,
            timeout=120,
            check=False,
        )
        if completed.returncode != 0:
            raise SystemExit((completed.stderr or completed.stdout or "Falha ao ler XML rejeitado.").strip())
        raw = completed.stdout.strip()
        if not raw:
            raise SystemExit("Consulta sem retorno.")
        return json.loads(raw.splitlines()[-1])
    finally:
        if askpass_path:
            Path(askpass_path).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Busca XML rejeitado no servidor Pleno.")
    parser.add_argument("--file", required=True, help="Nome do XML rejeitado.")
    args = parser.parse_args()
    filename = validate_filename(args.file)
    print(json.dumps(fetch_xml(load_env(), filename), ensure_ascii=False))


if __name__ == "__main__":
    main()
