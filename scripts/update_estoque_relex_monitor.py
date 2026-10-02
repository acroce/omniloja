#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATUS = ROOT / "outputs" / "pleno_business_monitor" / "estoque_relex.json"
DEFAULT_GENERATED_DIR = "/servpleno/exportacao"
DEFAULT_PROCESSED_DIR = "/servpleno/exportacao/processados"
DEFAULT_FILE_NAMES = ["estoque_data.csv", "estote_data.csv"]
DEFAULT_GENERATED_TARGET_TIME = "22:30"
DEFAULT_VARIATION_TARGET_TIME = "23:30"
DEFAULT_PROCESSED_TARGET_TIME = "06:00"
DEFAULT_VARIATION_WARN_PERCENT = 2.0


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
    # No Linux as credenciais remotas sao carregadas pelo Docker Compose a
    # partir do .env central. Mantem os arquivos locais como fallback.
    env.update(os.environ)
    return env


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def after_target(target_time: str) -> bool:
    try:
        hours, minutes = target_time.split(":", 1)
        target = datetime.now().replace(hour=int(hours), minute=int(minutes), second=0, microsecond=0)
    except ValueError:
        return True
    return datetime.now() >= target


def after_date_target(date_text: str, target_time: str) -> bool:
    try:
        hours, minutes = target_time.split(":", 1)
        base = datetime.strptime(date_text, "%Y-%m-%d")
        target = base.replace(hour=int(hours), minute=int(minutes), second=0, microsecond=0)
    except ValueError:
        return True
    return datetime.now() >= target


def remote_config(env: dict[str, str]) -> tuple[str, str, str, str]:
    user = env.get("ESTOQUE_RELEX_REMOTE_USER") or env.get("STOCK_REMOTE_USER") or ""
    host = env.get("ESTOQUE_RELEX_REMOTE_HOST") or env.get("STOCK_REMOTE_HOST") or ""
    port = env.get("ESTOQUE_RELEX_REMOTE_PORT") or env.get("STOCK_REMOTE_PORT") or "22"
    password = env.get("ESTOQUE_RELEX_REMOTE_PASSWORD") or env.get("STOCK_REMOTE_PASSWORD") or ""
    if not user or not host:
        raise SystemExit("Configure ESTOQUE_RELEX_REMOTE_USER/HOST ou STOCK_REMOTE_USER/HOST.")
    return user, host, port, password


def configured_file_names(env: dict[str, str]) -> list[str]:
    raw = env.get("ESTOQUE_RELEX_FILE_NAMES", "")
    names = [item.strip() for item in raw.split(",") if item.strip()]
    return names or DEFAULT_FILE_NAMES


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


REMOTE_VARIATION_PY = r"""
import csv
import datetime as dt
import glob
import json
import os
import re
from pathlib import Path

generated_dir = os.environ.get("generated_dir", "")
processed_dir = os.environ.get("processed_dir", "")
file_names = json.loads(os.environ.get("file_names_json", "[]"))
warn_percent = float(os.environ.get("variation_warn", "2") or 2)
today = dt.date.today()
target_date = today - dt.timedelta(days=1)

def compact(value):
    return value.strftime("%Y%m%d")

def file_mtime(path):
    return dt.datetime.fromtimestamp(path.stat().st_mtime)

def all_stock_files():
    found = []
    for kind, directory in (("generated", generated_dir), ("processed", processed_dir)):
        base = Path(directory)
        for name in file_names:
            path = base / name
            if path.is_file():
                found.append((kind, path))
        for pattern in ("*estoque*.csv", "*estote*.csv"):
            for raw in glob.glob(str(base / pattern)):
                path = Path(raw)
                if path.is_file():
                    found.append((kind, path))
    unique = {}
    for kind, path in found:
        unique[str(path)] = (kind, path)
    return list(unique.values())

def select_file(files, wanted_date):
    wanted = compact(wanted_date)
    candidates = []
    for kind, path in files:
        name = path.name
        mdate = file_mtime(path).date()
        match = re.search(rf"{wanted}(\d{{6}})", name)
        stamped = bool(match and int(match.group(1)) >= 220000)
        fixed = name in file_names and mdate == wanted_date
        if stamped or fixed:
            priority = 1 if kind == "generated" else 0
            candidates.append((priority, path.stat().st_size, kind, path))
    if not candidates:
        return None
    return sorted(candidates, reverse=True)[0][3]

def select_latest_processed(files, target):
    candidates = []
    target_path = str(target) if target else ""
    for kind, path in files:
        if kind != "processed" or str(path) == target_path:
            continue
        candidates.append((file_mtime(path), path.stat().st_size, path))
    if not candidates:
        return None
    return sorted(candidates, reverse=True)[0][2]

def normalized(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())

def parse_number(value):
    text = str(value or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0

def detect_columns(headers, rows):
    names = [normalized(item) for item in headers]
    store_terms = ("loja", "filial", "cfg06", "codloja", "codigoloja", "codfilial")
    qty_terms = ("estoque", "saldo", "quantidade", "qtd", "qtde")
    store_idx = next((idx for idx, name in enumerate(names) if any(term in name for term in store_terms)), None)
    qty_idx = next((idx for idx, name in enumerate(names) if any(term in name for term in qty_terms) and "cod" not in name), None)
    if store_idx is not None and qty_idx is not None:
        return True, store_idx, qty_idx

    sample = rows[:30]
    width = max([len(row) for row in sample] + [len(headers)])
    numeric_scores = []
    for idx in range(width):
        values = [row[idx] for row in sample if idx < len(row)]
        numeric = sum(1 for value in values if parse_number(value) != 0)
        numeric_scores.append((numeric, idx))
    if store_idx is None:
        store_idx = 0
    if qty_idx is None:
        qty_idx = sorted(numeric_scores, reverse=True)[0][1] if numeric_scores else None
    return False, store_idx, qty_idx

def summarize(path):
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        sample_text = handle.read(8192)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample_text, delimiters=";,|\t,")
        except csv.Error:
            dialect = csv.excel
            dialect.delimiter = ";"
        reader = csv.reader(handle, dialect)
        rows = [row for row in reader if row]
    if not rows:
        return {}, {"error": "arquivo vazio"}
    headers = rows[0]
    data_rows = rows[1:]
    has_header, store_idx, qty_idx = detect_columns(headers, data_rows)
    if store_idx is None or qty_idx is None:
        return {}, {"error": "nao foi possivel identificar coluna de loja e quantidade"}
    totals = {}
    for row in data_rows if has_header else rows:
        if store_idx >= len(row) or qty_idx >= len(row):
            continue
        store = str(row[store_idx]).strip()
        if not store:
            continue
        totals[store] = totals.get(store, 0.0) + parse_number(row[qty_idx])
    return totals, {
        "storeColumn": headers[store_idx] if has_header and store_idx < len(headers) else str(store_idx + 1),
        "quantityColumn": headers[qty_idx] if has_header and qty_idx < len(headers) else str(qty_idx + 1),
        "hasHeader": has_header,
    }

files = all_stock_files()
target = select_file(files, target_date)
baseline = select_latest_processed(files, target)
result = {
    "status": "error",
    "targetDate": target_date.isoformat(),
    "baselineDate": "",
    "thresholdPercent": warn_percent,
    "actualAt": "",
    "targetFile": str(target) if target else "",
    "previousFile": str(baseline) if baseline else "",
    "storesChecked": 0,
    "variationCount": 0,
    "variationStores": [],
    "details": "",
}
if not target:
    result["details"] = f"Arquivo de estoque gerado para {target_date.isoformat()} nao encontrado para validar variacao."
elif not baseline:
    result["details"] = f"Nenhum arquivo de estoque encontrado em processados para comparar com {Path(target).name}."
else:
    current_totals, current_meta = summarize(target)
    previous_totals, previous_meta = summarize(baseline)
    if current_meta.get("error") or previous_meta.get("error"):
        result["details"] = current_meta.get("error") or previous_meta.get("error")
    else:
        variations = []
        for store in sorted(set(current_totals) | set(previous_totals)):
            current = current_totals.get(store, 0.0)
            old = previous_totals.get(store, 0.0)
            pct = 0.0 if old == 0 and current == 0 else (100.0 if old == 0 else abs(current - old) / abs(old) * 100.0)
            if pct >= warn_percent:
                variations.append({
                    "store": store,
                    "previous": round(old, 3),
                    "current": round(current, 3),
                    "percent": round(pct, 2),
                })
        variations.sort(key=lambda item: item["percent"], reverse=True)
        result.update({
            "status": "ok" if variations else "error",
            "actualAt": file_mtime(target).isoformat(sep=" ", timespec="seconds"),
            "baselineDate": file_mtime(baseline).date().isoformat(),
            "storesChecked": len(set(current_totals) | set(previous_totals)),
            "variationCount": len(variations),
            "variationStores": variations[:20],
            "details": (
                f"Variacao de estoque por loja comparada com o processado mais recente {Path(baseline).name}. "
                f"Lojas verificadas: {len(set(current_totals) | set(previous_totals))}. "
                f"Colunas: loja={current_meta.get('storeColumn')}, quantidade={current_meta.get('quantityColumn')}. "
                + (
                    "Variacao encontrada: "
                    + ", ".join(f"{item['store']} {item['percent']}%" for item in variations[:8])
                    if variations else f"Sem variacao ou variacao menor que {warn_percent}%."
                )
            ),
        })
print("VARJSON|" + json.dumps(result, ensure_ascii=False))
"""


def run_remote_check(env: dict[str, str]) -> tuple[int, str, str]:
    user, host, port, password = remote_config(env)
    generated_dir = env.get("ESTOQUE_RELEX_GENERATED_DIR") or env.get("ESTOQUE_RELEX_SOURCE_DIR") or DEFAULT_GENERATED_DIR
    processed_dir = env.get("ESTOQUE_RELEX_REMOTE_DIR") or env.get("ESTOQUE_RELEX_PROCESSED_DIR") or DEFAULT_PROCESSED_DIR
    file_names = configured_file_names(env)
    names_script = " ".join(sh_quote(name) for name in file_names)
    file_names_json = sh_quote(json.dumps(file_names, ensure_ascii=False))
    variation_warn = sh_quote(env.get("ESTOQUE_RELEX_VARIATION_WARN_PERCENT") or str(DEFAULT_VARIATION_WARN_PERCENT))
    remote_script = f"""
set -eu
generated_dir={sh_quote(generated_dir)}
processed_dir={sh_quote(processed_dir)}
file_names_json={file_names_json}
variation_warn={variation_warn}
export generated_dir processed_dir file_names_json variation_warn
today="$(date +%Y-%m-%d)"
if yesterday="$(date -d yesterday +%Y-%m-%d 2>/dev/null)"; then
  :
else
  yesterday="$(date -v-1d +%Y-%m-%d)"
fi
yesterday_compact="$(printf '%s' "$yesterday" | tr -d '-')"
printf 'TODAY|%s\\n' "$today"
printf 'TARGET|%s|%s\\n' "$yesterday" "$yesterday_compact"
printf 'DIR|generated|%s\\n' "$generated_dir"
printf 'DIR|processed|%s\\n' "$processed_dir"
emit_file() {{
  kind="$1"
  dir="$2"
  name="$3"
  file="$dir/$name"
  if [ -f "$file" ]; then
    lines="$(wc -l < "$file" | tr -d ' ')"
    bytes="$(wc -c < "$file" | tr -d ' ')"
    if stat -c '%y' "$file" >/dev/null 2>&1; then
      mtime="$(stat -c '%y' "$file")"
      mdate="$(stat -c '%y' "$file" | cut -c1-10)"
      ctime="$(stat -c '%z' "$file")"
      cdate="$(stat -c '%z' "$file" | cut -c1-10)"
    else
      mtime="$(stat -f '%Sm' "$file")"
      mdate="$(stat -f '%Sm' -t '%Y-%m-%d' "$file")"
      ctime="$(stat -f '%Sc' "$file")"
      cdate="$(stat -f '%Sc' -t '%Y-%m-%d' "$file")"
    fi
    printf 'FILE|%s|%s|%s|%s|%s|%s|%s|%s|%s\\n' "$kind" "$name" "$lines" "$bytes" "$mtime" "$mdate" "$ctime" "$cdate" "$dir"
  else
    printf 'MISSING|%s|%s\\n' "$kind" "$name"
  fi
}}
for dir_pair in "generated|$generated_dir" "processed|$processed_dir"; do
  kind="${{dir_pair%%|*}}"
  dir="${{dir_pair#*|}}"
  for name in {names_script}; do
    emit_file "$kind" "$dir" "$name"
  done
  find "$dir" -maxdepth 1 -type f \\( -iname '*estoque*.csv' -o -iname '*estote*.csv' \\) -print 2>/dev/null |
  while IFS= read -r file; do
    emit_file "$kind" "$dir" "$(basename "$file")"
  done
done
python3 - <<'PY' 2>/dev/null || true
{REMOTE_VARIATION_PY}
PY
"""
    cmd = [
        "ssh",
        "-p", str(port),
        "-o", "BatchMode=no" if password else "BatchMode=yes",
        "-o", "ConnectTimeout=60",
        "-o", "StrictHostKeyChecking=accept-new",
        f"{user}@{host}",
        "sh",
        "-s",
    ]
    proc_env = os.environ.copy()
    askpass_path = None
    if password:
        fd, askpass_path = tempfile.mkstemp(prefix="estoque-relex-askpass.", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write('#!/bin/sh\nprintf "%s\\n" "$ESTOQUE_RELEX_SSH_PASSWORD"\n')
        os.chmod(askpass_path, 0o700)
        proc_env.update({
            "DISPLAY": proc_env.get("DISPLAY", ":0"),
            "SSH_ASKPASS": askpass_path,
            "SSH_ASKPASS_REQUIRE": "force",
            "ESTOQUE_RELEX_SSH_PASSWORD": password,
        })
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
    today = ""
    target_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    target_compact = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    dirs = {"generated": DEFAULT_GENERATED_DIR, "processed": DEFAULT_PROCESSED_DIR}
    files: list[dict[str, Any]] = []
    missing: list[str] = []
    variation: dict[str, Any] = {}
    for line in output.splitlines():
        if line.startswith("VARJSON|"):
            try:
                variation = json.loads(line.split("|", 1)[1])
            except json.JSONDecodeError:
                variation = {"status": "error", "details": "Falha ao interpretar validacao de variacao."}
            continue
        parts = line.split("|", 9)
        if not parts:
            continue
        if parts[0] == "TODAY" and len(parts) >= 2:
            today = parts[1]
        elif parts[0] == "TARGET" and len(parts) >= 3:
            target_date = parts[1]
            target_compact = parts[2]
        elif parts[0] == "DIR" and len(parts) >= 3:
            dirs[parts[1]] = parts[2]
        elif parts[0] == "MISSING" and len(parts) >= 3:
            missing.append(f"{parts[1]}:{parts[2]}")
        elif parts[0] == "FILE" and len(parts) >= 8:
            if len(parts) >= 10:
                kind, name, lines, bytes_size, mtime, mdate, ctime, cdate, remote_dir = parts[1], parts[2], parts[3], parts[4], parts[5], parts[6], parts[7], parts[8], parts[9]
            else:
                kind, name, lines, bytes_size, mtime, mdate, ctime, cdate, remote_dir = parts[1], parts[2], parts[3], parts[4], parts[5], parts[6], "", "", parts[7]
            stamp_match = re.search(rf"{re.escape(target_compact)}(\d{{6}})", name)
            stamped_target = bool(stamp_match and int(stamp_match.group(1)) >= 220000)
            fixed_name_target = name in DEFAULT_FILE_NAMES and mdate == target_date
            is_target = stamped_target or fixed_name_target
            files.append({
                "kind": kind,
                "name": name,
                "lines": int(lines or 0),
                "bytes": int(bytes_size or 0),
                "mtime": mtime,
                "mtimeDate": mdate,
                "ctime": ctime,
                "ctimeDate": cdate,
                "isToday": bool(today and mtime.startswith(today)),
                "isTargetDate": is_target,
                "dir": remote_dir,
            })
    unique_files: list[dict[str, Any]] = []
    seen_files: set[tuple[str, str]] = set()
    for item in files:
        # The same file name is expected while the consumer moves it from the
        # export folder to processados. Keep both locations as separate proof.
        key = (str(item["kind"]), str(item["name"]))
        if key in seen_files:
            continue
        seen_files.add(key)
        unique_files.append(item)
    return {
        "today": today,
        "targetDate": target_date,
        "targetCompact": target_compact,
        "dirs": dirs,
        "files": unique_files,
        "missing": missing,
        "variation": variation,
    }


def write_status(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def build_event(kind: str, parsed: dict[str, Any], env: dict[str, str], *, status_if_missing: str = "error") -> dict[str, Any]:
    if kind == "generated":
        target_time = env.get("ESTOQUE_RELEX_GENERATED_TARGET_TIME") or DEFAULT_GENERATED_TARGET_TIME
        label = "gerado"
        action = "gerado"
    else:
        target_time = env.get("ESTOQUE_RELEX_TARGET_TIME") or env.get("ESTOQUE_RELEX_PROCESSED_TARGET_TIME") or DEFAULT_PROCESSED_TARGET_TIME
        label = "consumido"
        action = "consumido"
    remote_dir = (parsed.get("dirs") or {}).get(kind) or (DEFAULT_GENERATED_DIR if kind == "generated" else DEFAULT_PROCESSED_DIR)
    target_files = [item for item in parsed["files"] if item.get("kind") == kind and item.get("isTargetDate")]
    if target_files:
        selected = max(target_files, key=lambda item: (item.get("bytes") or 0, item.get("lines") or 0))
        actual_at = selected["ctime"] if kind == "processed" and selected.get("ctime") else selected["mtime"]
        move_text = f" Movido/renomeado: {selected['ctime']}." if kind == "processed" and selected.get("ctime") else ""
        details = (
            f"Arquivo de estoque RELEX {label} para {parsed['targetDate']}: {selected['name']} em {remote_dir}. "
            f"Linhas: {selected['lines']}. Tamanho: {selected['bytes']} bytes. Modificado: {selected['mtime']}.{move_text}"
        )
        return {
            "targetTime": target_time,
            "status": "ok",
            "actualAt": actual_at,
            "count": selected["lines"],
            "source": remote_dir,
            "details": details,
            "files": [item for item in parsed["files"] if item.get("kind") == kind],
            "selectedFile": selected,
        }

    names = ", ".join(configured_file_names(env))
    seen_files = [item for item in parsed["files"] if item.get("kind") == kind]
    seen = ", ".join(f"{item['name']} modificado {item['mtime']}" for item in seen_files[:8])
    detail_seen = f" Encontrado fora da data esperada: {seen}." if seen else ""
    return {
        "targetTime": target_time,
        "status": (
            "aguardando"
            if kind == "processed" and not after_target(target_time)
            else "aguardando"
            if kind == "generated" and not after_date_target(parsed["targetDate"], target_time)
            else status_if_missing
        ),
        "actualAt": "",
        "count": 0,
        "source": remote_dir,
        "details": f"Arquivo de estoque do dia anterior ({parsed['targetDate']}) nao foi {action}. Esperado: {names} ou arquivo com data {parsed['targetCompact']} em {remote_dir}.{detail_seen}",
        "files": seen_files,
    }


def build_variation_event(parsed: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    target_time = env.get("ESTOQUE_RELEX_VARIATION_TARGET_TIME") or DEFAULT_VARIATION_TARGET_TIME
    variation = parsed.get("variation") or {}
    if variation:
        status = variation.get("status") or "error"
        if status == "error":
            details = variation.get("details") or ""
            if "nao encontrado para validar" in details and not after_date_target(parsed["targetDate"], target_time):
                status = "aguardando"
        return {
            "targetTime": target_time,
            "status": status,
            "actualAt": variation.get("actualAt") or "",
            "count": variation.get("storesChecked") or 0,
            "variationCount": variation.get("variationCount") or 0,
            "variationStores": variation.get("variationStores") or [],
            "variationThresholdPercent": variation.get("thresholdPercent") or DEFAULT_VARIATION_WARN_PERCENT,
            "source": variation.get("targetFile") or "",
            "details": variation.get("details") or "Validacao de variacao sem detalhes.",
            "files": [
                item for item in [variation.get("targetFile"), variation.get("previousFile")] if item
            ],
        }
    return {
        "targetTime": target_time,
        "status": "aguardando" if not after_target(target_time) else "error",
        "actualAt": "",
        "count": 0,
        "variationCount": 0,
        "variationStores": [],
        "variationThresholdPercent": DEFAULT_VARIATION_WARN_PERCENT,
        "source": "",
        "details": "Nao foi possivel calcular variacao do estoque.",
        "files": [],
    }


def build_events(env: dict[str, str]) -> dict[str, Any]:
    code, stdout, stderr = run_remote_check(env)
    if code != 0:
        details = (stderr or stdout or "Falha ao conectar no servidor.").strip()
        generated_dir = env.get("ESTOQUE_RELEX_GENERATED_DIR") or env.get("ESTOQUE_RELEX_SOURCE_DIR") or DEFAULT_GENERATED_DIR
        processed_dir = env.get("ESTOQUE_RELEX_REMOTE_DIR") or env.get("ESTOQUE_RELEX_PROCESSED_DIR") or DEFAULT_PROCESSED_DIR
        return {
            "arquivo_gerado": {
                "targetTime": env.get("ESTOQUE_RELEX_GENERATED_TARGET_TIME") or DEFAULT_GENERATED_TARGET_TIME,
                "status": "sem_acesso",
                "actualAt": "",
                "count": 0,
                "source": generated_dir,
                "details": f"Sem acesso ao servidor: {details[:500]}",
                "files": [],
            },
            "variacao_estoque": {
                "targetTime": env.get("ESTOQUE_RELEX_VARIATION_TARGET_TIME") or DEFAULT_VARIATION_TARGET_TIME,
                "status": "sem_acesso",
                "actualAt": "",
                "count": 0,
                "variationCount": 0,
                "variationStores": [],
                "source": generated_dir,
                "details": f"Sem acesso ao servidor: {details[:500]}",
                "files": [],
            },
            "arquivo_consumido": {
                "targetTime": env.get("ESTOQUE_RELEX_TARGET_TIME") or env.get("ESTOQUE_RELEX_PROCESSED_TARGET_TIME") or DEFAULT_PROCESSED_TARGET_TIME,
                "status": "sem_acesso",
                "actualAt": "",
                "count": 0,
                "source": processed_dir,
                "details": f"Sem acesso ao servidor: {details[:500]}",
                "files": [],
            },
        }

    parsed = parse_remote_output(stdout)
    events = {
        "arquivo_gerado": build_event("generated", parsed, env),
        "variacao_estoque": build_variation_event(parsed, env),
        "arquivo_consumido": build_event("processed", parsed, env),
    }
    if events["arquivo_gerado"].get("status") == "error" and events["arquivo_consumido"].get("status") == "ok":
        consumed = events["arquivo_consumido"]
        events["arquivo_gerado"] = {
            **events["arquivo_gerado"],
            "status": "ok",
            "actualAt": (consumed.get("selectedFile") or {}).get("mtime") or consumed.get("actualAt") or "",
            "count": consumed.get("count") or 0,
            "details": (
                "Arquivo de estoque RELEX ja foi consumido; geracao confirmada pelo arquivo em processados. "
                + str(consumed.get("details") or "")
            ),
            "files": consumed.get("files") or [],
        }
    return events


def main() -> None:
    env = load_env()
    status = {
        "collector": "estoque-relex-monitor",
        "updatedAt": iso_now(),
        "events": build_events(env),
    }
    write_status(DEFAULT_STATUS, status)
    print(f"Monitor estoque/RELEX atualizado em {DEFAULT_STATUS}")


if __name__ == "__main__":
    main()
