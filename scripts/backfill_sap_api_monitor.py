#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from update_sap_api_monitor import (
    DEFAULT_HISTORY_LIMIT,
    DEFAULT_STATUS,
    load_env,
    remote_config,
    with_previous_delta,
    write_status,
)


def remote_script(start_hhmm: str, bucket_minutes: int) -> str:
    return f"""python3 - <<'PY'
from pathlib import Path
from datetime import datetime, timedelta
import collections
import json
import re
import socket
import statistics

start_hhmm = {start_hhmm!r}
bucket_minutes = {int(bucket_minutes)}
now = datetime.now()
hour, minute = [int(part) for part in start_hhmm.split(":", 1)]
start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
if start > now:
    start = start - timedelta(days=1)
end = now
log_dir = Path("/var/log/pleno")
log_dates = sorted({{start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")}})
line_re = re.compile(r'^\\[(\\d{{4}}-\\d{{2}}-\\d{{2}})\\s+(\\d{{1,2}}:\\d{{2}}:\\d{{2}})\\.(\\d+)\\]\\s+\\[([^\\]]+)\\]\\s+(.*)$')
name_re = re.compile(r'ID\\s+(\\d+)\\s+(.+?)\\s+->')

def classify(msg):
    low = msg.lower()
    if "execução com sucesso" in low or "execucao com sucesso" in low or re.search(r'\\b0\\|', msg) or re.search(r'\\bOK\\b', msg):
        return "success"
    error_terms = [
        "chave nfe recebida",
        "nf não teve retorno",
        "nf nao teve retorno",
        "br_nfedocumentstatus não informado",
        "br_nfedocumentstatus nao informado",
        "nf-e inexistente",
        "falha",
        "erro",
        "exception",
        "timeout",
        "não está atualizado",
        "nao esta atualizado",
        "não foi possível",
        "nao foi possivel",
    ]
    if any(term in low for term in error_terms):
        return "error"
    return "other"

def reason(msg):
    low = msg.lower()
    if "chave nfe recebida" in low:
        return "Chave NFe nao tem 44 caracteres"
    if "br_nfedocumentstatus" in low:
        return "BR_NFeDocumentStatus nao informado"
    if "nf não teve retorno" in low or "nf nao teve retorno" in low:
        return "NF sem retorno do SAP apos 5 tentativas"
    if "nf-e inexistente no inbound" in low:
        return "NF-e inexistente no INBOUND"
    if "falha ao gerar documento" in low:
        return "Falha ao gerar documento VL32N"
    if "não está atualizado no centro" in low or "nao esta atualizado no centro" in low:
        return "Material nao atualizado no centro"
    if "não foi possível explosão" in low or "nao foi possivel explosao" in low:
        return "Falha na explosao da lista tecnica"
    if classify(msg) == "success":
        return "Sucesso"
    return "Outro/sem classificacao"

def percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[int(p * (len(ordered) - 1))]

def bucket_start_for(event_at):
    elapsed = int((event_at - start).total_seconds())
    bucket_index = elapsed // (bucket_minutes * 60)
    return start + timedelta(minutes=bucket_index * bucket_minutes)

buckets = {{}}
labels = {{}}
files_by_id = {{}}
for log_date in log_dates:
    for path in sorted(log_dir.glob(f"LOG.API.SAP.INTEGRATION.*.{{log_date}}.log")):
        try:
            handle = path.open("r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with handle:
            for raw in handle:
                match = line_re.match(raw)
                if not match:
                    continue
                micro = (match.group(3) + "000000")[:6]
                try:
                    event_at = datetime.strptime(match.group(1) + " " + match.group(2) + "." + micro, "%Y-%m-%d %H:%M:%S.%f")
                except ValueError:
                    continue
                if not (start <= event_at <= end):
                    continue
                msg = match.group(5).strip()
                if not any(token in msg for token in ["Chamada:", "Execução", "Execucao", "OK", "Falha", "não", "nao", "Erro", "erro"]):
                    continue
                tx_id = re.sub(r'\\.\\d{{4}}-\\d{{2}}-\\d{{2}}$', '', path.stem.replace("LOG.API.SAP.INTEGRATION.", ""))
                name_match = name_re.search(msg)
                if name_match:
                    labels[tx_id] = f"ID {{name_match.group(1)}} - {{name_match.group(2)}}"
                else:
                    labels.setdefault(tx_id, tx_id)
                files_by_id[tx_id] = str(path)
                bucket_at = bucket_start_for(event_at)
                bucket_key = bucket_at.isoformat(sep=" ", timespec="seconds")
                bucket = buckets.setdefault(bucket_key, {{}})
                tx = bucket.setdefault(tx_id, {{
                    "eventsAt": [],
                    "counts": collections.Counter(),
                    "reasons": collections.Counter(),
                    "notes": collections.Counter(),
                    "sampleErrors": [],
                }})
                status = classify(msg)
                tx["eventsAt"].append(event_at)
                tx["counts"][status] += 1
                tx["reasons"][reason(msg)] += 1
                note_match = re.search(r'BR_NotaFiscal=(\\d+)', msg)
                if note_match:
                    tx["notes"][note_match.group(1)] += 1
                if status == "error" and len(tx["sampleErrors"]) < 5:
                    tx["sampleErrors"].append(raw.strip()[:900])

snapshots = []
cursor = start
while cursor < end:
    bucket_end = min(cursor + timedelta(minutes=bucket_minutes), end)
    bucket_key = cursor.isoformat(sep=" ", timespec="seconds")
    transactions = []
    for tx_id, tx in (buckets.get(bucket_key) or {{}}).items():
        events = sorted(tx["eventsAt"])
        gaps = [(b - a).total_seconds() for a, b in zip(events, events[1:]) if (b - a).total_seconds() >= 0]
        total = len(events)
        counts = tx["counts"]
        transactions.append({{
            "id": tx_id,
            "label": labels.get(tx_id, tx_id),
            "file": files_by_id.get(tx_id, ""),
            "events": total,
            "success": counts["success"],
            "errors": counts["error"],
            "other": counts["other"],
            "successRate": round(counts["success"] / total * 100, 2) if total else 0,
            "errorRate": round(counts["error"] / total * 100, 2) if total else 0,
            "avgResponseGapSeconds": round(statistics.mean(gaps), 3) if gaps else None,
            "medianResponseGapSeconds": round(statistics.median(gaps), 3) if gaps else None,
            "p95ResponseGapSeconds": round(percentile(gaps, 0.95), 3) if gaps else None,
            "maxResponseGapSeconds": round(max(gaps), 3) if gaps else None,
            "eventsPerMinute": round(total / max((events[-1] - events[0]).total_seconds() / 60, 1 / 60), 2) if events else 0,
            "firstEventAt": events[0].isoformat(sep=" ", timespec="milliseconds") if events else "",
            "lastEventAt": events[-1].isoformat(sep=" ", timespec="milliseconds") if events else "",
            "topReasons": [{{"reason": key, "count": value}} for key, value in tx["reasons"].most_common(8)],
            "topNotes": [{{"note": key, "count": value}} for key, value in tx["notes"].most_common(8)],
            "sampleErrors": tx["sampleErrors"],
        }})
    transactions.sort(key=lambda item: item["events"], reverse=True)
    totals = {{
        "events": sum(item["events"] for item in transactions),
        "success": sum(item["success"] for item in transactions),
        "errors": sum(item["errors"] for item in transactions),
        "other": sum(item["other"] for item in transactions),
    }}
    totals["successRate"] = round(totals["success"] / totals["events"] * 100, 2) if totals["events"] else 0
    totals["errorRate"] = round(totals["errors"] / totals["events"] * 100, 2) if totals["events"] else 0
    snapshots.append({{
        "collectedAt": bucket_end.astimezone().isoformat(timespec="seconds"),
        "windowStart": cursor.astimezone().isoformat(timespec="seconds"),
        "windowEnd": bucket_end.astimezone().isoformat(timespec="seconds"),
        "windowMinutes": bucket_minutes,
        "host": socket.gethostname(),
        "logDir": str(log_dir),
        "totals": totals,
        "transactions": transactions,
    }})
    cursor = bucket_end

print(json.dumps({{"snapshots": snapshots}}, ensure_ascii=False))
PY"""


def run_remote_backfill(env: dict[str, str], start_hhmm: str, bucket_minutes: int) -> list[dict[str, Any]]:
    user, host, port, password = remote_config(env)
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
        fd, askpass_path = tempfile.mkstemp(prefix="sap-api-backfill-askpass.", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write('#!/bin/sh\nprintf "%s\\n" "$SAP_API_SSH_PASSWORD"\n')
        os.chmod(askpass_path, 0o700)
        proc_env.update(
            {
                "DISPLAY": proc_env.get("DISPLAY", ":0"),
                "SSH_ASKPASS": askpass_path,
                "SSH_ASKPASS_REQUIRE": "force",
                "SAP_API_SSH_PASSWORD": password,
            }
        )
    try:
        completed = subprocess.run(
            cmd,
            input=remote_script(start_hhmm, bucket_minutes),
            text=True,
            capture_output=True,
            env=proc_env,
            timeout=int(env.get("SAP_API_MONITOR_TIMEOUT_SECONDS", "300")),
            check=False,
        )
    finally:
        if askpass_path:
            Path(askpass_path).unlink(missing_ok=True)
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "Falha ao coletar backfill SAP.").strip()
        raise RuntimeError(details[:2000])
    return json.loads(completed.stdout).get("snapshots", [])


def load_status(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"collector": "sap-api-monitor", "history": []}


def main() -> None:
    parser = argparse.ArgumentParser(description="Preenche historico do monitor SAP API por buckets.")
    parser.add_argument("--from", dest="start_hhmm", default="10:00", help="Horario inicial HH:MM.")
    parser.add_argument("--bucket-minutes", type=int, default=10, help="Tamanho do bucket em minutos.")
    args = parser.parse_args()

    env = load_env()
    status_file = Path(env.get("SAP_API_MONITOR_STATUS_FILE") or DEFAULT_STATUS)
    history_limit = int(env.get("SAP_API_MONITOR_HISTORY_LIMIT") or DEFAULT_HISTORY_LIMIT)
    snapshots = run_remote_backfill(env, args.start_hhmm, args.bucket_minutes)

    previous = None
    history = []
    for snapshot in snapshots:
        with_previous_delta(snapshot, previous)
        history.append(snapshot)
        previous = snapshot
    history = history[-history_limit:]
    latest = history[-1] if history else {}
    status = {
        "collector": "sap-api-monitor",
        "updatedAt": latest.get("collectedAt") or datetime.now().astimezone().isoformat(timespec="seconds"),
        "windowMinutes": args.bucket_minutes,
        "historyLimit": history_limit,
        "latest": latest,
        "history": history,
    }
    write_status(status_file, status)
    print(f"Backfill SAP API gravado em {status_file}: {len(history)} janela(s).")


if __name__ == "__main__":
    main()
