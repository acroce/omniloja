#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import argparse
import csv
import re
import hashlib
import collections
import tarfile
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATUS = ROOT / "outputs" / "pleno_business_monitor" / "sap_api_monitor.json"
DEFAULT_TRIAGE_ROUTING_FILE = DEFAULT_STATUS.with_name("sap_api_error_routing.json")
DEFAULT_WINDOW_MINUTES = 10
DEFAULT_HISTORY_LIMIT = 24 * 6 * 31
DEFAULT_AGGREGATE_HISTORY_LIMIT = 24 * 90
DEFAULT_DETAILS_LIMIT = 200
DEFAULT_IGNORE_CONFIG = ROOT / "config" / "sap_api_ignore_patterns.json"
DEFAULT_DETAIL_DIR = ROOT / "outputs" / "pleno_business_monitor" / "sap_api_details"
DEFAULT_CHECKIN_REPORT_DIR = ROOT / "outputs" / "pleno-checkin-nf"


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
    env.update(load_env_file(ROOT / "config" / "pedidos_business_monitor_pull.env"))
    env.update(os.environ)
    return env


def remote_config(env: dict[str, str]) -> tuple[str, str, str, str]:
    user = env.get("SAP_API_REMOTE_USER") or env.get("PEDIDOS_REMOTE_USER") or env.get("STOCK_REMOTE_USER") or ""
    host = env.get("SAP_API_REMOTE_HOST") or env.get("PEDIDOS_REMOTE_HOST") or env.get("STOCK_REMOTE_HOST") or ""
    port = env.get("SAP_API_REMOTE_PORT") or env.get("PEDIDOS_REMOTE_PORT") or env.get("STOCK_REMOTE_PORT") or "22"
    password = env.get("SAP_API_REMOTE_PASSWORD") or env.get("PEDIDOS_SSH_PASSWORD") or env.get("STOCK_REMOTE_PASSWORD") or ""
    if not user or not host:
        raise SystemExit("Configure SAP_API_REMOTE_USER/HOST ou STOCK_REMOTE_USER/HOST.")
    return user, host, port, password


def split_log_dirs(value: str | None) -> list[str]:
    if not value:
        return [
            "/var/log/pleno",
            "/usr/share/pleno/log",
            "/usr/share/pleno/logs",
            "/usr/share/pleno",
            "/servpleno/log",
            "/servpleno/logs",
            "/servpleno",
        ]
    return [item.strip() for item in value.replace(",", " ").split() if item.strip()]


def load_ignore_patterns(env: dict[str, str]) -> list[dict[str, str]]:
    patterns: list[dict[str, str]] = []
    config_path = Path(env.get("SAP_API_IGNORE_CONFIG") or DEFAULT_IGNORE_CONFIG)
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            raw_patterns = data.get("ignorePatterns") if isinstance(data, dict) else data
            if isinstance(raw_patterns, list):
                for item in raw_patterns:
                    if isinstance(item, str):
                        patterns.append({"pattern": item, "reason": item})
                    elif isinstance(item, dict) and item.get("pattern"):
                        patterns.append({
                            "pattern": str(item.get("pattern") or ""),
                            "reason": str(item.get("reason") or item.get("pattern") or ""),
                        })
        except (OSError, json.JSONDecodeError):
            pass
    env_patterns = env.get("SAP_API_IGNORE_PATTERNS") or ""
    for item in env_patterns.split(","):
        pattern = item.strip()
        if pattern:
            patterns.append({"pattern": pattern, "reason": pattern})
    if not patterns:
        patterns.append({"pattern": "chave nfe recebida", "reason": "Chave NFe nao tem 44 caracteres"})
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in patterns:
        key = item["pattern"].strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append({"pattern": item["pattern"].strip(), "reason": item["reason"].strip()})
    return deduped


def collect_script(
    window_minutes: int,
    log_dirs: list[str] | None = None,
    ignore_patterns: list[dict[str, str]] | None = None,
    transaction_id: str = "",
    details_limit: int = DEFAULT_DETAILS_LIMIT,
    start_at: str = "",
    end_at: str = "",
) -> str:
    log_dirs_literal = json.dumps(log_dirs or split_log_dirs(None))
    ignore_patterns_literal = json.dumps(ignore_patterns or [{"pattern": "chave nfe recebida", "reason": "Chave NFe nao tem 44 caracteres"}])
    transaction_id_literal = json.dumps(transaction_id or "")
    start_at_literal = json.dumps(start_at or "")
    end_at_literal = json.dumps(end_at or "")
    return f"""
from pathlib import Path
from datetime import datetime, timedelta
import collections
import json
import re
import socket
import statistics

window_minutes = {int(window_minutes)}
transaction_filter = {transaction_id_literal}
details_limit = {int(details_limit)}
requested_start = {start_at_literal}
requested_end = {end_at_literal}

def parse_requested_datetime(value):
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed

now = parse_requested_datetime(requested_end) or datetime.now()
start = parse_requested_datetime(requested_start) or (now - timedelta(minutes=window_minutes))
window_minutes = max(1, int((now - start).total_seconds() // 60) or window_minutes)
log_dirs = [Path(item) for item in {log_dirs_literal}]
ignore_patterns = {ignore_patterns_literal}
scan_days = [(start + timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range((now.date() - start.date()).days + 1)]
line_re = re.compile(r'^\\[(\\d{{4}}-\\d{{2}}-\\d{{2}})\\s+(\\d{{1,2}}:\\d{{2}}:\\d{{2}})\\.(\\d+)\\]\\s+\\[([^\\]]+)\\]\\s+(.*)$')
name_re = re.compile(r'ID\\s+(\\d+)\\s+(.+?)\\s+->')
STORE_ERROR_DEVOLUTION_MATERIALS = set("265207 223419 271667 282690 284033 158221 266604 292690 278409 261624 270819 283901 184565 273398 900514 238002 236640 279111 301061".split())

def ignored_reason(msg):
    low = msg.lower()
    for item in ignore_patterns:
        pattern = str(item.get("pattern") or "").lower()
        if pattern and pattern in low:
            return str(item.get("reason") or item.get("pattern") or "Ignorado")
    return ""

def extract_attempt(msg):
    match = re.search(r'\\bTentativa\\s+(\\d+)\\b', msg, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None

def is_waiting_retry(msg):
    low = msg.lower()
    attempt = extract_attempt(msg)
    if attempt is None or attempt >= 5:
        return False
    strong_error_terms = [
        "nf não teve retorno",
        "nf nao teve retorno",
        "nf-e inexistente",
        "falha",
        "erro:",
        "exception",
        "timeout",
        "não está atualizado",
        "nao esta atualizado",
        "não foi possível",
        "nao foi possivel",
        "bloqueados pelo usuário",
        "bloqueados pelo usuario",
    ]
    if any(term in low for term in strong_error_terms):
        return False
    return "br_nfedocumentstatus" in low and ("nova chamada" in low or "será realizada" in low or "sera realizada" in low)

def nfe_document_status(msg):
    for pattern in [
        r'BR_NFeDocumentStatus[^0-9]{{0,24}}([0-3])',
        r'Motivo +([23]) *:',
    ]:
        match = re.search(pattern, msg, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None

def sap_application_error(msg):
    code_match = re.search(r'\[code\]\s*=>\s*([A-Z]{{1,8}}/\d{{1,6}})', msg, flags=re.IGNORECASE)
    if not code_match:
        # O Pleno tambem grava um resumo final do SAP, por exemplo:
        # "Centro de custo AC01/101010211 em 12.08.2026 nao existe - KI/222".
        # Ele e o mesmo erro, mas nao possui o bloco "[code] =>".
        code_match = re.search(
            r'(?<![A-Z0-9/])([A-Z]{{1,8}}/\d{{1,6}})(?![A-Z0-9/])',
            msg,
            flags=re.IGNORECASE,
        )
    if not code_match:
        return "", ""
    code = code_match.group(1).upper()
    message_match = re.search(r'\[message\]\s*=>\s*([^\\r\\n]+)', msg, flags=re.IGNORECASE)
    message = message_match.group(1).strip() if message_match else ""
    if not message and code == "KI/222":
        direct_message = re.search(
            r'(Centro de custo\s+.+?\s+em\s+\d{{2}}\.\d{{2}}\.\d{{4}}\s+n(?:ã|a)o existe)',
            msg,
            flags=re.IGNORECASE,
        )
        message = direct_message.group(1).strip() if direct_message else ""
    return code, message[:220]

def logged_return_reason(msg):
    unknown_match = re.search(r'Erro desconhecido[ \t]*-[ \t]*(.+)', msg, flags=re.IGNORECASE)
    if unknown_match:
        value = unknown_match.group(1).strip()
        if value:
            return value[:220]
    for pattern in [
        r'\[(?:reason|motivo)\]\s*=>\s*([^\\r\\n]+)',
        r'(?:"(?:reason|motivo)"|(?:reason|motivo))\s*[:=]\s*["\\']?([^"\\'\\r\\n,}}]+)',
        r'\[(?:message|mensagem)\]\s*=>\s*([^\\r\\n]+)',
    ]:
        match = re.search(pattern, msg, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if value:
                return value[:220]
    return ""

def sap_response_failure(msg):
    status_match = re.search(r'(?:\[status\]\s*=>\s*|["\\']status["\\']\s*[:=]\s*)([45]\d{{2}})', msg, flags=re.IGNORECASE)
    if not status_match:
        return None, ""
    status = status_match.group(1)
    message_match = re.search(r'\[message\]\s*=>\s*([^\\r\\n]+)', msg, flags=re.IGNORECASE)
    if not message_match:
        message_match = re.search(r'["\\']message["\\']\s*[:=]\s*["\\']?([^"\\'\\r\\n,}}]+)', msg, flags=re.IGNORECASE)
    message = message_match.group(1).strip() if message_match else ""
    message = message.split(" : " + status, 1)[0].split(" : HTTP", 1)[0].strip()
    return status, message[:120]

def classify(msg):
    if ignored_reason(msg):
        return "ignored"
    low = msg.lower()
    if nfe_document_status(msg) in [2, 3]:
        return "error"
    if sap_application_error(msg)[0]:
        return "error"
    if "erro desconhecido" in low:
        return "error"
    response_status, _ = sap_response_failure(msg)
    if response_status:
        return "error"
    if "execução com sucesso" in low or "execucao com sucesso" in low or re.search(r'\\b0\\|', msg) or re.search(r'\\bOK\\b', msg):
        return "success"
    if is_waiting_retry(msg):
        return "ignored"
    error_terms = [
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
        "dados de centro do material",
        "bloqueados pelo usuário",
        "bloqueados pelo usuario",
    ]
    if any(term in low for term in error_terms):
        return "error"
    # Uma chamada sem conclusao tambem e uma ocorrencia a investigar. Caso o
    # RESPONSE apareca nas linhas seguintes, a classificacao sera atualizada.
    if "chamada:" in low or logged_return_reason(msg):
        return "error"
    return "other"

def reason(msg):
    ignored = ignored_reason(msg)
    if ignored:
        return ignored
    low = msg.lower()
    document_status = nfe_document_status(msg)
    if document_status == 2:
        return "NF-e recusada no SAP (BR_NFeDocumentStatus=2)"
    if document_status == 3:
        return "NF-e rejeitada no SAP (BR_NFeDocumentStatus=3)"
    sap_code, sap_message = sap_application_error(msg)
    if sap_code == "KI/222":
        return "SAP KI/222 - Centro de custo inexistente"
    if "erro desconhecido" in low:
        return f"Pleno - {{logged_return_reason(msg) or 'erro desconhecido sem retorno detalhado'}}"
    if is_waiting_retry(msg):
        attempt = extract_attempt(msg)
        return f"Tentativa SAP em andamento ({{attempt}}/5)"
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
    if "dados de centro do material" in low and ("bloqueados pelo usuário" in low or "bloqueados pelo usuario" in low):
        return "Dados de centro do material bloqueados por usuario"
    if sap_code:
        return f"SAP {{sap_code}} - {{sap_message or 'erro retornado pelo SAP'}}"
    return_reason = logged_return_reason(msg)
    if return_reason:
        return f"SAP - {{return_reason}}"
    response_status, response_message = sap_response_failure(msg)
    if response_status:
        return f"SAP HTTP {{response_status}} - {{response_message or 'erro retornado pelo SAP'}}"
    if classify(msg) == "success":
        return "Sucesso"
    if "chamada:" in low:
        return "Pleno - chamada sem retorno registrado"
    return "Pleno - retorno sem motivo classificavel"

def extract_payload(msg):
    start_at = msg.find("{{")
    end_at = msg.rfind("}}")
    if start_at != -1 and end_at != -1 and end_at > start_at:
        try:
            return json.loads(msg[start_at:end_at + 1])
        except Exception:
            pass
    json_match = re.search(r'\\bJSON=\\s*(\\{{.*?\\}})\\s*(?:-\\s*RESPONSE:|$)', msg, flags=re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except Exception:
            pass
    request_block = extract_print_r_section(msg, r'com os dados=\\s*Array', [r'\\bJSON=', r'-\\s*RESPONSE:'])
    if request_block:
        return parse_print_r(request_block)
    return None

def extract_response_payload(msg):
    response_block = extract_print_r_section(msg, r'-\\s*RESPONSE:\\s*Array', [])
    if response_block:
        return parse_print_r(response_block)
    return None

def extract_print_r_section(msg, start_pattern, stop_patterns):
    start_match = re.search(start_pattern, msg, flags=re.IGNORECASE)
    if not start_match:
        return ""
    text = msg[start_match.end():]
    for stop_pattern in stop_patterns:
        stop_match = re.search(stop_pattern, text, flags=re.IGNORECASE)
        if stop_match:
            text = text[:stop_match.start()]
            break
    return text.strip()

def parse_print_r(text):
    root = {{}}
    stack = [root]
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line == "(":
            continue
        if line == ")":
            if len(stack) > 1:
                stack.pop()
            continue
        match = re.match(r'^\\[([^\\]]+)\\]\\s*=>\\s*(.*)$', line)
        if not match:
            continue
        key = match.group(1)
        value = match.group(2).strip()
        current = stack[-1]
        if value == "Array":
            child = {{}}
            current[key] = child
            stack.append(child)
        else:
            current[key] = value
    return normalize_print_r(root)

def normalize_print_r(value):
    if isinstance(value, dict):
        normalized = {{key: normalize_print_r(item) for key, item in value.items()}}
        keys = list(normalized.keys())
        if keys and all(str(key).isdigit() for key in keys):
            ordered = sorted((int(key), item) for key, item in normalized.items())
            if [index for index, _ in ordered] == list(range(len(ordered))):
                return [item for _, item in ordered]
        return normalized
    return value

def find_nested_value(value, key_terms):
    if isinstance(value, dict):
        for key, item in value.items():
            low_key = str(key).lower()
            if any(term in low_key for term in key_terms) and item not in (None, ""):
                return str(item)
            nested = find_nested_value(item, key_terms)
            if nested:
                return nested
    elif isinstance(value, list):
        for item in value:
            nested = find_nested_value(item, key_terms)
            if nested:
                return nested
    return None

def find_nested_values(value, key_terms):
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            low_key = str(key).lower()
            if any(term in low_key for term in key_terms) and item not in (None, ""):
                found.append(str(item))
            found.extend(find_nested_values(item, key_terms))
    elif isinstance(value, list):
        for item in value:
            found.extend(find_nested_values(item, key_terms))
    return found

def is_devolution_context(transaction_id, label, msg):
    text = " ".join([str(transaction_id or ""), str(label or ""), str(msg or "")]).lower()
    return "devolu" in text

def devolution_store_error_materials(msg, payload):
    found = set()
    for match in re.finditer(r'\\[(?:material|matnr|sku|produto)\\]\\s*=>\\s*([A-Za-z0-9._-]+)', msg, flags=re.IGNORECASE):
        value = re.sub(r'\\D+', '', match.group(1))
        if value in STORE_ERROR_DEVOLUTION_MATERIALS:
            found.add(value)
    if payload:
        for value in find_nested_values(payload, ["material", "matnr", "produto", "sku"]):
            digits = re.sub(r'\\D+', '', str(value))
            if digits in STORE_ERROR_DEVOLUTION_MATERIALS:
                found.add(digits)
    return sorted(found, key=int)

def extract_note_and_key(msg):
    payload = extract_payload(msg)
    key_match = re.search(r'\\b(\\d{{44}})\\b', msg)
    note_patterns = [
        r'BR_NotaFiscal\\s*[=:|-]\\s*(\\d+)',
        r'NotaFiscal\\s*[=:|-]\\s*(\\d+)',
        r'nota[_\\s-]*fiscal\\s*[=:|-]\\s*(\\d+)',
        r'numero[_\\s-]*nf\\s*[=:|-]\\s*(\\d+)',
        r'nr[_\\s-]*nf\\s*[=:|-]\\s*(\\d+)',
        r'num[_\\s-]*nota\\s*[=:|-]\\s*(\\d+)',
        r'\\bnota\\s*[=:|-]\\s*(\\d+)',
        r'\\b(?:documento|doc)\\s*[=:|-]\\s*(\\d+)',
        r'\\[(?:documento|doc)\\]\\s*=>\\s*(\\d+)',
        r'\\bnNF\\s*[=:|-]\\s*"?\\s*(\\d+)',
        r'"nNF"\\s*:\\s*"?\\s*(\\d+)',
        r'\\bnf\\s*[=:|-]\\s*(\\d+)',
        r'NF-e\\s+inexistente\\s+no\\s+INBOUND\\s*\\|\\s*NF\\s*-\\s*(\\d+)',
    ]
    note = None
    for pattern in note_patterns:
        match = re.search(pattern, msg, flags=re.IGNORECASE)
        if match:
            note = match.group(1)
            break
    if payload:
        if not key_match:
            payload_key = find_nested_value(payload, ["chave", "accesskey", "nfechave", "chavenfe"])
            if payload_key:
                key_match = re.search(r'\\b(\\d{{44}})\\b', payload_key)
        if not note:
            payload_note = find_nested_value(payload, ["notafiscal", "numero_nf", "nr_nf", "numnf", "nnf", "num_nota", "nota", "documento", "doc"])
            if payload_note:
                match = re.search(r'\\d+', payload_note)
                if match:
                    note = match.group(0)
    return note, key_match.group(1) if key_match else None, payload

def only_digits(value):
    if value is None:
        return None
    match = re.search(r'\\d+', str(value))
    if not match:
        return None
    return str(int(match.group(0)))

def extract_context_values(msg, payload):
    center = None
    store = None
    material = None
    center_match = re.search(r'\\bcentro\\s+0*(\\d{{1,6}})\\b', msg, flags=re.IGNORECASE)
    if center_match:
        center = str(int(center_match.group(1)))
        store = center
    if not center:
        center_array_match = re.search(r'\\[(?:centro|werks|plant)\\]\\s*=>\\s*0*(\\d{{1,6}})', msg, flags=re.IGNORECASE)
        if center_array_match:
            center = str(int(center_array_match.group(1)))
            store = center
    store_patterns = [
        r'\\bloja\\s*[=:|-]\\s*0*(\\d{{1,6}})',
        r'\\bfilial\\s*[=:|-]\\s*0*(\\d{{1,6}})',
        r'\\bstore\\s*[=:|-]\\s*0*(\\d{{1,6}})',
        r'\\bbranch\\s*[=:|-]\\s*0*(\\d{{1,6}})',
        r'\\[(?:loja|filial|store|branch)\\]\\s*=>\\s*0*(\\d{{1,6}})',
        r'\\[(?:centro|werks|plant)\\]\\s*=>\\s*0*(\\d{{1,6}})',
    ]
    for pattern in store_patterns:
        match = re.search(pattern, msg, flags=re.IGNORECASE)
        if match:
            store = str(int(match.group(1)))
            break
    material_patterns = [
        r'\\bMaterial\\s+([A-Za-z0-9._-]+)',
        r'\\bmaterial\\s*[=:|-]\\s*([A-Za-z0-9._-]+)',
        r'\\bmatnr\\s*[=:|-]\\s*([A-Za-z0-9._-]+)',
        r'\\bsku\\s*[=:|-]\\s*([A-Za-z0-9._-]+)',
        r'\\bproduto\\s*[=:|-]\\s*([A-Za-z0-9._-]+)',
        r'\\[(?:material|matnr|sku|produto)\\]\\s*=>\\s*([A-Za-z0-9._-]+)',
    ]
    for pattern in material_patterns:
        match = re.search(pattern, msg, flags=re.IGNORECASE)
        if match:
            material = match.group(1).strip()
            break
    if payload:
        if not center:
            center = only_digits(find_nested_value(payload, ["centro", "werks", "plant"]))
        if not store:
            store = only_digits(find_nested_value(payload, ["loja", "filial", "store", "branch"]))
        if not material:
            material_value = find_nested_value(payload, ["material", "matnr", "produto", "sku"])
            if material_value:
                material = str(material_value).strip()
        if center and not store:
            store = center
    return store, center, material

def apply_response_reference(detail):
    # O payload da chamada pode conter muitos itens. Quando o SAP aponta um
    # material especifico no retorno, ele e a referencia mais util para a area.
    response = "\\n".join(str(detail.get(key) or "") for key in ["returnReason", "sapMessage", "raw"])
    material_match = re.search(
        r'(?:dados de centro do material|lista t[eé]cnica para material|material)\\s+0*(\\d{{1,18}})\\b',
        response,
        flags=re.IGNORECASE,
    )
    if material_match:
        detail["material"] = str(int(material_match.group(1)))
    center_match = re.search(r'\\b(?:no|em)\\s+centro\\s+0*(\\d{{1,6}})\\b', response, flags=re.IGNORECASE)
    if center_match:
        detail["center"] = str(int(center_match.group(1)))
        detail["store"] = detail.get("store") or detail["center"]
    return detail

def event_detail(event_at, status, item_reason, msg, raw):
    note, access_key, payload = extract_note_and_key(msg)
    response_payload = extract_response_payload(msg)
    store, center, material = extract_context_values(msg, payload)
    attempt = extract_attempt(msg)
    sap_code, sap_message = sap_application_error(msg)
    return_reason = logged_return_reason(msg)
    document_status = nfe_document_status(msg)
    request_url_match = re.search(r'Chamada:\\s*(https?://[^\\s]+)', msg, flags=re.IGNORECASE)
    request_url = request_url_match.group(1) if request_url_match else None
    request_endpoint = request_url.split('?', 1)[0].rstrip('/').rsplit('/', 1)[-1] if request_url else None
    document_status_description = {{
        2: "Recusada. Aguardando SAP",
        3: "Rejeitada. Aguardando SAP",
    }}.get(document_status)
    detail = {{
        "at": event_at.isoformat(sep=" ", timespec="milliseconds"),
        "status": status,
        "reason": item_reason,
        "note": note,
        "accessKey": access_key,
        "store": store,
        "center": center,
        "material": material,
        "storeErrorMaterials": [],
        "storeError": False,
        "attempt": attempt,
        "maxAttempts": 5 if attempt is not None else None,
        "sapCode": sap_code or None,
        "sapMessage": sap_message or None,
        "returnReason": return_reason or None,
        "nfeDocumentStatus": document_status,
        "nfeDocumentStatusDescription": document_status_description,
        "requestEndpoint": request_endpoint,
        "requestUrl": request_url,
        "payload": payload,
        "responsePayload": response_payload,
        "raw": raw.strip()[:1800],
    }}
    return apply_response_reference(detail)

def apply_devolution_store_error(detail, transaction_id, label):
    payload = detail.get("payload")
    blocked = devolution_store_error_materials(str(detail.get("raw") or ""), payload)
    if not blocked or not is_devolution_context(transaction_id, label, detail.get("raw")):
        return detail
    detail["status"] = "error"
    detail["reason"] = "Erro da loja - material de devolucao"
    detail["storeError"] = True
    detail["storeErrorMaterials"] = blocked
    if not detail.get("material"):
        detail["material"] = blocked[0]
    return detail

def has_reference(detail):
    return any(detail.get(key) for key in ["note", "accessKey", "store", "center", "material"])

def merge_context_detail(detail, msg, raw):
    note, access_key, payload = extract_note_and_key(msg)
    response_payload = extract_response_payload(msg)
    store, center, material = extract_context_values(msg, payload)
    if note and not detail.get("note"):
        detail["note"] = note
    if access_key and not detail.get("accessKey"):
        detail["accessKey"] = access_key
    if store and not detail.get("store"):
        detail["store"] = store
    if center and not detail.get("center"):
        detail["center"] = center
    if material and not detail.get("material"):
        detail["material"] = material
    if payload and not detail.get("payload"):
        detail["payload"] = payload
    if response_payload and not detail.get("responsePayload"):
        detail["responsePayload"] = response_payload
    current_raw = str(detail.get("raw") or "")
    extra = raw.strip()
    if extra and extra not in current_raw and len(current_raw) < 3500:
        detail["raw"] = (current_raw + "\\n" + extra).strip()[:3500]
    payload = extract_payload(detail["raw"])
    response_payload = extract_response_payload(detail["raw"])
    if payload:
        detail["payload"] = payload
    if response_payload:
        detail["responsePayload"] = response_payload
    sap_code, sap_message = sap_application_error(str(detail.get("raw") or "") + "\\n" + raw)
    if sap_code:
        detail["sapCode"] = sap_code
    if sap_message:
        detail["sapMessage"] = sap_message
    return_reason = logged_return_reason(str(detail.get("raw") or "") + "\\n" + raw)
    if return_reason:
        detail["returnReason"] = return_reason
    apply_response_reference(detail)
    apply_devolution_store_error(detail, "", "")
    return detail

def classify_detail(detail):
    # O raw e limitado para nao gravar respostas enormes. Quando o codigo SAP
    # aparece depois desse limite, os campos estruturados continuam sendo a fonte
    # correta para classificar o mesmo evento.
    if detail.get("sapCode"):
        return "error"
    # Retornos como "Nao foi possivel explosao..." podem surgir depois do
    # limite do raw. O motivo extraido continua disponivel em returnReason.
    context = "\\n".join(str(detail.get(key) or "") for key in ["raw", "returnReason", "sapMessage"])
    return classify(context)

def reason_detail(detail):
    sap_code = str(detail.get("sapCode") or "").upper()
    if sap_code == "KI/222":
        return "SAP KI/222 - Centro de custo inexistente"
    if sap_code:
        return f"SAP {{sap_code}} - {{detail.get('sapMessage') or 'erro retornado pelo SAP'}}"
    context = "\\n".join(str(detail.get(key) or "") for key in ["raw", "returnReason", "sapMessage"])
    return reason(context)

def is_response_continuation(msg):
    # Dependendo do LogLevel, o Pleno pode repetir "ID 050 ... ->" em
    # todas as linhas do RESPONSE. O bloco ainda e resposta da chamada anterior.
    return bool(re.search(
        r'(?:-\\s*RESPONSE\s*:|\\[?(?:error|code|message)\\]?\\s*=>|\\bKI/\\d+\\b|Centro de custo .+ nao existe|Centro de custo .+ não existe)',
        str(msg or ""),
        flags=re.IGNORECASE,
    ))

def percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[int(p * (len(ordered) - 1))]

transactions = []
log_files = []
seen_paths = set()
for log_dir in log_dirs:
    if not log_dir.exists():
        continue
    for scan_day in scan_days:
        for path in list(log_dir.glob(f"LOG.API.SAP.INTEGRATION.*.{{scan_day}}.log")) + list(log_dir.rglob(f"LOG.API.SAP.INTEGRATION.*.{{scan_day}}.log")):
            path_key = str(path)
            if path_key not in seen_paths:
                seen_paths.add(path_key)
                log_files.append(path)

for path in sorted(log_files):
    path_tx_id = re.sub(r'\\.\\d{{4}}-\\d{{2}}-\\d{{2}}$', '', path.stem.replace("LOG.API.SAP.INTEGRATION.", ""))
    if transaction_filter and path_tx_id != transaction_filter:
        continue
    events = []
    counts = collections.Counter()
    reasons = collections.Counter()
    error_reasons = collections.Counter()
    unclassified_reasons = collections.Counter()
    ignored_reasons = collections.Counter()
    notes = collections.Counter()
    sample_errors = []
    sample_others = []
    error_details = []
    other_details = []
    ignored_details = []
    reference_details = []
    retry_attempts = {{}}
    seen_references = set()
    label = path.name
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        continue
    with handle:
        context_at = None
        active_detail = None
        request_context = None
        for raw in handle:
            match = line_re.match(raw)
            if not match:
                if context_at and active_detail:
                    context_msg = raw.strip()
                    previous_status = active_detail.get("status")
                    previous_reason = active_detail.get("reason")
                    merge_context_detail(active_detail, context_msg, raw)
                    active_detail["status"] = classify_detail(active_detail)
                    active_detail["reason"] = reason_detail(active_detail)
                    apply_devolution_store_error(active_detail, path_tx_id, label)
                    if active_detail.get("status") != "error":
                        error_details = [item for item in error_details if item is not active_detail]
                    if active_detail.get("status") != "other":
                        other_details = [item for item in other_details if item is not active_detail]
                    if active_detail.get("status") != previous_status or active_detail.get("reason") != previous_reason:
                        if previous_status:
                            counts[previous_status] -= 1
                        if previous_status == "ignored":
                            ignored_reasons[previous_reason] -= 1
                        elif previous_reason:
                            reasons[previous_reason] -= 1
                        if previous_status == "error" and previous_reason:
                            error_reasons[previous_reason] -= 1
                        if previous_status == "other":
                            unclassified_reasons[previous_reason] -= 1
                        counts[active_detail["status"]] += 1
                        if active_detail["status"] == "ignored":
                            ignored_reasons[active_detail["reason"]] += 1
                        else:
                            reasons[active_detail["reason"]] += 1
                        if active_detail["status"] == "error":
                            error_reasons[active_detail["reason"]] += 1
                        if active_detail["status"] == "other":
                            unclassified_reasons[active_detail["reason"]] += 1
                        if active_detail["status"] == "error":
                            other_details = [item for item in other_details if item is not active_detail]
                            if active_detail not in error_details and len(error_details) < details_limit:
                                error_details.append(active_detail)
                    if active_detail.get("note"):
                        notes[active_detail["note"]] += 1
                    reference_key = "|".join(str(active_detail.get(key) or "") for key in ["note", "accessKey", "store", "center", "material"])
                    if has_reference(active_detail) and reference_key not in seen_references and len(reference_details) < details_limit:
                        seen_references.add(reference_key)
                        reference_details.append(active_detail)
                continue
            micro = (match.group(3) + "000000")[:6]
            try:
                event_at = datetime.strptime(match.group(1) + " " + match.group(2) + "." + micro, "%Y-%m-%d %H:%M:%S.%f")
            except ValueError:
                continue
            # Os arquivos diarios do Pleno sao cronologicos. Em consultas
            # historicas, nao vale percorrer o restante do arquivo depois do
            # fim solicitado; isso reduz muito o tempo de uma janela por hora.
            if event_at > now:
                break
            if not (start <= event_at <= now):
                context_at = None
                active_detail = None
                continue
            previous_detail = active_detail
            previous_at = context_at
            context_at = event_at
            msg = match.group(5).strip()
            # Alguns logs gravam cada linha do RESPONSE com timestamp proprio.
            # Nesses casos, ela ainda pertence a chamada anterior e nao e outro evento.
            if (
                previous_detail
                and previous_at
                and (event_at - previous_at).total_seconds() <= 15
                and is_response_continuation(msg)
                and not name_re.search(msg)
            ):
                previous_status = previous_detail.get("status")
                previous_reason = previous_detail.get("reason")
                merge_context_detail(previous_detail, msg, raw)
                previous_detail["status"] = classify_detail(previous_detail)
                previous_detail["reason"] = reason_detail(previous_detail)
                apply_devolution_store_error(previous_detail, path_tx_id, label)
                if previous_detail.get("status") != "error":
                    error_details = [item for item in error_details if item is not previous_detail]
                if previous_detail.get("status") != "other":
                    other_details = [item for item in other_details if item is not previous_detail]
                if previous_detail.get("status") != previous_status or previous_detail.get("reason") != previous_reason:
                    if previous_status:
                        counts[previous_status] -= 1
                    if previous_status == "ignored":
                        ignored_reasons[previous_reason] -= 1
                    elif previous_reason:
                        reasons[previous_reason] -= 1
                    if previous_status == "error" and previous_reason:
                        error_reasons[previous_reason] -= 1
                    if previous_status == "other":
                        unclassified_reasons[previous_reason] -= 1
                    counts[previous_detail["status"]] += 1
                    if previous_detail["status"] == "ignored":
                        ignored_reasons[previous_detail["reason"]] += 1
                    else:
                        reasons[previous_detail["reason"]] += 1
                    if previous_detail["status"] == "error":
                        error_reasons[previous_detail["reason"]] += 1
                    if previous_detail["status"] == "other":
                        unclassified_reasons[previous_detail["reason"]] += 1
                    if previous_detail["status"] == "error":
                        other_details = [item for item in other_details if item is not previous_detail]
                        if previous_detail not in error_details and len(error_details) < details_limit:
                            error_details.append(previous_detail)
                active_detail = previous_detail
                continue
            active_detail = None
            msg_lower = msg.lower()
            if not any(token in msg_lower for token in ["chamada:", "execução", "execucao", "ok", "falha", "não", "nao", "erro"]):
                continue
            name_match = name_re.search(msg)
            if name_match:
                label = f"ID {{name_match.group(1)}} - {{name_match.group(2)}}"
            status = classify(msg)
            item_reason = reason(msg)
            detail = event_detail(event_at, status, item_reason, msg, raw)
            # O ID 101 pode registrar o BR_NFeDocumentStatus em uma linha
            # separada do envio. Herdamos a referencia da chamada anterior para
            # que a fila de encaminhamento tenha loja, NF/doc e chave.
            if "chamada:" in msg_lower and has_reference(detail):
                request_context = detail
            elif detail.get("nfeDocumentStatus") in [2, 3] and request_context:
                for context_field in ["note", "accessKey", "store", "center", "material", "payload", "requestEndpoint", "requestUrl"]:
                    if not detail.get(context_field) and request_context.get(context_field):
                        detail[context_field] = request_context[context_field]
            apply_devolution_store_error(detail, path_tx_id, label)
            status = detail["status"]
            item_reason = detail["reason"]
            waiting_retry = is_waiting_retry(msg)
            if detail.get("note"):
                notes[detail["note"]] += 1
                if status == "success" and detail["note"] in retry_attempts:
                    retry_attempts[detail["note"]]["completed"] = True
                    retry_attempts[detail["note"]]["completedAt"] = detail["at"]
                if waiting_retry:
                    note_key = detail["note"]
                    current_retry = retry_attempts.get(note_key, {{
                        "note": note_key,
                        "attempts": 0,
                        "maxAttempt": 0,
                        "maxAttempts": detail.get("maxAttempts") or 5,
                        "firstAt": detail["at"],
                        "lastAt": detail["at"],
                        "completed": False,
                    }})
                    current_retry["attempts"] += 1
                    current_retry["maxAttempt"] = max(int(current_retry.get("maxAttempt") or 0), int(detail.get("attempt") or 0))
                    current_retry["lastAt"] = detail["at"]
                    retry_attempts[note_key] = current_retry
            events.append(event_at)
            counts[status] += 1
            if status == "ignored":
                ignored_reasons[item_reason] += 1
            else:
                reasons[item_reason] += 1
            if status == "error":
                error_reasons[item_reason] += 1
            if status == "other":
                unclassified_reasons[item_reason] += 1
            if status == "error" and len(sample_errors) < 5:
                sample_errors.append(raw.strip()[:900])
            if status == "other" and not waiting_retry and len(sample_others) < 10:
                sample_others.append(raw.strip()[:900])
            # A correlacao da chamada com o RESPONSE precisa existir mesmo apos
            # atingir o limite de detalhes salvos. O limite controla apenas o
            # tamanho do JSON; nao pode alterar a classificacao dos eventos.
            if status in ["error", "other", "ignored"]:
                active_detail = detail
            if status == "error" and len(error_details) < details_limit:
                error_details.append(detail)
            if status == "other" and not waiting_retry and len(other_details) < details_limit:
                other_details.append(detail)
            if status == "ignored" and not waiting_retry and len(ignored_details) < min(details_limit, 200):
                ignored_details.append(detail)
            if status in ["error", "other", "ignored"] and not waiting_retry:
                reference_key = "|".join(str(detail.get(key) or "") for key in ["note", "accessKey", "store", "center", "material"])
                if has_reference(detail) and reference_key not in seen_references and len(reference_details) < details_limit:
                    seen_references.add(reference_key)
                    reference_details.append(detail)
    if not events:
        continue
    counts = +counts
    reasons = +reasons
    error_reasons = +error_reasons
    unclassified_reasons = +unclassified_reasons
    ignored_reasons = +ignored_reasons
    gaps = [(b - a).total_seconds() for a, b in zip(events, events[1:]) if (b - a).total_seconds() >= 0]
    total = len(events)
    monitored_total = max(total - counts["ignored"], 0)
    transactions.append({{
        "id": path_tx_id,
        "label": label,
        "file": str(path),
        "events": total,
        "monitoredEvents": monitored_total,
        "success": counts["success"],
        "errors": counts["error"],
        "ignored": counts["ignored"],
        "other": counts["other"],
        "successRate": round(counts["success"] / monitored_total * 100, 2) if monitored_total else 0,
        "errorRate": round(counts["error"] / monitored_total * 100, 2) if monitored_total else 0,
        "ignoredRate": round(counts["ignored"] / total * 100, 2) if total else 0,
        "avgResponseGapSeconds": round(statistics.mean(gaps), 3) if gaps else None,
        "medianResponseGapSeconds": round(statistics.median(gaps), 3) if gaps else None,
        "p95ResponseGapSeconds": round(percentile(gaps, 0.95), 3) if gaps else None,
        "maxResponseGapSeconds": round(max(gaps), 3) if gaps else None,
        "eventsPerMinute": round(total / max((events[-1] - events[0]).total_seconds() / 60, 1 / 60), 2),
        "firstEventAt": events[0].isoformat(sep=" ", timespec="milliseconds"),
        "lastEventAt": events[-1].isoformat(sep=" ", timespec="milliseconds"),
        "topReasons": [{{"reason": key, "count": value}} for key, value in reasons.most_common(8)],
        "errorReasons": [{{"reason": key, "count": value}} for key, value in error_reasons.most_common(40)],
        "unclassifiedReasons": [{{"reason": key, "count": value}} for key, value in unclassified_reasons.most_common(10)],
        "ignoredReasons": [{{"reason": key, "count": value}} for key, value in ignored_reasons.most_common(8)],
        "topNotes": [{{"note": key, "count": value}} for key, value in notes.most_common(8)],
        "retryAttempts": sorted((item for item in retry_attempts.values() if not item.get("completed")), key=lambda item: (-int(item.get("maxAttempt") or 0), item.get("note") or ""))[:20],
        "referenceDetails": reference_details,
        "sampleErrors": sample_errors,
        "sampleOthers": sample_others,
        "errorDetails": error_details,
        "otherDetails": other_details,
        "ignoredDetails": ignored_details,
    }})

totals = {{
    "events": sum(item["events"] for item in transactions),
    "monitoredEvents": sum(item["monitoredEvents"] for item in transactions),
    "success": sum(item["success"] for item in transactions),
    "errors": sum(item["errors"] for item in transactions),
    "ignored": sum(item["ignored"] for item in transactions),
    "other": sum(item["other"] for item in transactions),
}}
totals["successRate"] = round(totals["success"] / totals["monitoredEvents"] * 100, 2) if totals["monitoredEvents"] else 0
totals["errorRate"] = round(totals["errors"] / totals["monitoredEvents"] * 100, 2) if totals["monitoredEvents"] else 0
totals["ignoredRate"] = round(totals["ignored"] / totals["events"] * 100, 2) if totals["events"] else 0

print(json.dumps({{
    "collectedAt": now.astimezone().isoformat(timespec="seconds"),
    "windowStart": start.astimezone().isoformat(timespec="seconds"),
    "windowEnd": now.astimezone().isoformat(timespec="seconds"),
    "windowMinutes": window_minutes,
    "host": socket.gethostname(),
    "logDirs": [str(item) for item in log_dirs],
    "matchedLogFiles": [str(item) for item in sorted(log_files)],
    "ignorePatterns": ignore_patterns,
    "totals": totals,
    "transactions": transactions,
}}, ensure_ascii=False))
"""


def remote_script(
    window_minutes: int,
    log_dirs: list[str],
    ignore_patterns: list[dict[str, str]],
    transaction_id: str = "",
    details_limit: int = DEFAULT_DETAILS_LIMIT,
    start_at: str = "",
    end_at: str = "",
) -> str:
    return "python3 - <<'PY'\n" + collect_script(window_minutes, log_dirs, ignore_patterns, transaction_id, details_limit, start_at, end_at) + "PY"


def run_remote_collect(
    env: dict[str, str],
    window_minutes: int,
    transaction_id: str = "",
    details_limit: int = DEFAULT_DETAILS_LIMIT,
    start_at: str = "",
    end_at: str = "",
) -> dict[str, Any]:
    user, host, port, password = remote_config(env)
    log_dirs = split_log_dirs(env.get("SAP_API_REMOTE_LOG_DIRS") or env.get("SAP_API_LOG_DIRS"))
    ignore_patterns = load_ignore_patterns(env)
    ssh_cmd = [
        "ssh",
        "-p",
        str(port),
        "-o",
        "BatchMode=no" if password else "BatchMode=yes",
        "-o",
        "ConnectTimeout=60",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "LogLevel=ERROR",
        f"{user}@{host}",
        "sh",
        "-s",
    ]
    cmd = ssh_cmd
    proc_env = os.environ.copy()
    if password:
        cmd = ["sshpass", "-p", password, *ssh_cmd]
    completed = subprocess.run(
        cmd,
        input=remote_script(window_minutes, log_dirs, ignore_patterns, transaction_id, details_limit, start_at, end_at),
        text=True,
        capture_output=True,
        env=proc_env,
        timeout=int(env.get("SAP_API_MONITOR_TIMEOUT_SECONDS", "180")),
        check=False,
    )
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "Falha ao coletar logs SAP.").strip()
        raise RuntimeError(details[:2000])
    return json.loads(completed.stdout)


def fetch_remote_log_archive(env: dict[str, str], start_at: datetime, end_at: datetime, destination: Path) -> Path:
    """Baixa uma unica copia compactada dos logs para reprocessamento local."""
    user, host, port, password = remote_config(env)
    log_dirs = split_log_dirs(env.get("SAP_API_REMOTE_LOG_DIRS") or env.get("SAP_API_LOG_DIRS"))
    scan_days = [
        (start_at + timedelta(days=offset)).strftime("%Y-%m-%d")
        for offset in range((end_at.date() - start_at.date()).days + 1)
    ]
    archive_script = """python3 - <<'PY'
from pathlib import Path
import tarfile
import sys

log_dirs = {log_dirs!r}
scan_days = {scan_days!r}
paths = []
seen = set()
for raw_dir in log_dirs:
    root = Path(raw_dir)
    if not root.exists():
        continue
    for day in scan_days:
        for path in list(root.glob(f'LOG.API.SAP.INTEGRATION.*.{{day}}.log')) + list(root.rglob(f'LOG.API.SAP.INTEGRATION.*.{{day}}.log')):
            key = str(path)
            if key not in seen and path.is_file():
                seen.add(key)
                paths.append(path)
with tarfile.open(fileobj=sys.stdout.buffer, mode='w|gz') as archive:
    for index, path in enumerate(sorted(paths)):
        archive.add(path, arcname=f'logs/{{index}}/{{path.name}}', recursive=False)
PY
""".format(log_dirs=log_dirs, scan_days=scan_days)
    ssh_cmd = [
        "ssh", "-p", str(port),
        "-o", "BatchMode=no" if password else "BatchMode=yes",
        "-o", "ConnectTimeout=60",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "LogLevel=ERROR",
        f"{user}@{host}", "sh", "-s",
    ]
    cmd = ["sshpass", "-p", password, *ssh_cmd] if password else ssh_cmd
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as output:
        completed = subprocess.run(
            cmd,
            input=archive_script,
            text=True,
            stdout=output,
            stderr=subprocess.PIPE,
            timeout=int(env.get("SAP_API_MONITOR_ARCHIVE_TIMEOUT_SECONDS", "900")),
            check=False,
        )
    if completed.returncode != 0:
        destination.unlink(missing_ok=True)
        raise RuntimeError((completed.stderr or "Falha ao baixar o arquivo compactado dos logs SAP.").strip()[:2000])
    if not destination.exists() or destination.stat().st_size < 32:
        raise RuntimeError("Arquivo compactado dos logs SAP veio vazio.")
    return destination


def extract_log_archive(archive_path: Path, destination: Path) -> list[str]:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        members = [member for member in archive.getmembers() if member.isfile()]
        root = destination.resolve()
        for member in members:
            target = (destination / member.name).resolve()
            if root not in target.parents and target != root:
                raise RuntimeError("Arquivo remoto invalido no pacote de logs.")
        archive.extractall(destination, members=members)
    return [str(destination)]


def run_local_collect(
    env: dict[str, str],
    window_minutes: int,
    transaction_id: str = "",
    details_limit: int = DEFAULT_DETAILS_LIMIT,
    start_at: str = "",
    end_at: str = "",
    log_dirs: list[str] | None = None,
) -> dict[str, Any]:
    log_dirs = log_dirs or split_log_dirs(env.get("SAP_API_LOG_DIRS") or env.get("SAP_API_LOG_DIR") or "/var/log/pleno")
    ignore_patterns = load_ignore_patterns(env)
    completed = subprocess.run(
        ["python3", "-c", collect_script(window_minutes, log_dirs, ignore_patterns, transaction_id, details_limit, start_at, end_at)],
        text=True,
        capture_output=True,
        timeout=int(env.get("SAP_API_MONITOR_TIMEOUT_SECONDS", "180")),
        check=False,
    )
    if completed.returncode != 0:
        details = (completed.stderr or completed.stdout or "Falha ao coletar logs SAP localmente.").strip()
        raise RuntimeError(details[:2000])
    return json.loads(completed.stdout)


def collect_snapshot(
    env: dict[str, str],
    window_minutes: int,
    transaction_id: str = "",
    details_limit: int = DEFAULT_DETAILS_LIMIT,
    start_at: str = "",
    end_at: str = "",
    local_log_dirs: list[str] | None = None,
) -> dict[str, Any]:
    if local_log_dirs is not None:
        snapshot = run_local_collect(env, window_minutes, transaction_id, details_limit, start_at, end_at, local_log_dirs)
    else:
        collector = run_local_collect if env.get("SAP_API_LOG_DIR") else run_remote_collect
        snapshot = collector(env, window_minutes, transaction_id, details_limit, start_at, end_at)
    enrich_with_checkin_source_calls(snapshot, env, details_limit)
    return snapshot


def normalize_search_text(value: Any) -> str:
    text = str(value or "").lower()
    return " ".join(text.replace("ç", "c").replace("ã", "a").replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u").split())


def manual_reason_phrases(value: str) -> list[str]:
    phrases: list[str] = []
    for raw_line in str(value or "").splitlines():
        candidate = raw_line.split("\t", 1)[0].strip()
        candidate = candidate.split(";", 1)[0].strip()
        candidate = candidate.removeprefix("Motivo 1:").removeprefix("Motivo 2:").strip()
        candidate = normalize_search_text(candidate)
        if candidate:
            phrases.append(candidate)
    if not phrases and value:
        phrases.append(normalize_search_text(value))
    return phrases


def detail_matches_store(detail: dict[str, Any], store: str) -> bool:
    if not store:
        return True
    wanted = str(int(store)) if str(store).isdigit() else str(store).strip()
    for field in ["store", "center"]:
        value = str(detail.get(field) or "").strip()
        if value and value.lstrip("0") == wanted.lstrip("0"):
            return True
    raw = " ".join([
        str(detail.get("raw") or ""),
        json.dumps(detail.get("payload"), ensure_ascii=False) if detail.get("payload") is not None else "",
        json.dumps(detail.get("responsePayload"), ensure_ascii=False) if detail.get("responsePayload") is not None else "",
    ])
    return bool(re.search(rf"(?<!\d)0*{re.escape(wanted)}(?!\d)", raw))


def detail_matches_reason(detail: dict[str, Any], phrases: list[str]) -> bool:
    if not phrases:
        return True
    haystack = normalize_search_text(" ".join([
        str(detail.get("reason") or ""),
        str(detail.get("raw") or ""),
        json.dumps(detail.get("payload"), ensure_ascii=False) if detail.get("payload") is not None else "",
        json.dumps(detail.get("responsePayload"), ensure_ascii=False) if detail.get("responsePayload") is not None else "",
    ]))
    for phrase in phrases:
        words = [word for word in phrase.split() if len(word) >= 3 and word not in {"motivo", "devolucao"}]
        if words and all(word in haystack for word in words):
            return True
        if phrase and phrase in haystack:
            return True
    return False


def manual_error_search(snapshot: dict[str, Any], store: str, reason_text: str, limit: int = 100) -> list[dict[str, Any]]:
    phrases = manual_reason_phrases(reason_text)
    results: list[dict[str, Any]] = []
    for transaction in snapshot.get("transactions") or []:
        details = [
            *(transaction.get("errorDetails") or []),
            *(transaction.get("otherDetails") or []),
        ]
        for detail in details:
            if not detail_matches_store(detail, store) or not detail_matches_reason(detail, phrases):
                continue
            results.append({
                "transactionId": transaction.get("id"),
                "transaction": transaction.get("label"),
                "file": transaction.get("file"),
                **detail,
            })
    results.sort(key=lambda item: item.get("at") or "", reverse=True)
    return results[:limit]


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone()


def source_call_from_checkin_row(row: dict[str, str], source_file: Path) -> dict[str, Any] | None:
    chave = (row.get("chave") or "").strip()
    if not chave:
        return None
    return {
        "source": "pleno-checkin-nf",
        "file": str(source_file),
        "transactionId": "ID.144.PORTARIA.4.TAX",
        "chave": chave,
        "status": (row.get("status") or "").strip(),
        "mensagem": (row.get("mensagem") or "").strip(),
        "startedAt": (row.get("startedAt") or "").strip(),
        "finishedAt": (row.get("finishedAt") or "").strip(),
        "payload": {
            "id": chave,
            "cnpj": "",
            "nf": "",
            "serie": "",
        },
    }


def load_checkin_source_calls(env: dict[str, str], window_start: datetime, window_end: datetime, limit: int) -> list[dict[str, Any]]:
    report_dir = Path(env.get("SAP_API_CHECKIN_REPORT_DIR") or DEFAULT_CHECKIN_REPORT_DIR)
    if not report_dir.exists():
        return []
    tolerance_minutes = int(env.get("SAP_API_SOURCE_CALL_TOLERANCE_MINUTES") or "15")
    start = window_start - timedelta(minutes=tolerance_minutes)
    end = window_end + timedelta(minutes=tolerance_minutes)
    calls: list[dict[str, Any]] = []
    seen: set[str] = set()
    files = sorted(report_dir.glob("relatorio-checkin-*.csv")) + sorted(report_dir.glob("chaves-erro-checkin-*.csv"))
    for path in files:
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle, delimiter=";"):
                    started = parse_datetime(row.get("startedAt"))
                    finished = parse_datetime(row.get("finishedAt")) or started
                    probe = finished or started
                    if not probe or not (start <= probe <= end):
                        continue
                    call = source_call_from_checkin_row(row, path)
                    if not call:
                        continue
                    key = f"{call['chave']}|{call.get('startedAt')}|{call.get('finishedAt')}"
                    if key in seen:
                        continue
                    seen.add(key)
                    calls.append(call)
                    if len(calls) >= limit:
                        return calls
        except OSError:
            continue
    return calls


def enrich_with_checkin_source_calls(snapshot: dict[str, Any], env: dict[str, str], details_limit: int) -> None:
    window_start = parse_datetime(snapshot.get("windowStart"))
    window_end = parse_datetime(snapshot.get("windowEnd"))
    if not window_start or not window_end:
        return
    calls = load_checkin_source_calls(env, window_start, window_end, details_limit)
    if not calls:
        return
    for tx in snapshot.get("transactions", []):
        if tx.get("id") != "ID.144.PORTARIA.4.TAX":
            continue
        tx["sourceCalls"] = calls
        existing_refs = tx.get("referenceDetails") if isinstance(tx.get("referenceDetails"), list) else []
        known = {f"{item.get('note') or ''}|{item.get('accessKey') or ''}" for item in existing_refs if isinstance(item, dict)}
        for call in calls:
            ref_key = f"|{call['chave']}"
            if ref_key in known:
                continue
            existing_refs.append({
                "at": call.get("finishedAt") or call.get("startedAt"),
                "status": "source_call",
                "reason": call.get("mensagem") or "Chamada original relacionada",
                "note": None,
                "accessKey": call["chave"],
                "payload": call["payload"],
                "raw": f"{call['source']} {call['status']} {call['mensagem']}".strip(),
            })
            known.add(ref_key)
        tx["referenceDetails"] = existing_refs[:details_limit]


def load_status(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"collector": "sap-api-monitor", "history": []}


def with_previous_delta(snapshot: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    if not previous:
        return snapshot
    prev_by_id = {item.get("id"): item for item in previous.get("transactions", [])}
    for item in snapshot.get("transactions", []):
        prev = prev_by_id.get(item.get("id")) or {}
        item["changeFromPrevious"] = {
            "events": item.get("events", 0) - prev.get("events", 0),
            "success": item.get("success", 0) - prev.get("success", 0),
            "errors": item.get("errors", 0) - prev.get("errors", 0),
            "ignored": item.get("ignored", 0) - prev.get("ignored", 0),
            "errorRate": round(item.get("errorRate", 0) - prev.get("errorRate", 0), 2),
            "avgResponseGapSeconds": (
                round(item["avgResponseGapSeconds"] - prev["avgResponseGapSeconds"], 3)
                if item.get("avgResponseGapSeconds") is not None and prev.get("avgResponseGapSeconds") is not None
                else None
            ),
        }
    return snapshot


def write_status(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def safe_detail_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "._-" else "_" for char in value)
    return cleaned[:120] or "transacao"


def bucket_start(dt: datetime, grain: str) -> datetime:
    local = dt.astimezone()
    if grain == "month":
        return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if grain == "week":
        first = local - timedelta(days=local.weekday())
        return first.replace(hour=0, minute=0, second=0, microsecond=0)
    if grain == "day":
        return local.replace(hour=0, minute=0, second=0, microsecond=0)
    return local.replace(minute=0, second=0, microsecond=0)


def bucket_end(start: datetime, grain: str) -> datetime:
    if grain == "month":
        if start.month == 12:
            return start.replace(year=start.year + 1, month=1)
        return start.replace(month=start.month + 1)
    if grain == "week":
        return start + timedelta(days=7)
    if grain == "day":
        return start + timedelta(days=1)
    return start + timedelta(hours=1)


def aggregate_history(history: list[dict[str, Any]], limit: int) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, dict[str, dict[str, Any]]] = {grain: {} for grain in ["hour", "day", "week", "month"]}
    for snapshot in history:
        collected_at = parse_datetime(snapshot.get("collectedAt"))
        if not collected_at:
            continue
        for grain in buckets:
            start = bucket_start(collected_at, grain)
            key = start.isoformat(timespec="seconds")
            bucket = buckets[grain].setdefault(key, {
                "grain": grain,
                "bucketStart": key,
                "bucketEnd": bucket_end(start, grain).isoformat(timespec="seconds"),
                "samples": 0,
                "events": 0,
                "success": 0,
                "errors": 0,
                "ignored": 0,
                "other": 0,
                "transactions": {},
                "reasons": {},
                "errorReasons": {},
                "unclassifiedReasons": {},
                "ignoredReasons": {},
            })
            bucket["samples"] += 1
            totals = snapshot.get("totals") or {}
            for field in ["events", "success", "errors", "ignored", "other"]:
                bucket[field] += int(totals.get(field) or 0)
            for tx in snapshot.get("transactions") or []:
                tx_id = str(tx.get("id") or "")
                if not tx_id:
                    continue
                tx_bucket = bucket["transactions"].setdefault(tx_id, {
                    "id": tx_id,
                    "label": tx.get("label") or tx_id,
                    "events": 0,
                    "success": 0,
                    "errors": 0,
                    "ignored": 0,
                    "other": 0,
                    "reasons": {},
                    "errorReasons": {},
                    "unclassifiedReasons": {},
                    "ignoredReasons": {},
                })
                for field in ["events", "success", "errors", "ignored", "other"]:
                    tx_bucket[field] += int(tx.get(field) or 0)
                for item in tx.get("topReasons") or []:
                    reason_key = str(item.get("reason") or "Sem motivo")
                    count = int(item.get("count") or 0)
                    tx_bucket["reasons"][reason_key] = tx_bucket["reasons"].get(reason_key, 0) + count
                    bucket["reasons"][reason_key] = bucket["reasons"].get(reason_key, 0) + count
                for item in tx.get("errorReasons") or []:
                    reason_key = str(item.get("reason") or "Erro sem motivo")
                    count = int(item.get("count") or 0)
                    tx_bucket["errorReasons"][reason_key] = tx_bucket["errorReasons"].get(reason_key, 0) + count
                    bucket["errorReasons"][reason_key] = bucket["errorReasons"].get(reason_key, 0) + count
                for item in tx.get("unclassifiedReasons") or []:
                    reason_key = str(item.get("reason") or "Pleno - retorno sem motivo classificavel")
                    count = int(item.get("count") or 0)
                    tx_bucket["unclassifiedReasons"][reason_key] = tx_bucket["unclassifiedReasons"].get(reason_key, 0) + count
                    bucket["unclassifiedReasons"][reason_key] = bucket["unclassifiedReasons"].get(reason_key, 0) + count
                for item in tx.get("ignoredReasons") or []:
                    reason_key = str(item.get("reason") or "Ignorado")
                    count = int(item.get("count") or 0)
                    tx_bucket["ignoredReasons"][reason_key] = tx_bucket["ignoredReasons"].get(reason_key, 0) + count
                    bucket["ignoredReasons"][reason_key] = bucket["ignoredReasons"].get(reason_key, 0) + count

    def compact_reason_map(reason_map: dict[str, int], item_limit: int = 200) -> list[dict[str, Any]]:
        return [
            {"reason": reason, "count": count}
            for reason, count in sorted(reason_map.items(), key=lambda item: item[1], reverse=True)[:item_limit]
        ]

    result: dict[str, list[dict[str, Any]]] = {}
    for grain, grain_buckets in buckets.items():
        rows = []
        for bucket in sorted(grain_buckets.values(), key=lambda item: item["bucketStart"]):
            transactions = []
            for tx in bucket["transactions"].values():
                tx["reasons"] = compact_reason_map(tx["reasons"])
                tx["errorReasons"] = compact_reason_map(tx["errorReasons"])
                tx["unclassifiedReasons"] = compact_reason_map(tx["unclassifiedReasons"])
                tx["ignoredReasons"] = compact_reason_map(tx["ignoredReasons"], 80)
                transactions.append(tx)
            transactions.sort(key=lambda item: (item.get("errors", 0), item.get("ignored", 0), item.get("events", 0)), reverse=True)
            bucket["transactions"] = transactions[:80]
            bucket["reasons"] = compact_reason_map(bucket["reasons"])
            bucket["errorReasons"] = compact_reason_map(bucket["errorReasons"])
            bucket["unclassifiedReasons"] = compact_reason_map(bucket["unclassifiedReasons"])
            bucket["ignoredReasons"] = compact_reason_map(bucket["ignoredReasons"], 80)
            rows.append(bucket)
        result[grain] = rows[-limit:]
    return result


def load_triage_routing_rules(path: Path = DEFAULT_TRIAGE_ROUTING_FILE) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [item for item in data.get("rules") or [] if isinstance(item, dict) and item.get("enabled", True)]
    except (OSError, json.JSONDecodeError):
        return []


def triage_owner(reason_text: str, detail: dict[str, Any], routing_rules: list[dict[str, Any]] | None = None) -> tuple[str, str, str]:
    """Define o primeiro responsavel; ocorrencias sem regra continuam visiveis."""
    reason_value = str(reason_text or "").lower()
    context = "\n".join(str(detail.get(key) or "") for key in [
        "reason", "sapCode", "sapMessage", "returnReason", "transaction", "transactionId", "raw",
    ]).lower()
    # A regra cadastrada mais recentemente deve prevalecer sobre uma regra
    # anterior mais generica que tambem corresponda ao retorno.
    for rule in reversed(routing_rules or []):
        pattern = str(rule.get("pattern") or "").strip().lower()
        if pattern and pattern in context:
            return (
                str(rule.get("department") or "Triagem TI / Integracoes"),
                "Regra cadastrada",
                str(rule.get("recommendedAction") or "Encaminhar para a area responsavel"),
            )
    if detail.get("storeError"):
        return "Operacao da loja", "Loja", "Validar material e devolucao na filial"
    if any(term in reason_value for term in [
        "centro de custo", "material nao atualizado", "lista tecnica",
        "dados de centro do material", "determina", "cfop",
    ]):
        return "Cadastro SAP", "Produto / centro / contabilizacao", "Corrigir cadastro de produto, centro ou regra SAP"
    if any(term in reason_value for term in [
        "nf-e inexistente", "vl32n", "nf-e recusada", "nf-e rejeitada",
        "nf sem retorno", "br_nfedocumentstatus",
    ]):
        return "SAP Logistica / Fiscal", "Documento fiscal", "Analisar documento fiscal e processamento no SAP"
    if any(term in reason_value for term in ["pleno -", "sap http", "chamada sem retorno"]):
        return "TI Pleno / Integracoes", "Aplicacao / integracao", "Analisar chamada do Pleno e retorno tecnico"
    if str(detail.get("sapCode") or "").strip():
        return "SAP Funcional", "Retorno SAP", "Analisar codigo e mensagem retornados pelo SAP"
    return "Triagem TI / Integracoes", "Sem regra definida", "Classificar responsavel a partir do retorno registrado"


def error_triage(existing: dict[str, Any], snapshot: dict[str, Any], routing_rules: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Acumula ocorrencias reais com as referencias para encaminhamento."""
    known = {
        str(item.get("id") or ""): item
        for item in (existing.get("occurrences") or [])
        if isinstance(item, dict) and item.get("id")
    }
    collected_at = str(snapshot.get("collectedAt") or datetime.now().astimezone().isoformat(timespec="seconds"))
    for tx in snapshot.get("transactions") or []:
        for detail in [*(tx.get("errorDetails") or []), *(tx.get("otherDetails") or [])]:
            if re.search(r"tentativa sap em andamento\s*\(\d+\s*/\s*5\)", str(detail.get("reason") or ""), flags=re.IGNORECASE):
                continue
            status = str(detail.get("status") or "error")
            if status not in ["error", "other"]:
                continue
            reason_text = str(detail.get("reason") or "Pleno - retorno sem motivo classificavel")
            owner, area, action = triage_owner(reason_text, detail, routing_rules)
            identity = "|".join([
                str(tx.get("id") or ""), str(detail.get("at") or ""), reason_text,
                str(detail.get("note") or ""), str(detail.get("accessKey") or ""),
                str(detail.get("store") or ""), str(detail.get("material") or ""),
            ])
            occurrence_id = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:20]
            old = known.get(occurrence_id)
            record = {
                "id": occurrence_id,
                "firstSeenAt": old.get("firstSeenAt") if old else collected_at,
                "lastSeenAt": collected_at,
                "occurrenceAt": detail.get("at") or collected_at,
                "occurrenceCount": int(old.get("occurrenceCount") or 0) + 1 if old else 1,
                "status": old.get("status") if old else "Novo",
                "department": owner,
                "area": area,
                "recommendedAction": action,
                "transactionId": tx.get("id") or "",
                "transaction": tx.get("label") or tx.get("id") or "",
                "reason": reason_text,
                "eventStatus": status,
                "store": detail.get("store") or "",
                "center": detail.get("center") or "",
                "note": detail.get("note") or "",
                "accessKey": detail.get("accessKey") or "",
                "material": detail.get("material") or "",
                "sapCode": detail.get("sapCode") or "",
                "sapMessage": detail.get("sapMessage") or "",
                "returnReason": detail.get("returnReason") or "",
                "requestEndpoint": detail.get("requestEndpoint") or "",
                "requestUrl": detail.get("requestUrl") or "",
                "payload": detail.get("payload"),
                "responsePayload": detail.get("responsePayload"),
                "raw": str(detail.get("raw") or "")[:1800],
            }
            known[occurrence_id] = record

    for record in known.values():
        owner, area, action = triage_owner(str(record.get("reason") or ""), record, routing_rules)
        record["department"] = owner
        record["area"] = area
        record["recommendedAction"] = action
    occurrences = sorted(known.values(), key=lambda item: str(item.get("occurrenceAt") or ""), reverse=True)
    max_items = 20000
    occurrences = occurrences[:max_items]
    department_counts = collections.Counter(item.get("department") or "Triagem TI / Integracoes" for item in occurrences)
    reason_counts = collections.Counter((item.get("department") or "Triagem TI / Integracoes", item.get("reason") or "Sem motivo") for item in occurrences)
    return {
        "updatedAt": collected_at,
        "retentionLimit": max_items,
        "occurrences": occurrences,
        "departments": [
            {"department": department, "occurrences": count}
            for department, count in department_counts.most_common()
        ],
        "reasons": [
            {"department": department, "reason": reason_text, "occurrences": count}
            for (department, reason_text), count in reason_counts.most_common(200)
        ],
    }


def rebuild_history_from_logs(
    env: dict[str, str],
    status_file: Path,
    days: int,
    history_limit: int,
    aggregate_history_limit: int,
) -> None:
    days = max(1, min(int(days), 31))
    now = datetime.now().astimezone().replace(second=0, microsecond=0)
    rebuild_start = now - timedelta(days=days)
    recent_start = now - timedelta(hours=24)
    original = load_status(status_file)
    original_history = original.get("history") or []
    progress_file = status_file.with_name(f"{status_file.stem}.reprocessando.json")
    progress = load_status(progress_file) if progress_file.exists() else {}
    plan: list[tuple[datetime, datetime]] = []
    rebuilt_by_window: dict[tuple[str, str], dict[str, Any]] = {}

    # Um reprocessamento pode levar alguns minutos. Mantemos cada janela concluida
    # em arquivo separado para poder retomar apos queda de VPN sem publicar parcial.
    if (
        progress.get("collector") == "sap-api-history-rebuild"
        and int(progress.get("days") or 0) == days
        and isinstance(progress.get("plan"), list)
    ):
        for item in progress["plan"]:
            if not isinstance(item, dict):
                continue
            start = parse_datetime(item.get("start"))
            end = parse_datetime(item.get("end"))
            if start and end and end > start:
                plan.append((start, end))
        for snapshot in progress.get("rebuilt") or []:
            if not isinstance(snapshot, dict):
                continue
            start = str(snapshot.get("windowStart") or "")
            end = str(snapshot.get("windowEnd") or "")
            if start and end:
                rebuilt_by_window[(start, end)] = snapshot
        if plan:
            print(
                f"Retomando reprocessamento: {len(rebuilt_by_window)}/{len(plan)} janela(s) ja concluidas.",
                flush=True,
            )

    if not plan:
        # Mantem a resolucao de 10 minutos do ultimo dia quando ja houver pontos salvos.
        recent_points = [
            snapshot for snapshot in original_history
            if (parse_datetime(snapshot.get("windowStart")) or parse_datetime(snapshot.get("collectedAt")))
            and (parse_datetime(snapshot.get("windowEnd")) or parse_datetime(snapshot.get("collectedAt")))
            and (parse_datetime(snapshot.get("windowEnd")) or parse_datetime(snapshot.get("collectedAt"))) >= recent_start
        ]
        cursor = rebuild_start.replace(minute=0, second=0, microsecond=0)
        hourly_end = recent_start.replace(minute=0, second=0, microsecond=0)
        while cursor < hourly_end:
            plan.append((cursor, min(cursor + timedelta(hours=1), hourly_end)))
            cursor += timedelta(hours=1)
        if recent_points:
            for snapshot in sorted(recent_points, key=lambda item: str(item.get("windowStart") or item.get("collectedAt") or "")):
                start = parse_datetime(snapshot.get("windowStart")) or parse_datetime(snapshot.get("collectedAt"))
                end = parse_datetime(snapshot.get("windowEnd")) or start
                if not start or not end or end <= start:
                    continue
                plan.append((max(start, recent_start), min(end, now)))
        else:
            cursor = hourly_end
            while cursor < now:
                plan.append((cursor, min(cursor + timedelta(hours=1), now)))
                cursor += timedelta(hours=1)

    deduped_plan: list[tuple[datetime, datetime]] = []
    seen_windows: set[tuple[str, str]] = set()
    for start, end in plan:
        if end <= start:
            continue
        key = (start.isoformat(), end.isoformat())
        if key not in seen_windows:
            seen_windows.add(key)
            deduped_plan.append((start, end))
    if not deduped_plan:
        raise RuntimeError("Nao ha janelas historicas para reconstruir.")

    # Para historico, trazemos os logs uma unica vez, compactados, e fazemos as
    # centenas de janelas localmente. A coleta normal de 10 min segue remota e leve.
    archive_workspace = None
    local_log_dirs = None
    if not env.get("SAP_API_LOG_DIR"):
        archive_workspace = tempfile.TemporaryDirectory(prefix="sap-api-history-")
        archive_path = Path(archive_workspace.name) / "pleno-logs.tar.gz"
        print("Baixando logs compactados do Pleno para reprocessar localmente...", flush=True)
        try:
            fetch_remote_log_archive(env, deduped_plan[0][0], deduped_plan[-1][1], archive_path)
            local_log_dirs = extract_log_archive(archive_path, Path(archive_workspace.name) / "logs")
            archive_path.unlink(missing_ok=True)
        except Exception:
            archive_workspace.cleanup()
            raise

    if not progress_file.exists():
        write_status(progress_file, {
            "collector": "sap-api-history-rebuild",
            "days": days,
            "startedAt": now.isoformat(timespec="seconds"),
            "plan": [
                {"start": start.isoformat(), "end": end.isoformat()}
                for start, end in deduped_plan
            ],
            "rebuilt": [],
        })

    def save_progress() -> None:
        write_status(progress_file, {
            "collector": "sap-api-history-rebuild",
            "days": days,
            "startedAt": progress.get("startedAt") or now.isoformat(timespec="seconds"),
            "updatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "plan": [
                {"start": item_start.isoformat(), "end": item_end.isoformat()}
                for item_start, item_end in deduped_plan
            ],
            "rebuilt": [
                rebuilt_by_window[(item_start.isoformat(), item_end.isoformat())]
                for item_start, item_end in deduped_plan
                if (item_start.isoformat(), item_end.isoformat()) in rebuilt_by_window
            ],
        })

    pending = [
        (index, start, end)
        for index, (start, end) in enumerate(deduped_plan, start=1)
        if (start.isoformat(), end.isoformat()) not in rebuilt_by_window
    ]
    total = len(deduped_plan)
    workers = max(1, min(int(env.get("SAP_API_MONITOR_REBUILD_WORKERS", "4")), 8, len(pending) or 1))

    def rebuild_window(index: int, start: datetime, end: datetime) -> tuple[int, datetime, datetime, dict[str, Any]]:
        minutes = max(1, int((end - start).total_seconds() // 60))
        snapshot = collect_snapshot(
            env,
            minutes,
            details_limit=0,
            start_at=start.isoformat(),
            end_at=end.isoformat(),
            local_log_dirs=local_log_dirs,
        )
        snapshot["collectedAt"] = end.isoformat(timespec="seconds")
        return index, start, end, snapshot

    if pending:
        print(f"Reconstruindo {len(pending)} janela(s) com {workers} tarefa(s) locais em paralelo.", flush=True)
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="sap-history") as executor:
            futures = {
                executor.submit(rebuild_window, index, start, end): (index, start, end)
                for index, start, end in pending
            }
            completed = len(rebuilt_by_window)
            for future in as_completed(futures):
                index, start, end = futures[future]
                try:
                    _, result_start, result_end, snapshot = future.result()
                except Exception as exc:
                    for pending_future in futures:
                        pending_future.cancel()
                    raise RuntimeError(
                        f"Falha ao reconstruir {index}/{total} ({start.strftime('%d/%m %H:%M')} ate {end.strftime('%d/%m %H:%M')}): {exc}"
                    ) from exc
                rebuilt_by_window[(result_start.isoformat(), result_end.isoformat())] = snapshot
                completed += 1
                print(
                    f"Reconstruido {completed}/{total}: {result_start.strftime('%d/%m %H:%M')} ate {result_end.strftime('%d/%m %H:%M')}",
                    flush=True,
                )
                save_progress()

    rebuilt = [
        rebuilt_by_window[(start.isoformat(), end.isoformat())]
        for start, end in deduped_plan
        if (start.isoformat(), end.isoformat()) in rebuilt_by_window
    ]

    # Rele no final para preservar uma coleta automatica que tenha ocorrido durante o processo.
    current = load_status(status_file)
    retained = []
    for snapshot in current.get("history") or []:
        point = parse_datetime(snapshot.get("windowEnd")) or parse_datetime(snapshot.get("collectedAt"))
        if not point or point < rebuild_start or point > now:
            retained.append(snapshot)
    history = sorted([*retained, *rebuilt], key=lambda item: str(item.get("collectedAt") or ""))
    history = history[-max(history_limit, len(history)):]
    backup = status_file.with_name(f"{status_file.stem}.antes-reprocessamento-{datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')}.json")
    write_status(backup, current)
    current["collector"] = "sap-api-monitor"
    current["updatedAt"] = datetime.now().astimezone().isoformat(timespec="seconds")
    current["historyLimit"] = max(history_limit, len(history))
    current["aggregateHistoryLimit"] = aggregate_history_limit
    current["history"] = history
    current["aggregates"] = aggregate_history(history, aggregate_history_limit)
    write_status(status_file, current)
    progress_file.unlink(missing_ok=True)
    if archive_workspace:
        archive_workspace.cleanup()
    print(f"Historico reprocessado: {len(rebuilt)} janela(s), {days} dia(s). Backup: {backup}", flush=True)


def snapshot_window_end(snapshot: dict[str, Any]) -> datetime | None:
    return parse_datetime(snapshot.get("windowEnd")) or parse_datetime(snapshot.get("collectedAt"))


def recover_missing_history(
    env: dict[str, str],
    history: list[dict[str, Any]],
    latest_snapshot: dict[str, Any],
    window_minutes: int,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Recupera lacunas usando um unico arquivo compactado de logs do Pleno."""
    latest_start = parse_datetime(latest_snapshot.get("windowStart"))
    previous_end = max((snapshot_window_end(item) for item in history if snapshot_window_end(item)), default=None)
    if not latest_start or not previous_end or latest_start <= previous_end + timedelta(seconds=5):
        return [], None

    max_minutes = max(10, min(int(env.get("SAP_API_MONITOR_RECOVERY_MAX_MINUTES", "1440")), 7 * 24 * 60))
    recovery_start = max(previous_end, latest_start - timedelta(minutes=max_minutes))
    if latest_start <= recovery_start + timedelta(seconds=5):
        return [], None

    plan: list[tuple[datetime, datetime]] = []
    cursor = recovery_start
    while cursor < latest_start:
        next_cursor = min(cursor + timedelta(minutes=window_minutes), latest_start)
        if next_cursor > cursor:
            plan.append((cursor, next_cursor))
        cursor = next_cursor
    if not plan:
        return [], None

    archive_workspace = tempfile.TemporaryDirectory(prefix="sap-api-recovery-")
    try:
        archive_path = Path(archive_workspace.name) / "pleno-logs.tar.gz"
        print(
            f"Recuperando lacuna de {recovery_start.strftime('%d/%m %H:%M')} ate {latest_start.strftime('%d/%m %H:%M')}: baixando logs compactados uma unica vez...",
            flush=True,
        )
        fetch_remote_log_archive(env, recovery_start, latest_start, archive_path)
        local_log_dirs = extract_log_archive(archive_path, Path(archive_workspace.name) / "logs")
        archive_path.unlink(missing_ok=True)
        workers = max(1, min(int(env.get("SAP_API_MONITOR_RECOVERY_WORKERS", "4")), 8, len(plan)))

        def recover_window(start: datetime, end: datetime) -> dict[str, Any]:
            snapshot = collect_snapshot(
                env,
                max(1, int((end - start).total_seconds() // 60)),
                details_limit=0,
                start_at=start.isoformat(),
                end_at=end.isoformat(),
                local_log_dirs=local_log_dirs,
            )
            snapshot["collectedAt"] = end.isoformat(timespec="seconds")
            return snapshot

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="sap-recovery") as executor:
            recovered = list(executor.map(lambda item: recover_window(*item), plan))
        metadata = {
            "recoveredAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "start": recovery_start.isoformat(timespec="seconds"),
            "end": latest_start.isoformat(timespec="seconds"),
            "windows": len(recovered),
            "maxMinutes": max_minutes,
        }
        print(f"Lacuna recuperada: {len(recovered)} janela(s) localmente.", flush=True)
        return recovered, metadata
    except Exception as exc:
        print(f"Aviso: nao foi possivel recuperar a lacuna automaticamente: {exc}", flush=True)
        return [], {
            "failedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
            "error": str(exc)[:500],
            "maxMinutes": max_minutes,
        }
    finally:
        archive_workspace.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--detail-transaction", default="")
    parser.add_argument("--window-minutes", type=int, default=None)
    parser.add_argument("--details-limit", type=int, default=DEFAULT_DETAILS_LIMIT)
    parser.add_argument("--detail-dir", default="")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--manual-store", default="")
    parser.add_argument("--manual-reason", default="")
    parser.add_argument("--manual-at", default="")
    parser.add_argument("--manual-window-minutes", type=int, default=120)
    parser.add_argument("--rebuild-history-days", type=int, default=0)
    args = parser.parse_args()

    env = load_env()
    status_file = Path(env.get("SAP_API_MONITOR_STATUS_FILE") or DEFAULT_STATUS)
    window_minutes = int(args.window_minutes or env.get("SAP_API_MONITOR_WINDOW_MINUTES") or DEFAULT_WINDOW_MINUTES)
    history_limit = int(env.get("SAP_API_MONITOR_HISTORY_LIMIT") or DEFAULT_HISTORY_LIMIT)
    aggregate_history_limit = int(env.get("SAP_API_MONITOR_AGGREGATE_HISTORY_LIMIT") or DEFAULT_AGGREGATE_HISTORY_LIMIT)
    details_limit = int(env.get("SAP_API_MONITOR_DETAILS_LIMIT") or DEFAULT_DETAILS_LIMIT)

    if args.rebuild_history_days:
        rebuild_history_from_logs(
            env,
            status_file,
            args.rebuild_history_days,
            history_limit,
            aggregate_history_limit,
        )
        return

    if args.manual_store or args.manual_reason:
        manual_window = max(10, min(int(args.manual_window_minutes or 120), 24 * 60))
        center = parse_datetime(args.manual_at) if args.manual_at else None
        if center:
            start_at = (center - timedelta(minutes=manual_window // 2)).isoformat()
            end_at = (center + timedelta(minutes=manual_window // 2)).isoformat()
        else:
            end_at = datetime.now().astimezone().isoformat()
            start_at = (datetime.now().astimezone() - timedelta(hours=24)).isoformat()
        snapshot = collect_snapshot(env, manual_window, details_limit=2000, start_at=start_at, end_at=end_at)
        results = manual_error_search(snapshot, args.manual_store, args.manual_reason)
        detail_dir = Path(args.detail_dir or env.get("SAP_API_DETAIL_DIR") or DEFAULT_DETAIL_DIR)
        detail_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        detail_file = detail_dir / f"{stamp}-busca-loja-{safe_detail_name(args.manual_store or 'todas')}-{manual_window}min.json"
        payload = {
            "collector": "sap-api-manual-search",
            "updatedAt": snapshot.get("collectedAt") or datetime.now().astimezone().isoformat(timespec="seconds"),
            "store": args.manual_store,
            "reason": args.manual_reason,
            "approximateAt": args.manual_at,
            "windowMinutes": manual_window,
            "start": start_at,
            "end": end_at,
            "detailFile": str(detail_file),
            "matched": len(results),
            "results": results,
        }
        write_status(detail_file, payload)
        print(json.dumps(payload, ensure_ascii=False))
        return

    if args.detail_transaction:
        snapshot = collect_snapshot(env, window_minutes, args.detail_transaction, args.details_limit, args.start, args.end)
        detail_dir = Path(args.detail_dir or env.get("SAP_API_DETAIL_DIR") or DEFAULT_DETAIL_DIR)
        detail_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        detail_file = detail_dir / f"{stamp}-{safe_detail_name(args.detail_transaction)}-{window_minutes}min.json"
        payload = {
            "collector": "sap-api-detail",
            "updatedAt": snapshot.get("collectedAt") or datetime.now().astimezone().isoformat(timespec="seconds"),
            "transactionId": args.detail_transaction,
            "windowMinutes": window_minutes,
            "start": args.start,
            "end": args.end,
            "detailsLimit": args.details_limit,
            "detailFile": str(detail_file),
            "snapshot": snapshot,
        }
        write_status(detail_file, payload)
        print(json.dumps(payload, ensure_ascii=False))
        return

    current_status = load_status(status_file)
    previous = current_status.get("latest")
    snapshot = with_previous_delta(collect_snapshot(env, window_minutes, details_limit=details_limit), previous)
    history = current_status.get("history") or []
    recovered, recovery = recover_missing_history(env, history, snapshot, window_minutes)
    existing_windows = {
        (str(item.get("windowStart") or ""), str(item.get("windowEnd") or ""))
        for item in history
    }
    for item in recovered:
        key = (str(item.get("windowStart") or ""), str(item.get("windowEnd") or ""))
        if key not in existing_windows:
            history.append(item)
            existing_windows.add(key)
    history.append(snapshot)
    history.sort(key=lambda item: str(item.get("collectedAt") or item.get("windowEnd") or ""))
    history = history[-history_limit:]
    aggregates = aggregate_history(history, aggregate_history_limit)
    triage = error_triage(current_status.get("triage") or {}, snapshot, load_triage_routing_rules())

    status = {
        "collector": "sap-api-monitor",
        "updatedAt": snapshot.get("collectedAt") or datetime.now().astimezone().isoformat(timespec="seconds"),
        "windowMinutes": window_minutes,
        "historyLimit": history_limit,
        "aggregateHistoryLimit": aggregate_history_limit,
        "detailsLimit": details_limit,
        "latest": snapshot,
        "history": history,
        "aggregates": aggregates,
        "triage": triage,
    }
    if recovery:
        status["lastRecovery"] = recovery
    write_status(status_file, status)
    print(f"Monitor SAP API atualizado em {status_file}")


if __name__ == "__main__":
    main()
