#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".python_packages"))

DEFAULT_STATUS = ROOT / "outputs" / "pleno_business_monitor" / "notas_rejeitadas.json"
DEFAULT_REMOTE_DIR = "/servpleno/importacao/NFE/rejeitado"
DEFAULT_LOOKBACK_HOURS = 168
DEFAULT_ALERT_AFTER_HOURS = 8
DEFAULT_CD_STORE = 704


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


def note_age_hours(value: str) -> float:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return max(0.0, (datetime.now().astimezone() - moment.astimezone()).total_seconds() / 3600)


def json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def clean_cnpj(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def parse_int_set(value: str, default: set[int] | None = None) -> set[int]:
    result = set(default or set())
    for item in str(value or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            result.add(int(item))
        except ValueError:
            continue
    return result


def remote_config(env: dict[str, str]) -> tuple[str, str, str, str]:
    user = env.get("NOTAS_REJEITADAS_REMOTE_USER") or env.get("STOCK_REMOTE_USER") or ""
    host = env.get("NOTAS_REJEITADAS_REMOTE_HOST") or env.get("STOCK_REMOTE_HOST") or ""
    port = env.get("NOTAS_REJEITADAS_REMOTE_PORT") or env.get("STOCK_REMOTE_PORT") or "22"
    password = env.get("NOTAS_REJEITADAS_REMOTE_PASSWORD") or env.get("STOCK_REMOTE_PASSWORD") or ""
    if not user or not host:
        raise SystemExit("Configure NOTAS_REJEITADAS_REMOTE_USER/HOST ou STOCK_REMOTE_USER/HOST.")
    return user, host, port, password


def run_remote_xml_scan(env: dict[str, str]) -> tuple[int, str, str]:
    user, host, port, password = remote_config(env)
    remote_dir = env.get("NOTAS_REJEITADAS_REMOTE_DIR") or DEFAULT_REMOTE_DIR
    lookback_hours = int(env.get("NOTAS_REJEITADAS_LOOKBACK_HOURS") or DEFAULT_LOOKBACK_HOURS)
    remote_script = f"""
set -eu
python3 - <<'PY'
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

remote_dir = Path({sh_quote(remote_dir)})
lookback_seconds = {lookback_hours} * 3600
now = datetime.now().timestamp()

def text(node, tag):
    item = node.find('.//{{*}}' + tag)
    return (item.text or '').strip() if item is not None else ''

def text_under(node, parent, tag):
    root = node.find('.//{{*}}' + parent)
    if root is None:
        return ''
    item = root.find('.//{{*}}' + tag)
    return (item.text or '').strip() if item is not None else ''

def only_digits(value):
    return re.sub(r'\\D', '', value or '')

print('REMOTE_DIR|' + str(remote_dir))
if not remote_dir.exists():
    raise SystemExit('Diretorio nao encontrado: ' + str(remote_dir))

for path in sorted(remote_dir.rglob('*.xml')):
    try:
        st = path.stat()
    except OSError:
        continue
    if now - st.st_mtime > lookback_seconds:
        continue
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        continue
    inf = root.find('.//{{*}}infNFe')
    chave = text(root, 'chNFe')
    if not chave and inf is not None:
        chave = (inf.attrib.get('Id') or '').replace('NFe', '')
    row = {{
        'arquivo': str(path),
        'nomeArquivo': path.name,
        'mtime': datetime.fromtimestamp(st.st_mtime, timezone.utc).astimezone().isoformat(timespec='seconds'),
        'chave': chave,
        'nota': text(root, 'nNF'),
        'serie': text(root, 'serie'),
        'emissao': (text(root, 'dhEmi') or text(root, 'dEmi'))[:10],
        'emitenteCnpj': only_digits(text_under(root, 'emit', 'CNPJ')),
        'destinatarioCnpj': only_digits(text_under(root, 'dest', 'CNPJ')),
        'destinatarioNome': text_under(root, 'dest', 'xNome'),
        'motivo': '',
    }}
    print('XML|' + json.dumps(row, ensure_ascii=False))
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
        fd, askpass_path = tempfile.mkstemp(prefix="notas-rejeitadas-askpass.", text=True)
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
            return completed.returncode, completed.stdout, completed.stderr
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            return 124, stdout, stderr or "Timeout ao acessar servidor."
    finally:
        if askpass_path:
            Path(askpass_path).unlink(missing_ok=True)


def parse_remote_output(output: str) -> tuple[str, list[dict[str, Any]]]:
    remote_dir = DEFAULT_REMOTE_DIR
    rows: list[dict[str, Any]] = []
    for line in output.splitlines():
        if line.startswith("REMOTE_DIR|"):
            remote_dir = line.split("|", 1)[1]
        elif line.startswith("XML|"):
            try:
                rows.append(json.loads(line.split("|", 1)[1]))
            except json.JSONDecodeError:
                continue
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("chave") or row.get("arquivo") or "")
        if key:
            unique[key] = row
    return remote_dir, list(unique.values())


def query_filiais(conn) -> dict[str, dict[str, Any]]:
    sql = """
        SELECT DISTINCT
            REPLACE(REPLACE(REPLACE(e.pes03_cnpj, '.', ''), '/', ''), '-', '') AS cnpj,
            f.cfg06_numero AS loja,
            f.cfg06_nome AS nome_loja
        FROM cfg06_filial f
        JOIN pes03_estabelecimento e ON e.pes03_id = f.pes03_estabelecimento_id
        WHERE e.pes03_cnpj IS NOT NULL
          AND f.cfg06_numero IS NOT NULL
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        cnpj = clean_cnpj(str(row["cnpj"] or ""))
        loja = row["loja"]
        if cnpj and loja is not None:
            previous = result.get(cnpj)
            if previous is None or int(loja) < int(previous["loja"]):
                result[cnpj] = {"loja": int(loja), "nomeLoja": row["nome_loja"] or ""}
    return result


def query_pleno_notes(conn, keys: list[str]) -> set[str]:
    found: set[str] = set()
    for index in range(0, len(keys), 700):
        chunk = keys[index:index + 700]
        if not chunk:
            continue
        placeholders = ",".join(["%s"] * len(chunk))
        sql = f"SELECT DISTINCT fis01_nfe_chave AS chave FROM fis01_notafiscal WHERE fis01_nfe_chave IN ({placeholders})"
        with conn.cursor() as cur:
            cur.execute(sql, chunk)
            found.update(str(row["chave"] or "") for row in cur.fetchall())
    return found


def write_status(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")
    tmp.replace(path)


def build_event(env: dict[str, str]) -> dict[str, Any]:
    code, stdout, stderr = run_remote_xml_scan(env)
    if code != 0:
        details = (stderr or stdout or "Falha ao conectar no servidor.").strip()
        return {
            "targetTime": "00:00",
            "status": "sem_acesso",
            "actualAt": "",
            "count": 0,
            "source": env.get("NOTAS_REJEITADAS_REMOTE_DIR") or DEFAULT_REMOTE_DIR,
            "details": f"Sem acesso ao servidor: {details[:500]}",
            "notes": [],
        }

    remote_dir, xmls = parse_remote_output(stdout)
    import pymysql
    conn = pymysql.connect(
        host=env["MYSQL_HOST"],
        port=int(env.get("MYSQL_PORT", "3306")),
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        database=env["MYSQL_DATABASE"],
        charset="latin1",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        filiais = query_filiais(conn)
        cd_store = int(env.get("NOTAS_REJEITADAS_CD_STORE") or DEFAULT_CD_STORE)
        max_store = int(env.get("NOTAS_REJEITADAS_MAX_STORE_NUMBER") or "2999")
        ignored_stores = parse_int_set(env.get("NOTAS_REJEITADAS_IGNORE_STORES") or "", {1})
        candidates = []
        ignored = []
        for xml in xmls:
            dest = filiais.get(clean_cnpj(str(xml.get("destinatarioCnpj") or "")))
            emit = filiais.get(clean_cnpj(str(xml.get("emitenteCnpj") or "")))
            if not dest or not emit:
                continue
            dest_store = int(dest["loja"])
            if dest_store in ignored_stores:
                ignored.append({**xml, "loja": dest_store, "nomeLoja": dest["nomeLoja"], "motivoIgnorado": "Destinatario ignorado pela regra do monitor."})
                continue
            if dest_store <= 0 or dest_store > max_store or dest_store == cd_store:
                continue
            if int(emit["loja"]) != cd_store:
                continue
            candidates.append({**xml, "loja": dest["loja"], "nomeLoja": dest["nomeLoja"], "lojaEmitente": emit["loja"]})
        keys = [str(row.get("chave") or "") for row in candidates if row.get("chave")]
        found = query_pleno_notes(conn, keys)
    finally:
        conn.close()

    missing = []
    for row in candidates:
        if str(row.get("chave") or "") in found:
            continue
        missing.append({
            "nota": row.get("nota") or "-",
            "serie": row.get("serie") or "-",
            "chave": row.get("chave") or "",
            "loja": row.get("loja"),
            "nomeLoja": row.get("nomeLoja") or "",
            "emissao": row.get("emissao") or "",
            "arquivo": row.get("nomeArquivo") or Path(str(row.get("arquivo") or "")).name,
            "mtime": row.get("mtime") or "",
            "motivo": row.get("motivo") or "XML rejeitado nao localizado na fis01_notafiscal.",
        })
    try:
        alert_after_hours = max(1, int(env.get("NOTAS_REJEITADAS_ALERT_AFTER_HOURS") or DEFAULT_ALERT_AFTER_HOURS))
    except (TypeError, ValueError):
        alert_after_hours = DEFAULT_ALERT_AFTER_HOURS
    for item in missing:
        age_hours = note_age_hours(str(item.get("mtime") or ""))
        item["ageHours"] = round(age_hours, 1)
        item["overdue"] = age_hours >= alert_after_hours
    missing.sort(key=lambda item: (not bool(item.get("overdue")), -float(item.get("ageHours") or 0), int(item.get("loja") or 0), str(item.get("nota") or "")))
    count = len(missing)
    overdue = [item for item in missing if item.get("overdue")]
    if overdue:
        visible = ", ".join(f"NF {item['nota']} L-{item['loja']} ({item['ageHours']:.1f}h)" for item in overdue[:8])
        suffix = f" (+{len(overdue) - 8})" if len(overdue) > 8 else ""
        status = "error"
        details = (
            f"{len(overdue)} nota(s) rejeitada(s) de CD sem entrada no Pleno ha {alert_after_hours}h ou mais: "
            f"{visible}{suffix}. Total pendente: {count}."
        )
    elif count:
        visible = ", ".join(f"NF {item['nota']} L-{item['loja']}" for item in missing[:8])
        suffix = f" (+{count - 8})" if count > 8 else ""
        status = "warning"
        details = (
            f"{count} nota(s) rejeitada(s) de CD para lojas proprias sem entrada no Pleno, "
            f"ainda dentro do prazo de {alert_after_hours}h: {visible}{suffix}."
        )
    else:
        status = "ok"
        details = f"Nenhuma nota rejeitada de CD para lojas proprias sem entrada no Pleno em {remote_dir}."
    return {
        "targetTime": "00:00",
        "status": status,
        "actualAt": iso_now(),
        "count": count,
        "source": remote_dir,
        "details": details,
        "notes": missing[:50],
        "overdueCount": len(overdue),
        "alertAfterHours": alert_after_hours,
        "checkedXmls": len(xmls),
        "candidateXmls": len(candidates),
        "ignoredXmls": len(ignored),
        "ignoredStores": sorted(ignored_stores),
        "lookbackHours": int(env.get("NOTAS_REJEITADAS_LOOKBACK_HOURS") or DEFAULT_LOOKBACK_HOURS),
    }


def main() -> None:
    env = load_env()
    status_file = Path(env.get("NOTAS_REJEITADAS_STATUS_FILE") or DEFAULT_STATUS)
    status = {
        "collector": "notas-rejeitadas-monitor",
        "updatedAt": iso_now(),
        "events": {
            "notas_rejeitadas": build_event(env),
        },
    }
    write_status(status_file, status)
    print(f"Monitor notas rejeitadas atualizado em {status_file}")


if __name__ == "__main__":
    main()
