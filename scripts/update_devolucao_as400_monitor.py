#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".python_packages"))
DEFAULT_STATUS = ROOT / "outputs" / "pleno_business_monitor" / "devolucao_as400.json"
DEFAULT_REMOTE_BASE = "/servpleno/exportacao/enviados_devolucao"
DEFAULT_EXPORT_DIR = "/servpleno/exportacao"
DEFAULT_EXPORT_TIME = "17:45"
DEFAULT_SENT_TIME = "18:15"


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


def target_date() -> date:
    return datetime.now().date()


def before_time(time_text: str) -> bool:
    return datetime.now().strftime("%H:%M") < time_text


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def remote_config(env: dict[str, str]) -> tuple[str, str, str, str]:
    user = env.get("DEVOLUCAO_AS400_REMOTE_USER") or env.get("STOCK_REMOTE_USER") or env.get("REMOTE_USER") or ""
    host = env.get("DEVOLUCAO_AS400_REMOTE_HOST") or env.get("STOCK_REMOTE_HOST") or env.get("REMOTE_HOST") or ""
    port = env.get("DEVOLUCAO_AS400_REMOTE_PORT") or env.get("STOCK_REMOTE_PORT") or env.get("REMOTE_PORT") or "22"
    password = env.get("DEVOLUCAO_AS400_REMOTE_PASSWORD") or env.get("STOCK_REMOTE_PASSWORD") or env.get("REMOTE_PASSWORD") or ""
    if not user or not host:
        raise SystemExit("Configure DEVOLUCAO_AS400_REMOTE_USER/HOST ou STOCK_REMOTE_USER/HOST.")
    return user, host, port, password


def run_remote_scan(env: dict[str, str], wanted: date) -> tuple[int, str, str]:
    user, host, port, password = remote_config(env)
    base_dir = env.get("DEVOLUCAO_AS400_REMOTE_BASE") or DEFAULT_REMOTE_BASE
    export_dir = env.get("DEVOLUCAO_AS400_EXPORT_DIR") or DEFAULT_EXPORT_DIR
    wanted_yyyymmdd = wanted.strftime("%Y%m%d")
    remote_script = f"""
set -eu
python3 - <<'PY'
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

base = Path({sh_quote(base_dir)})
export_dir = Path({sh_quote(export_dir)})
wanted = {sh_quote(wanted_yyyymmdd)}
pattern = f"DEVOLUCAO_CD_{{wanted}}*.csv"

def file_payload(path):
    if not path:
        return None
    st = path.stat()
    return {{
        "path": str(path),
        "name": path.name,
        "bytes": st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).astimezone().isoformat(timespec="seconds"),
        "ctime": datetime.fromtimestamp(st.st_ctime, timezone.utc).astimezone().isoformat(timespec="seconds"),
    }}

def read_rows(path):
    if not path:
        return []
    rows = []
    with path.open("r", encoding="latin1", errors="replace", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,|\\t,")
        except csv.Error:
            dialect = csv.excel
            dialect.delimiter = ";"
        reader = csv.DictReader(handle, dialect=dialect)
        for raw in reader:
            rows.append({{
                "loja": str(raw.get("nro_loja") or raw.get("loja") or "").strip(),
                "nro_nf": str(raw.get("nro_nf") or raw.get("nr_devolucao") or "").strip(),
                "data_nf": str(raw.get("data_nf") or "").strip(),
                "codigo": str(raw.get("codigo_interno") or raw.get("codigo_produto") or raw.get("cd_artigo") or "").strip(),
            }})
    return rows

generated_files = sorted(export_dir.glob(pattern)) if export_dir.exists() else []
sent_dir = base / f"enviados_{{wanted}}"
sent_files = sorted(sent_dir.glob(pattern)) if sent_dir.exists() else []
if not sent_files and base.exists():
    sent_files = sorted(base.glob(f"enviados_*/{{pattern}}"))
generated_path = max(generated_files, key=lambda p: p.stat().st_mtime) if generated_files else None
sent_path = max(sent_files, key=lambda p: p.stat().st_mtime) if sent_files else None
payload = {{
    "generatedFile": file_payload(generated_path),
    "sentFile": file_payload(sent_path),
    "rows": read_rows(sent_path),
    "base": str(base),
    "exportDir": str(export_dir),
    "sentDir": str(sent_dir),
    "wanted": wanted,
}}
print("JSON|" + json.dumps(payload, ensure_ascii=False))
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
        fd, askpass_path = tempfile.mkstemp(prefix="devolucao-as400-askpass.", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write('#!/bin/sh\nprintf "%s\\n" "$DEVOLUCAO_AS400_SSH_PASSWORD"\n')
        os.chmod(askpass_path, 0o700)
        proc_env.update({
            "DISPLAY": proc_env.get("DISPLAY", ":0"),
            "SSH_ASKPASS": askpass_path,
            "SSH_ASKPASS_REQUIRE": "force",
            "DEVOLUCAO_AS400_SSH_PASSWORD": password,
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
    return {"file": None, "rows": []}


def mysql_connect(env: dict[str, str]):
    import pymysql

    return pymysql.connect(
        host=env.get("MYSQL_HOST") or env.get("DB_HOST") or "127.0.0.1",
        port=int(env.get("MYSQL_PORT") or env.get("DB_PORT") or "3306"),
        user=env.get("MYSQL_USER") or env.get("DB_USER") or env.get("DB_USERNAME") or "root",
        password=env.get("MYSQL_PASSWORD") or env.get("DB_PASSWORD") or "",
        database=env.get("MYSQL_DATABASE") or env.get("DB_DATABASE") or "pleno",
        charset="latin1",
        cursorclass=pymysql.cursors.DictCursor,
    )


def fetch_pleno(env: dict[str, str], wanted: date) -> list[dict[str, Any]]:
    sql = """
        SELECT
            loja,
            nro_nf,
            data_nf,
            codigo_produto
        FROM view_dia_devolucao_cd
        WHERE data_devolucao = %s
    """
    with mysql_connect(env) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (wanted.isoformat(),))
            return list(cur.fetchall())


def normalize_key(row: dict[str, Any], source: str) -> tuple[str, str, str, str]:
    if source == "file":
        return (
            str(row.get("loja") or "").lstrip("0"),
            str(row.get("nro_nf") or "").lstrip("0"),
            str(row.get("data_nf") or "")[:10],
            str(row.get("codigo") or "").lstrip("0"),
        )
    return (
        str(row.get("loja") or "").lstrip("0"),
        str(row.get("nro_nf") or "").lstrip("0"),
        str(row.get("data_nf") or "")[:10],
        str(row.get("codigo_produto") or "").lstrip("0"),
    )


def sample_keys(keys: set[tuple[str, str, str, str]], limit: int = 10) -> list[dict[str, str]]:
    rows = []
    for loja, nota, data_nf, codigo in sorted(keys)[:limit]:
        rows.append({"loja": loja, "nota": nota, "data": data_nf, "codigo": codigo})
    return rows


def waiting_event(target_time: str, details: str) -> dict[str, Any]:
    return {
        "targetTime": target_time,
        "status": "aguardando",
        "actualAt": "",
        "count": 0,
        "details": details,
        "fileCount": 0,
        "plenoCount": 0,
        "missingInFile": 0,
        "extraInFile": 0,
    }


def build_events(env: dict[str, str]) -> dict[str, Any]:
    wanted = target_date()
    export_time = env.get("DEVOLUCAO_AS400_EXPORT_TIME") or DEFAULT_EXPORT_TIME
    sent_time = env.get("DEVOLUCAO_AS400_SENT_TIME") or env.get("DEVOLUCAO_AS400_TARGET_TIME") or DEFAULT_SENT_TIME
    if before_time(export_time):
        return {
            "arquivo_gerado": waiting_event(
                export_time,
                f"Aguardando arquivo DEVOLUCAO_CD de {wanted.strftime('%d/%m/%Y')} ser gerado as {export_time}.",
            ),
            "enviado_as400": waiting_event(
                sent_time,
                f"Aguardando envio para enviados_devolucao/enviados_{wanted.strftime('%Y%m%d')} as {sent_time}.",
            ),
        }
    code, stdout, stderr = run_remote_scan(env, wanted)
    if code != 0:
        details = (stderr or stdout or "Falha ao conectar no servidor.").strip()
        return {
            "arquivo_gerado": {
                "targetTime": export_time,
                "status": "sem_acesso",
                "actualAt": "",
                "count": 0,
                "details": f"Sem acesso: {details[:500]}",
            },
            "enviado_as400": {
                "targetTime": sent_time,
                "status": "sem_acesso",
                "actualAt": "",
                "count": 0,
                "details": f"Sem acesso: {details[:500]}",
            },
        }

    remote = parse_remote(stdout)
    generated_info = remote.get("generatedFile") or {}
    sent_info = remote.get("sentFile") or {}
    generated_or_sent = generated_info or sent_info
    events: dict[str, Any] = {}
    if generated_or_sent:
        events["arquivo_gerado"] = {
            "targetTime": export_time,
            "status": "ok",
            "actualAt": generated_or_sent.get("mtime") or iso_now(),
            "count": 1,
            "details": f"Arquivo DEVOLUCAO_CD de {wanted.strftime('%d/%m/%Y')} gerado: {generated_or_sent.get('name')}.",
            "source": generated_or_sent.get("path") or "",
        }
    else:
        events["arquivo_gerado"] = {
            "targetTime": export_time,
            "status": "error",
            "actualAt": "",
            "count": 0,
            "details": f"Arquivo DEVOLUCAO_CD de {wanted.strftime('%d/%m/%Y')} nao encontrado em {remote.get('exportDir') or DEFAULT_EXPORT_DIR}.",
            "fileCount": 0,
            "plenoCount": 0,
            "missingInFile": 0,
            "extraInFile": 0,
        }

    if not sent_info:
        if before_time(sent_time):
            events["enviado_as400"] = waiting_event(
                sent_time,
                f"Aguardando Luiz mover o arquivo para {remote.get('sentDir') or DEFAULT_REMOTE_BASE} as {sent_time}.",
            )
        else:
            events["enviado_as400"] = {
                "targetTime": sent_time,
                "status": "error",
                "actualAt": "",
                "count": 0,
                "details": f"Arquivo DEVOLUCAO_CD de {wanted.strftime('%d/%m/%Y')} nao encontrado em {remote.get('sentDir') or DEFAULT_REMOTE_BASE}.",
                "fileCount": 0,
                "plenoCount": 0,
                "missingInFile": 0,
                "extraInFile": 0,
            }
        return events

    file_rows = remote.get("rows") or []
    pleno_rows = fetch_pleno(env, wanted)
    file_keys = {normalize_key(row, "file") for row in file_rows if normalize_key(row, "file")[0] and normalize_key(row, "file")[3]}
    pleno_keys = {normalize_key(row, "pleno") for row in pleno_rows if normalize_key(row, "pleno")[0] and normalize_key(row, "pleno")[3]}
    missing = pleno_keys - file_keys
    extra = file_keys - pleno_keys
    ok = not missing and not extra
    details = (
        f"Devolucao AS400 {wanted.strftime('%d/%m/%Y')}: arquivo {sent_info.get('name')}, "
        f"{len(file_keys)} item(ns) no arquivo e {len(pleno_keys)} item(ns) no Pleno. "
        f"So no Pleno: {len(missing)}. So no arquivo: {len(extra)}."
    )
    events["enviado_as400"] = {
        "targetTime": sent_time,
        "status": "ok" if ok else "error",
        "actualAt": sent_info.get("mtime") or iso_now(),
        "count": len(file_keys),
        "details": details,
        "source": sent_info.get("path") or "",
        "file": sent_info,
        "fileCount": len(file_keys),
        "plenoCount": len(pleno_keys),
        "missingInFile": len(missing),
        "extraInFile": len(extra),
        "missingSamples": sample_keys(missing),
        "extraSamples": sample_keys(extra),
    }
    return events


def write_status(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    env = load_env()
    status = {
        "collector": "devolucao-as400-monitor",
        "updatedAt": iso_now(),
        "events": build_events(env),
    }
    write_status(DEFAULT_STATUS, status)
    print(f"Monitor devolucao AS400 atualizado em {DEFAULT_STATUS}")


if __name__ == "__main__":
    main()
