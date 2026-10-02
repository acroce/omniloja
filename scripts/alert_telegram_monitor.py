#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
# Also support the host watchdog importing this module by absolute path.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from noc_api_client import request_json, ApiUnavailable, process_observations


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / "outputs" / "pleno_business_monitor" / "telegram_alert_state.json"
DEFAULT_PROMOPRECO_HISTORY = ROOT / "outputs" / "pleno_business_monitor" / "promopreco_history.json"
DEFAULT_POLICY_FILE = ROOT / "outputs" / "pleno_business_monitor" / "noc_alert_policy.json"
DEFAULT_POLICY_TEMPLATE = ROOT / "config" / "noc_alert_policy.json"
DEFAULT_ACKNOWLEDGEMENTS_FILE = ROOT / "outputs" / "pleno_business_monitor" / "noc_alert_acknowledgements.json"

MONITORS = [
    ("Pedidos", "/api/business-monitor/pedidos", "stages"),
    ("Promocao e Precos", "/api/business-monitor/promopreco", "stages"),
    ("Notas Rejeitadas", "/api/business-monitor/notas-rejeitadas", "stages"),
    ("Estoque RELEX", "/api/business-monitor/estoque-relex", "stages"),
    ("Retificacao RET", "/api/business-monitor/retificacao-ret", "stages"),
    ("Devolucao AS400", "/api/business-monitor/devolucao-as400", "stages"),
    ("Mercadoria Filial", "/api/business-monitor/mercadoria-filial", "stages"),
]

DEFAULT_POLICY: dict[str, Any] = {
    "weekdays": [0, 1, 2, 3, 4, 5, 6],
    "monitorStart": "00:00",
    "monitorEnd": "23:59",
    "okCheckIntervalSeconds": 300,
    "failureCheckIntervalSeconds": 60,
    "firstErrorAfterSeconds": 0,
    "repeatEverySeconds": 3600,
    "stopAfterSeconds": 10800,
    "sendFailure": True,
    "sendRecovery": True,
    "recoveryRepeatEverySeconds": 0,
    "recoverySendOnce": True,
    "recoveryOnlyWithinStopWindow": True,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Envia alertas Telegram dos monitores NOC.")
    parser.add_argument("--dry-run", action="store_true", help="Mostra a mensagem sem enviar ao Telegram.")
    parser.add_argument("--force", action="store_true", help="Envia mesmo se o alerta ja tiver sido enviado.")
    parser.add_argument("--only-errors", action="store_true", help="Envia apenas se existir falha no monitor.")
    parser.add_argument(
        "--scope",
        choices=["all", "morning", "night", "pedidos", "promopreco", "notas-rejeitadas", "estoque-relex", "retificacao-ret", "devolucao-as400", "mercadoria-filial", "estoque-retificacao"],
        default="all",
        help="Grupo de monitores a enviar.",
    )
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
    env.update(os.environ)
    return env


def load_alert_policy(env: dict[str, str]) -> dict[str, Any]:
    configured = Path(env.get("NOC_ALERT_POLICY_FILE") or DEFAULT_POLICY_FILE)
    path = configured if configured.is_absolute() else ROOT / configured
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        try:
            data = json.loads(DEFAULT_POLICY_TEMPLATE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
    defaults = {**DEFAULT_POLICY, **(data.get("defaults") or {})}
    return {
        "defaults": defaults,
        "scopes": data.get("scopes") or {},
        "destinations": data.get("destinations") or [{
            "id": "telegram-legacy",
            "type": "telegram",
            "enabled": True,
            "scopes": ["all"],
            "tokenEnv": "TELEGRAM_BOT_TOKEN",
            "chatIdsEnv": "TELEGRAM_CHAT_IDS",
        }],
    }


def load_alert_acknowledgements(env: dict[str, str]) -> dict[str, Any]:
    configured = Path(env.get("NOC_ALERT_ACKNOWLEDGEMENTS_FILE") or DEFAULT_ACKNOWLEDGEMENTS_FILE)
    path = configured if configured.is_absolute() else ROOT / configured
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"scopes": {}}
    return data if isinstance(data, dict) else {"scopes": {}}


def active_silenced_scopes(acknowledgements: dict[str, Any], now: datetime) -> dict[str, datetime]:
    active: dict[str, datetime] = {}
    for scope, value in (acknowledgements.get("scopes") or {}).items():
        if not isinstance(value, dict):
            continue
        muted_until = parse_iso(str(value.get("mutedUntil") or ""))
        if muted_until and muted_until > now:
            active[str(scope)] = muted_until
    return active


def alert_policy_for_scope(policy: dict[str, Any], scope: str) -> dict[str, Any]:
    specific = (policy.get("scopes") or {}).get(scope) or {}
    merged = {**DEFAULT_POLICY, **(policy.get("defaults") or {}), **specific}
    for key in ("okCheckIntervalSeconds", "failureCheckIntervalSeconds", "firstErrorAfterSeconds", "repeatEverySeconds", "stopAfterSeconds", "recoveryRepeatEverySeconds"):
        try:
            merged[key] = max(int(merged.get(key) or 0), 0)
        except (TypeError, ValueError):
            merged[key] = int(DEFAULT_POLICY[key])
    merged["sendFailure"] = bool(merged.get("sendFailure", True))
    merged["sendRecovery"] = bool(merged.get("sendRecovery", True))
    merged["recoverySendOnce"] = bool(merged.get("recoverySendOnce", True))
    merged["recoveryOnlyWithinStopWindow"] = bool(merged.get("recoveryOnlyWithinStopWindow", True))
    weekdays = merged.get("weekdays") or DEFAULT_POLICY["weekdays"]
    merged["weekdays"] = sorted({int(day) for day in weekdays if str(day).isdigit() and 0 <= int(day) <= 6}) or DEFAULT_POLICY["weekdays"]
    return merged


def within_monitor_window(settings: dict[str, Any], moment: datetime) -> bool:
    def minutes(value: object, fallback: int) -> int:
        try:
            hour, minute = str(value).split(":", 1)
            return int(hour) * 60 + int(minute)
        except (TypeError, ValueError):
            return fallback

    if moment.weekday() not in settings.get("weekdays", DEFAULT_POLICY["weekdays"]):
        return False
    start = minutes(settings.get("monitorStart"), 0)
    end = minutes(settings.get("monitorEnd"), 23 * 60 + 59)
    current = moment.hour * 60 + moment.minute
    return start <= current <= end if start <= end else current >= start or current <= end


def load_json_url(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {"scopes": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def scope_state(state: dict[str, Any], scope: str) -> dict[str, Any]:
    scopes = state.setdefault("scopes", {})
    if not isinstance(scopes, dict):
        scopes = {}
        state["scopes"] = scopes
    current = scopes.setdefault(scope, {})
    if not isinstance(current, dict):
        current = {}
        scopes[scope] = current
    return current


def format_dt(value: str) -> str:
    if not value:
        return "-"
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return date.strftime("%d/%m %H:%M")
    except ValueError:
        return value


def stage_failed(stage: dict[str, Any]) -> bool:
    return int(stage.get("severity") or 0) >= 3


def short_batch(batch: str) -> str:
    return str(batch or "").replace("Rodada ", "").strip()


def promo_environment(label: str) -> str:
    text = str(label or "")
    if "Pre Producao" in text:
        return "Pre producao"
    if "Producao" in text:
        return "Producao"
    return text or "Ambiente"


def selected_stage(stages: list[dict[str, Any]]) -> dict[str, Any]:
    return next((stage for stage in stages if "Importado" in str(stage.get("label", ""))), stages[0] if stages else {})


def folder_count_text(stage: dict[str, Any], mode: str = "importedCount") -> str:
    folders = stage.get("folderStats") or []
    parts = [
        f"{folder.get('folder')}: {int(folder.get(mode) or 0)}"
        for folder in folders
        if int(folder.get(mode) or 0) > 0
    ]
    return f" ({'; '.join(parts)})" if parts else ""


def history_event_for(stage_id: str) -> tuple[str, dict[str, Any]] | tuple[str, None]:
    history = load_json_file(DEFAULT_PROMOPRECO_HISTORY)
    days = history.get("days") or {}
    today = datetime.now().strftime("%Y-%m-%d")
    for day_key in sorted((key for key in days if key < today), reverse=True):
        event_data = (days.get(day_key) or {}).get("events", {}).get(stage_id)
        if event_data:
            return day_key, event_data
    return "", None


def variation_text(stage: dict[str, Any]) -> str:
    stage_id = str(stage.get("id") or "")
    if not stage_id:
        return ""
    previous_day, previous = history_event_for(stage_id)
    if not previous:
        return ""
    current = int(stage.get("importedCount") or 0)
    baseline = int(previous.get("importedCount") or 0)
    if baseline <= 0:
        return ""
    variation = abs(current - baseline) / baseline
    if variation <= 0.05:
        return ""
    direction = "acima" if current > baseline else "abaixo"
    percent = variation * 100
    return f" ⚠️ Investigar variacao {percent:.1f}% {direction} de {previous_day} ({baseline})."


def ok_reason(stages: list[dict[str, Any]]) -> str:
    stage = selected_stage(stages)
    imported = int(stage.get("importedCount") or 0)
    store_total = int(stage.get("storeTotal") or 0)
    store_imported = int(stage.get("storeImported") or 0)
    store_text = f", lojas {store_imported}/{store_total}" if store_total else ""
    last_imported = stage.get("lastImportedAt") or ""
    finished = f" terminou {last_imported}" if last_imported else ""
    return f"OK - {imported} processados{store_text}{finished}{folder_count_text(stage)}{variation_text(stage)}"


def warning_reason(stages: list[dict[str, Any]]) -> str:
    stage = next((item for item in stages if str(item.get("status") or "") in {"aguardando", "warning"} and int(item.get("pendingCount") or 0) > 0), selected_stage(stages))
    pending = int(stage.get("pendingCount") or 0)
    imported = int(stage.get("importedCount") or 0)
    store_total = int(stage.get("storeTotal") or 0)
    store_imported = int(stage.get("storeImported") or 0)
    store_pending = int(stage.get("storePending") or 0)
    store_text = f", lojas {store_imported}/{store_total}, faltam {store_pending}" if store_total else ""
    last_imported = stage.get("lastImportedAt") or ""
    progress = f" ultimo imp. {last_imported}" if last_imported else ""
    return f"Atencao: {pending} arquivo(s) sem imp. tratado(s) como excecao, {imported} com imp.{store_text}{progress}"


def failure_reason(stages: list[dict[str, Any]]) -> str:
    failed = [stage for stage in stages if stage_failed(stage)]
    if not failed:
        return ""
    imported_stage = selected_stage(failed)
    status = str(imported_stage.get("status") or "")
    details = str(imported_stage.get("details") or "")
    if status == "sem_acesso" or "ssh:" in details.lower() or "timed out" in details.lower() or "sem acesso" in details.lower():
        return "Sem acesso"
    pending = imported_stage.get("pendingCount")
    imported = imported_stage.get("importedCount")
    folders = imported_stage.get("folderStats") or []
    if folders:
        folder_text = " " + "; ".join(
            f"{folder.get('folder')}: {folder.get('pendingCount', 0)} sem imp., {folder.get('importedCount', 0)} com imp."
            for folder in folders
            if int(folder.get("pendingCount") or 0) > 0 or int(folder.get("importedCount") or 0) > 0
        )
    else:
        folder_text = ""
    stores = imported_stage.get("pendingStores") or []
    if stores:
        visible = [str(item) for item in stores[:12]]
        suffix = f" (+{len(stores) - 12})" if len(stores) > 12 else ""
        store_text = f" Lojas: {', '.join(visible)}{suffix}"
    else:
        store_text = ""
    if pending not in ("", None) and imported not in ("", None) and int(pending or 0) == 0 and int(imported or 0) == 0:
        return "Falha: sem arquivo"
    if pending not in ("", None) and int(pending or 0) > 0:
        store_total = int(imported_stage.get("storeTotal") or 0)
        store_imported = int(imported_stage.get("storeImported") or 0)
        store_pending = int(imported_stage.get("storePending") or 0)
        store_progress = f", lojas {store_imported}/{store_total}, faltam {store_pending}" if store_total else ""
        last_imported = imported_stage.get("lastImportedAt") or ""
        progress = f" ultimo imp. {last_imported}" if last_imported else ""
        return f"Falha: {pending} sem imp., {imported or 0} com imp.{store_progress}{progress}{folder_text}{store_text}"
    if "Sem arquivo em:" in details:
        missing = details.split("Sem arquivo em:", 1)[1].split(".", 1)[0].strip()
        return f"Falha: sem arquivo em {missing}"
    if "Nenhum arquivo" in details:
        return "Falha: sem arquivo"
    return f"Falha: {imported_stage.get('statusLabel') or imported_stage.get('status') or 'verificar'}"


def summarize_pedidos(data: dict[str, Any]) -> list[str]:
    if data.get("noSchedule") or datetime.now().weekday() == 6:
        return ["⏸️ Pedidos - Domingo sem agenda"]
    if datetime.now().strftime("%H:%M") < "07:50":
        return ["⏳ Pedidos - Aguardando inicio 07:50"]
    stages = [
        stage for stage in data.get("stages", [])
        if stage.get("id") != "pedido_concluido"
    ]
    fluxo = next((stage for stage in stages if stage.get("id") == "lojas_diaflex"), {})
    fluxo_details = str(fluxo.get("details") or "")
    fluxo_match = re.search(r"(\d+)\s*/\s*(\d+)\s+loja\(s\)\s+concluida", fluxo_details, re.IGNORECASE)
    fluxo_lines: list[str] = []
    if fluxo_match:
        completed, total = fluxo_match.groups()
        pending_match = re.search(r"Pendentes:\s*(.+?)(?:\.|$)", fluxo_details, re.IGNORECASE)
        pending = pending_match.group(1).strip() if pending_match else "-"
        cancelled_match = re.search(r"Canceladas:\s*(.+?)(?:\.|$)", fluxo_details, re.IGNORECASE)
        cancelled = cancelled_match.group(1).strip() if cancelled_match else ""
        closing = datetime.now().replace(hour=9, minute=30, second=0, microsecond=0)
        remaining_seconds = int((closing - datetime.now()).total_seconds())
        if remaining_seconds > 0:
            hours, remainder = divmod(remaining_seconds, 3600)
            minutes = remainder // 60
            remaining = f"Tempo para fechamento: {hours}h {minutes:02d}min (09:30)"
        else:
            remaining = "Fechamento previsto: 09:30 (prazo encerrado)"
        fluxo_lines = [
            "Pedido Fluxo Tenso",
            f"{total} Lojas - {completed} Executados",
            f"Lojas que ficaram de fora: {pending}",
            remaining,
        ]
        if cancelled:
            fluxo_lines.append(f"Canceladas sem revisao: {cancelled}")
    relex_stages = [stage for stage in stages if stage.get("id") in {"envio_relex", "relex_processados"}]
    relex_closed = len(relex_stages) == 2 and all(
        str(stage.get("status") or "") in {"concluido", "concluido_atrasado"}
        for stage in relex_stages
    )
    if relex_closed:
        sent_at = next((str(stage.get("actualAt") or "") for stage in relex_stages if stage.get("actualAt")), "")
        relex_line = f"✅ Pedido - Processo fechado: RELEX enviado {format_dt(sent_at)}."
        if fluxo_match and int(fluxo_match.group(1)) < int(fluxo_match.group(2)):
            return fluxo_lines + [relex_line, "🟡 Fluxo Diaflex ainda possui lojas pendentes."]
        return fluxo_lines + [relex_line]
    failed = [stage for stage in stages if stage_failed(stage)]
    closing = datetime.now().replace(hour=9, minute=30, second=0, microsecond=0)
    if failed and datetime.now() < closing:
        labels = ", ".join(str(stage.get("label") or "etapa") for stage in failed[:3])
        return fluxo_lines + [
            f"🟡 Pedidos - Alerta: pendencia em {labels}. Acompanhando novas verificacoes ate 09:30."
        ]
    if not failed:
        completed = [
            stage for stage in stages
            if str(stage.get("status") or "") in {"concluido", "concluido_atrasado"}
        ]
        pending = [
            stage for stage in stages
            if str(stage.get("status") or "") in {"aguardando", "sem_coleta"}
        ]
        if pending:
            next_step = min(pending, key=lambda stage: str(stage.get("targetTime") or "99:99"))
            return fluxo_lines + [
                f"🟡 Pedidos - OK parcial: {len(completed)}/{len(stages)} passos. "
                f"Aguardando {next_step.get('targetTime') or '-'} {next_step.get('label') or 'proxima etapa'}"
            ]
        return fluxo_lines + ["✅ Pedidos - OK"]
    return fluxo_lines + [f"❌ Pedidos - {failure_reason(failed) or 'Falha'}"]


def summarize_promopreco(data: dict[str, Any]) -> list[str]:
    notice = str(data.get("notice") or "")
    if "Coleta antiga" in notice or "Sem coleta de hoje" in notice:
        return [f"⚠️ Promocao e Precos - Sem coleta atual: {notice}"]

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for stage in data.get("stages", []):
        key = (promo_environment(stage.get("label", "")), short_batch(stage.get("batch", "")))
        groups.setdefault(key, []).append(stage)

    lines: list[str] = []
    for (environment, batch), stages in sorted(groups.items(), key=lambda item: (item[0][1], item[0][0])):
        prefix = f"{environment} {batch}".strip()
        process_stage = next((stage for stage in stages if str(stage.get("id", "")).endswith("_processo_carga")), None)
        file_stages = [stage for stage in stages if not str(stage.get("id", "")).endswith("_processo_carga")]
        reason = failure_reason(file_stages)
        waiting = [
            stage for stage in file_stages
            if str(stage.get("status") or "") in {"aguardando", "sem_coleta", "warning"}
        ]
        if reason:
            lines.append(f"❌ {prefix} arquivos - {reason}")
        elif waiting:
            next_step = min(waiting, key=lambda stage: str(stage.get("targetTime") or "99:99"))
            if str(next_step.get("statusLabel") or "") == "Atencao":
                lines.append(f"🟡 {prefix} arquivos - {warning_reason(file_stages)}")
            else:
                lines.append(f"🟡 {prefix} arquivos - Aguardando {next_step.get('targetTime') or '-'}")
        else:
            lines.append(f"✅ {prefix} arquivos - {ok_reason(file_stages)}")

        if process_stage:
            process_status = str(process_stage.get("status") or "")
            start_time = process_stage.get("processStartTime") or "-"
            if process_status == "rodando":
                lines.append(f"🟡 {prefix} processo - Rodando desde {start_time}")
            elif process_status in {"aguardando", "sem_coleta"}:
                lines.append(f"🟡 {prefix} processo - Aguardando {process_stage.get('targetTime') or '-'}")
            elif stage_failed(process_stage):
                lines.append(f"❌ {prefix} processo - Falha: {process_stage.get('statusLabel') or process_status}")
            else:
                lines.append(f"✅ {prefix} processo - OK")
    return lines


def summarize_estoque_relex(data: dict[str, Any]) -> list[str]:
    stages = data.get("stages", [])
    if not stages:
        return ["🟡 Estoque RELEX - Aguardando coleta"]
    failed = [stage for stage in stages if stage_failed(stage)]
    waiting = [stage for stage in stages if str(stage.get("status") or "") in {"aguardando", "sem_coleta"}]
    if not failed and not waiting:
        consumed = next((stage for stage in stages if stage.get("id") == "arquivo_consumido"), stages[-1])
        count = int(consumed.get("count") or 0)
        return [f"✅ Estoque RELEX - OK - {count} linha(s)"]
    if waiting and not failed:
        labels = ", ".join(f"{stage.get('label') or 'etapa'} {stage.get('targetTime') or '-'}" for stage in waiting)
        return [f"🟡 Estoque RELEX - Aguardando {labels}"]
    stage = failed[0]
    reason = failure_reason(failed)
    if reason == "Sem acesso":
        return ["❌ Estoque RELEX - Sem acesso"]
    label = stage.get("label") or "etapa"
    return [f"❌ Estoque RELEX - Erro: {label}"]


def summarize_retificacao_ret(data: dict[str, Any]) -> list[str]:
    stages = data.get("stages", [])
    stage = stages[0] if stages else {}
    status = str(stage.get("status") or "")
    count = int(stage.get("count") or 0)
    max_files = int(stage.get("maxFiles") or 3)
    if status in {"concluido", "concluido_atrasado"}:
        return [f"✅ Retificacao RET - OK - {count} arquivo(s)"]
    if status in {"aguardando", "sem_coleta"}:
        return [f"🟡 Retificacao RET - Aguardando coleta"]
    reason = failure_reason(stages)
    if status == "sem_acesso" or reason == "Sem acesso":
        return ["❌ Retificacao RET - Sem acesso"]
    return [f"❌ Retificacao RET - {count} arquivo(s), limite {max_files}"]


def summarize_notas_rejeitadas(data: dict[str, Any]) -> list[str]:
    stages = data.get("stages", [])
    stage = stages[0] if stages else {}
    status = str(stage.get("status") or "")
    count = int(stage.get("count") or 0)
    if status in {"concluido", "concluido_atrasado"}:
        return [f"✅ Notas rejeitadas - OK - {count} pendente(s)"]
    if status in {"aguardando", "sem_coleta"}:
        return ["🟡 Notas rejeitadas - Aguardando coleta"]
    reason = failure_reason(stages)
    if status == "sem_acesso" or reason == "Sem acesso":
        return ["❌ Notas rejeitadas - Sem acesso"]
    notes = stage.get("notes") or []
    visible = []
    for note in notes[:8]:
        visible.append(f"NF {note.get('nota') or '-'} L-{note.get('loja') or '-'}")
    suffix = f" (+{len(notes) - 8})" if len(notes) > 8 else ""
    detail = f": {', '.join(visible)}{suffix}" if visible else ""
    return [f"❌ Notas rejeitadas - {count} nota(s){detail}"]


def summarize_devolucao_as400(data: dict[str, Any]) -> list[str]:
    stages = data.get("stages", [])
    failed = [stage for stage in stages if stage_failed(stage)]
    waiting = [stage for stage in stages if str(stage.get("status") or "") in {"aguardando", "sem_coleta"}]
    stage = next((item for item in stages if item.get("id") == "enviado_as400"), stages[-1] if stages else {})
    status = str(stage.get("status") or "")
    file_count = int(stage.get("fileCount") or 0)
    pleno_count = int(stage.get("plenoCount") or 0)
    missing = int(stage.get("missingInFile") or 0)
    extra = int(stage.get("extraInFile") or 0)
    if not failed and not waiting and stages:
        return [f"✅ Devolucao AS400 - OK - arquivo {file_count}, Pleno {pleno_count}"]
    if waiting and not failed:
        next_step = min(waiting, key=lambda item: str(item.get("targetTime") or "99:99"))
        return [f"🟡 Devolucao AS400 - Aguardando {next_step.get('targetTime') or '-'}"]
    reason = failure_reason(stages)
    if status == "sem_acesso" or reason == "Sem acesso":
        return ["❌ Devolucao AS400 - Sem acesso"]
    return [f"❌ Devolucao AS400 - Pleno sem arquivo {missing}, arquivo sem Pleno {extra}"]


def summarize_mercadoria_filial(data: dict[str, Any]) -> list[str]:
    stages = data.get("stages", [])
    failed = [stage for stage in stages if stage_failed(stage)]
    waiting = [stage for stage in stages if str(stage.get("status") or "") in {"aguardando", "sem_coleta"}]
    if not failed and not waiting and stages:
        return ["✅ Mercadoria Filial - OK"]
    if waiting and not failed:
        return ["🟡 Mercadoria Filial - Aguardando"]
    if failed:
        reason = failure_reason(failed)
        if reason == "Sem acesso":
            return ["❌ Mercadoria Filial - Sem acesso"]
        labels = ", ".join(stage.get("label") or "etapa" for stage in failed[:3])
        return [f"❌ Mercadoria Filial - Falha: {labels}"]
    return ["🟡 Mercadoria Filial - Aguardando coleta"]


def monitor_in_scope(title: str, scope: str) -> bool:
    if scope == "all":
        return True
    if scope == "morning":
        return title in {"Pedidos", "Promocao e Precos", "Notas Rejeitadas"}
    if scope == "night":
        return title in {"Estoque RELEX", "Retificacao RET", "Devolucao AS400", "Mercadoria Filial"}
    if scope == "pedidos":
        return title == "Pedidos"
    if scope == "promopreco":
        return title == "Promocao e Precos"
    if scope == "notas-rejeitadas":
        return title == "Notas Rejeitadas"
    if scope == "estoque-relex":
        return title == "Estoque RELEX"
    if scope == "retificacao-ret":
        return title == "Retificacao RET"
    if scope == "devolucao-as400":
        return title == "Devolucao AS400"
    if scope == "mercadoria-filial":
        return title == "Mercadoria Filial"
    if scope == "estoque-retificacao":
        return title in {"Estoque RELEX", "Retificacao RET", "Devolucao AS400", "Mercadoria Filial"}
    return True


def monitor_scope(title: str) -> str:
    return {
        "Pedidos": "pedidos",
        "Promocao e Precos": "promopreco",
        "Notas Rejeitadas": "notas-rejeitadas",
        "Estoque RELEX": "estoque-relex",
        "Retificacao RET": "retificacao-ret",
        "Devolucao AS400": "devolucao-as400",
        "Mercadoria Filial": "mercadoria-filial",
    }.get(title, "all")


def collect_lines(
    base_url: str,
    scope: str = "all",
    policy: dict[str, Any] | None = None,
    muted_scopes: set[str] | None = None,
    api_observations: list | None = None,
) -> list[str]:
    lines: list[str] = []
    for title, path, collection_key in MONITORS:
        if not monitor_in_scope(title, scope):
            continue
        if muted_scopes and monitor_scope(title) in muted_scopes:
            continue
        if policy and not within_monitor_window(alert_policy_for_scope(policy, monitor_scope(title)), datetime.now()):
            continue
        try:
            observations = api_observations if api_observations is not None else []
            data = request_json(base_url.rstrip("/") + path, monitor_scope(title), observations)
        except ApiUnavailable:
            continue
        if title == "Pedidos":
            lines.extend(summarize_pedidos(data))
        elif title == "Promocao e Precos":
            lines.extend(summarize_promopreco(data))
        elif title == "Notas Rejeitadas":
            lines.extend(summarize_notas_rejeitadas(data))
        elif title == "Estoque RELEX":
            lines.extend(summarize_estoque_relex(data))
        elif title == "Retificacao RET":
            lines.extend(summarize_retificacao_ret(data))
        elif title == "Devolucao AS400":
            lines.extend(summarize_devolucao_as400(data))
        elif title == "Mercadoria Filial":
            lines.extend(summarize_mercadoria_filial(data))
        else:
            failed = [item for item in data.get(collection_key, []) if stage_failed(item)]
            lines.append(f"{title} - {'OK' if not failed else 'Falha'}")
    return lines


def fingerprint(lines: list[str]) -> str:
    raw = json.dumps(
        lines,
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_message(lines: list[str]) -> str:
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    return "\n".join(["NOC Pleno", now, *lines])


def build_recovery_message(lines: list[str]) -> str:
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    return "\n".join(["NOC Pleno", now, "✅ Alertas criticos normalizados", *lines])


def error_lines(lines: list[str]) -> list[str]:
    # Before the 09:30 deadline, Pedidos is intentionally an alert rather
    # than a failure. It still needs to reach the configured destinations.
    return [
        line for line in lines
        if line.startswith("❌")
        or "Falha" in line
        or line.startswith("🟡 Pedidos - Alerta:")
    ]


def send_telegram(token: str, chat_id: str, message: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    request = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not body.get("ok"):
        raise RuntimeError(f"Telegram recusou a mensagem para {chat_id}: {body}")


def send_google_chat(webhook: str, message: str) -> None:
    request = urllib.request.Request(
        webhook,
        data=json.dumps({"text": message[:3800]}, ensure_ascii=False).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"Google Chat respondeu HTTP {response.status}.")


def destination_matches_scope(destination: dict[str, Any], scope: str) -> bool:
    scopes = destination.get("scopes") or ["all"]
    return "all" in scopes or scope in scopes


def send_notifications(env: dict[str, str], policy: dict[str, Any], scope: str, message: str) -> int:
    sent = 0
    errors: list[str] = []
    for destination in policy.get("destinations") or []:
        if destination.get("enabled") is False or not destination_matches_scope(destination, scope):
            continue
        kind = str(destination.get("type") or "").strip().lower()
        identifier = str(destination.get("id") or kind or "destino")
        try:
            if kind == "telegram":
                token = env.get(str(destination.get("tokenEnv") or "TELEGRAM_BOT_TOKEN"), "")
                chat_ids = [item.strip() for item in env.get(str(destination.get("chatIdsEnv") or "TELEGRAM_CHAT_IDS"), "").split(",") if item.strip()]
                if not token or not chat_ids:
                    raise RuntimeError("token ou chat ID nao configurado")
                for chat_id in chat_ids:
                    send_telegram(token, chat_id, message)
                sent += len(chat_ids)
            elif kind == "google_chat":
                webhook = str(destination.get("webhook") or env.get(str(destination.get("webhookEnv") or "NOC_GOOGLE_CHAT_WEBHOOK"), "")).strip()
                if not webhook:
                    raise RuntimeError("webhook nao configurado")
                if not webhook.startswith("https://chat.googleapis.com/"):
                    raise RuntimeError("webhook invalido")
                send_google_chat(webhook, message)
                sent += 1
            else:
                raise RuntimeError(f"tipo de destino desconhecido: {kind or '-'}")
        except Exception as exc:  # noqa: BLE001 - entrega em um destino nao impede os demais.
            errors.append(f"{identifier}: {exc}")
    if errors:
        raise RuntimeError("; ".join(errors))
    if not sent:
        raise RuntimeError("Nenhum destino de alerta habilitado para este escopo.")
    return sent


def main() -> None:
    args = parse_args()
    env = load_env()
    base_url = env.get("TELEGRAM_ALERT_BASE_URL", "http://127.0.0.1:8094")
    state_path = Path(env.get("TELEGRAM_ALERT_STATE_FILE") or DEFAULT_STATE)
    if not state_path.is_absolute():
      state_path = ROOT / state_path

    now = datetime.now()
    policy = load_alert_policy(env)
    muted_scopes = active_silenced_scopes(load_alert_acknowledgements(env), now)
    if args.scope in muted_scopes:
        print(f"Alertas de {args.scope} silenciados ate {muted_scopes[args.scope].strftime('%d/%m %H:%M')}; monitoramento segue ativo.")
        return
    alert_settings = alert_policy_for_scope(policy, args.scope)
    if not args.force and not within_monitor_window(alert_settings, now):
        print("Fora da janela de monitoramento configurada; alerta nao enviado.")
        return
    api_observations: list = []
    lines = collect_lines(base_url, args.scope, policy, set(muted_scopes), api_observations)
    process_observations(
        state_path.parent, api_observations,
        lambda message: send_notifications(env, policy, "all", message),
        dry_run=args.dry_run,
    )
    latest_api = {item["url"]: item for item in api_observations}
    api_failed = any(not item["ok"] for item in latest_api.values())
    if api_failed:
        # Do not turn missing monitor data into a business failure or false recovery.
        # Real errors from endpoints that did respond can still be delivered.
        lines = error_lines(lines)
        if not lines:
            print("Consulta incompleta; indisponibilidade tratada no estado global do NOC.")
            return
    if args.only_errors and muted_scopes and not error_lines(lines):
        print("Alertas silenciados para processo(s) em analise; monitoramento segue ativo.")
        return
    if args.dry_run:
        print(build_message(error_lines(lines) if args.only_errors else lines))
        return
    state = load_state(state_path)
    current_scope_state = scope_state(state, args.scope)
    repeat_after = timedelta(seconds=alert_settings["repeatEverySeconds"])
    stop_after = timedelta(seconds=alert_settings["stopAfterSeconds"])

    if args.only_errors:
        errors = error_lines(lines)
        if not errors:
            recovery_repeat = timedelta(seconds=alert_settings["recoveryRepeatEverySeconds"])
            should_repeat_recovery = (
                not alert_settings["recoverySendOnce"]
                and recovery_repeat.total_seconds() > 0
                and bool(current_scope_state.get("recoveredAt"))
            )
            if current_scope_state.get("hadErrors") or should_repeat_recovery:
                recovery_current = fingerprint(["recovery", *lines])
                first_error_at = parse_iso(str(current_scope_state.get("firstErrorAt") or ""))
                if (
                    alert_settings["recoveryOnlyWithinStopWindow"]
                    and stop_after.total_seconds() > 0
                    and first_error_at
                    and now - first_error_at > stop_after
                ):
                    current_scope_state.update({
                        "active": recovery_current,
                        "sentAt": now.isoformat(timespec="seconds"),
                        "count": len(lines),
                        "hadErrors": False,
                        "recoveredAt": now.isoformat(timespec="seconds"),
                        "recoverySuppressedAfterSeconds": alert_settings["stopAfterSeconds"],
                    })
                    write_state(state_path, state)
                    print("Falha normalizada fora da janela de recuperacao; alerta nao enviado.")
                    return
                last_sent_at = parse_iso(str(current_scope_state.get("sentAt") or ""))
                if (
                    not args.force
                    and current_scope_state.get("active") == recovery_current
                    and (
                        alert_settings["recoverySendOnce"]
                        or recovery_repeat.total_seconds() <= 0
                        or (last_sent_at and now - last_sent_at < recovery_repeat)
                    )
                ):
                    print("Mensagem de normalizacao ja enviada para este estado do monitor.")
                    return
                message = build_recovery_message(lines)
                if args.dry_run:
                    print(message)
                    return
                if not alert_settings["sendRecovery"]:
                    current_scope_state.update({
                        "active": recovery_current,
                        "sentAt": now.isoformat(timespec="seconds"),
                        "count": len(lines),
                        "hadErrors": False,
                        "recoveredAt": now.isoformat(timespec="seconds"),
                    })
                    write_state(state_path, state)
                    print("Normalizacao registrada; envio desabilitado pela politica.")
                    return
                sent = send_notifications(env, policy, args.scope, message)
                current_scope_state.update({
                    "active": recovery_current,
                    "sentAt": now.isoformat(timespec="seconds"),
                    "count": len(lines),
                    "hadErrors": False,
                    "recoveredAt": now.isoformat(timespec="seconds"),
                })
                write_state(state_path, state)
                print(f"Normalizacao enviada para {sent} destino(s).")
                return
            print("Sem falhas; alerta nao enviado.")
            return
        # Pedidos builds a multi-line operational summary before its yellow
        # alert. Keep that context in the notification until the 09:30 limit.
        if args.scope == "pedidos" and any(line.startswith("🟡 Pedidos - Alerta:") for line in errors):
            lines = lines
        else:
            lines = errors

    current = fingerprint(lines)
    current_errors = error_lines(lines)
    if not args.force and current_scope_state.get("active") == current:
        if current_errors:
            first_error_at = parse_iso(str(current_scope_state.get("firstErrorAt") or current_scope_state.get("sentAt") or ""))
            last_sent_at = parse_iso(str(current_scope_state.get("sentAt") or ""))
            current_scope_state["hadErrors"] = True
            current_scope_state["lastErrorSeenAt"] = now.isoformat(timespec="seconds")
            if stop_after.total_seconds() > 0 and first_error_at and now - first_error_at > stop_after:
                current_scope_state["suppressedAfterSeconds"] = alert_settings["stopAfterSeconds"]
                write_state(state_path, state)
                print("Alerta persistente fora da janela configurada; envio suprimido.")
                return
            if last_sent_at and now - last_sent_at < repeat_after:
                write_state(state_path, state)
                print("Mensagem ja enviada para este estado do monitor.")
                return
        else:
            print("Mensagem ja enviada para este estado do monitor.")
            return

    if current_errors and not args.force:
        previous_active = current_scope_state.get("active")
        if previous_active != current:
            current_scope_state["firstErrorAt"] = now.isoformat(timespec="seconds")
        elif not current_scope_state.get("firstErrorAt"):
            current_scope_state["firstErrorAt"] = now.isoformat(timespec="seconds")

        first_error_at = parse_iso(str(current_scope_state.get("firstErrorAt") or ""))
        first_after = timedelta(seconds=alert_settings["firstErrorAfterSeconds"])
        if first_error_at and now - first_error_at < first_after:
            current_scope_state.update({
                "active": current,
                "hadErrors": True,
                "lastErrorSeenAt": now.isoformat(timespec="seconds"),
            })
            write_state(state_path, state)
            print("Falha registrada; aguardando atraso inicial configurado para alertar.")
            return

    if not args.force and current_errors and current_scope_state.get("active") == current:
        first_error_at = parse_iso(str(current_scope_state.get("firstErrorAt") or ""))
        if stop_after.total_seconds() > 0 and first_error_at and now - first_error_at > stop_after:
            current_scope_state["suppressedAfterSeconds"] = alert_settings["stopAfterSeconds"]
            write_state(state_path, state)
            print("Alerta persistente fora da janela configurada; envio suprimido.")
            return

    if current_errors and not args.force and not alert_settings["sendFailure"]:
        current_scope_state.update({
            "active": current,
            "hadErrors": True,
            "lastErrorSeenAt": now.isoformat(timespec="seconds"),
        })
        current_scope_state.setdefault("firstErrorAt", now.isoformat(timespec="seconds"))
        write_state(state_path, state)
        print("Falha registrada; envio desabilitado pela politica.")
        return

    message = build_message(lines)
    if args.dry_run:
        print(message)
        return

    sent = send_notifications(env, policy, args.scope, message)

    current_scope_state.update({
        "active": current,
        "sentAt": now.isoformat(timespec="seconds"),
        "count": len(lines),
        "hadErrors": bool(current_errors),
    })
    if current_errors:
        current_scope_state.setdefault("firstErrorAt", now.isoformat(timespec="seconds"))
        current_scope_state["lastErrorSeenAt"] = now.isoformat(timespec="seconds")
    else:
        current_scope_state.pop("firstErrorAt", None)
        current_scope_state.pop("lastErrorSeenAt", None)
        current_scope_state.pop("suppressedAfterSeconds", None)
    write_state(state_path, state)
    print(f"Alerta enviado para {sent} destino(s).")


if __name__ == "__main__":
    main()
