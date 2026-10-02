#!/usr/bin/env python3
"""Painel local para extrair e corrigir o estoque do Pleno."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import platform
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DIR = ROOT / "estoque-update-app"
OUTPUTS_DIR = ROOT / "outputs"
DEPLOY_HISTORY_FILE = OUTPUTS_DIR / "estoque_envios" / "historico.jsonl"
REJECTED_XML_DIR = ROOT / "rejeitados"
REJECTED_REMOTE_DIR = "/servpleno/importacao/NFE/rejeitado"
PACKAGED_PYTHON = Path("/Users/alexandrematheuscrose/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3")
PYTHON_BIN = os.environ.get("ESTOQUE_PYTHON_BIN") or str(PACKAGED_PYTHON if PACKAGED_PYTHON.exists() else Path(sys.executable))
job_lock = threading.Lock()
job: dict[str, object] = {"status": "idle", "log": [], "result": None, "error": None, "period": None, "progress": None, "deployment": None}


def append_log(message: str) -> None:
    with job_lock:
        job["log"].append(f"{datetime.now():%H:%M:%S}  {message}")
        job["log"] = job["log"][-80:]


def record_deployment(method: str, result: dict[str, object]) -> None:
    DEPLOY_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "sent_at": datetime.now().isoformat(timespec="seconds"),
        "method": method,
        "file": str(result["name"]),
        "local_file": str(result["file"]),
        "destination": "amc018br@172.22.20.101:/servpleno/exportacao",
    }
    with DEPLOY_HISTORY_FILE.open("a", encoding="utf-8") as history:
        history.write(json.dumps(record, ensure_ascii=False) + "\n")


def deployment_history() -> list[dict[str, object]]:
    if not DEPLOY_HISTORY_FILE.exists():
        return []
    records = []
    for line in DEPLOY_HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(records[-30:]))


def latest_store_list() -> list[int]:
    manifests = sorted(OUTPUTS_DIR.glob("pleno_estoque_atual_layout_*/manifest_estoque_*.json"))
    for manifest in reversed(manifests):
        try:
            stores = json.loads(manifest.read_text(encoding="utf-8")).get("stores", [])
            if len(stores) >= 100:
                return [int(store) for store in stores]
        except (OSError, ValueError, TypeError):
            continue
    raise RuntimeError("Nao encontrei uma extracao integral anterior para obter a lista de lojas.")


def run_command(command: list[str], label: str, watch_dir: Path | None = None) -> None:
    append_log(label)
    process = subprocess.Popen(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    last_size = -1
    while process.poll() is None:
        if watch_dir and watch_dir.exists():
            candidates = sorted(watch_dir.glob("estoque_*.csv"), key=lambda item: item.stat().st_mtime)
            if candidates:
                current = candidates[-1]
                size = current.stat().st_size
                with job_lock:
                    job["progress"] = {"file": current.name, "bytes": size}
                if size != last_size:
                    append_log(f"Arquivo em geracao: {current.name} ({size / 1024 / 1024:.1f} MB)")
                    last_size = size
        time.sleep(3)
    output = process.stdout.read() if process.stdout else ""
    for line in output.splitlines():
        if line.strip():
            append_log(line.strip())
    if process.returncode:
        raise RuntimeError(f"{label}: processo terminou com erro.")


def sync_rejected_xmls(password: str) -> tuple[int, int]:
    if not password:
        raise RuntimeError("Informe a senha do Pleno para sincronizar os XMLs rejeitados.")
    host = "amc018br@172.22.20.101"
    append_log("XMLs rejeitados: consultando arquivos no Pleno.")
    code, output = run_with_ssh_password(
        [
            "ssh", "-o", "StrictHostKeyChecking=accept-new", host,
            f"cd {shlex.quote(REJECTED_REMOTE_DIR)} && find . -type f -iname '*.xml' -printf '%P\\t%s\\n'",
        ],
        password,
        "XML remoto",
        log_output=False,
    )
    if code:
        raise RuntimeError(f"Nao foi possivel listar XMLs rejeitados: {output}")
    remote_files = []
    for line in output.splitlines():
        try:
            relative, size = line.rsplit("\t", 1)
            if relative and ".." not in Path(relative).parts:
                remote_files.append((relative, int(size)))
        except ValueError:
            continue
    pending = []
    for relative, size in remote_files:
        local = REJECTED_XML_DIR / relative
        if not local.exists() or local.stat().st_size != size:
            pending.append((relative, size))
    append_log(f"XMLs rejeitados: {len(remote_files)} no Pleno; {len(pending)} novos ou alterados para baixar.")
    for index, (relative, _) in enumerate(pending, 1):
        local = REJECTED_XML_DIR / relative
        local.parent.mkdir(parents=True, exist_ok=True)
        code, output = run_with_ssh_password(
            ["scp", "-q", "-o", "StrictHostKeyChecking=accept-new", f"{host}:{REJECTED_REMOTE_DIR}/{relative}", str(local)],
            password,
            "SCP XML",
            log_output=False,
        )
        if code:
            raise RuntimeError(f"Falha ao baixar XML {relative}: {output}")
        if index == 1 or index == len(pending) or index % 25 == 0:
            append_log(f"XMLs rejeitados: baixados {index}/{len(pending)}.")
    return len(remote_files), len(pending)


def latest_rejected_items(start: date, end: date) -> Path:
    files = sorted(
        OUTPUTS_DIR.glob(f"rejeitados_lojas_proprias/auditoria_xmls_rejeitados_pleno_estoque_{start}_a_{end}_*_itens.csv"),
        key=lambda item: item.stat().st_mtime,
    )
    if not files:
        raise RuntimeError("A auditoria de XMLs rejeitados nao gerou o arquivo de itens.")
    return files[-1]


def latest_rejected_consolidated() -> Path:
    files = sorted(
        OUTPUTS_DIR.glob("rejeitados_lojas_proprias/itens_para_recriar_estoque_por_filial_*/itens_para_recriar_estoque_consolidado_por_loja_artigo.csv"),
        key=lambda item: item.stat().st_mtime,
    )
    if not files:
        raise RuntimeError("O consolidado de rejeitados nao foi encontrado.")
    return files[-1]


def run_job(start_date: str, end_date: str, password: str) -> None:
    with job_lock:
        job.update(status="running", error=None, result=None, log=[], period={"start": start_date, "end": end_date}, progress=None, deployment=None)
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        if end < start:
            raise ValueError("A data final precisa ser igual ou posterior a data inicial.")
        sync_rejected_xmls(password)
        run_command(
            [PYTHON_BIN, "scripts/auditar_xmls_rejeitados_estoque.py", "--start-date", start.isoformat(), "--end-date", end.isoformat()],
            "Auditando XMLs rejeitados contra o Pleno",
        )
        rejected_items = latest_rejected_items(start, end)
        run_command(
            [PYTHON_BIN, "scripts/gerar_csv_recriar_estoque_rejeitados.py", str(rejected_items)],
            "Gerando consolidado de rejeitados sem movimento",
        )
        rejected_consolidated = latest_rejected_consolidated()
        append_log(f"Consolidado de rejeitados pronto: {rejected_consolidated.name}")

        stores = latest_store_list()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as file:
            file.write("\n".join(map(str, stores)) + "\n")
            stores_file = Path(file.name)
        try:
            stamp_dir = OUTPUTS_DIR / f"pleno_estoque_atual_layout_{end:%Y%m%d}"
            stamp_dir.mkdir(parents=True, exist_ok=True)
            append_log(f"Extracao de {len(stores)} lojas iniciada.")
            run_command(
                [PYTHON_BIN, "scripts/exportar_estoque_atual_pleno_layout.py", "--lojas-file", str(stores_file), "--out-dir", str(stamp_dir)],
                "Extraindo estoque atual do Pleno",
                stamp_dir,
            )
        finally:
            stores_file.unlink(missing_ok=True)

        manifests = sorted(stamp_dir.glob("manifest_estoque_*.json"), key=lambda item: item.stat().st_mtime)
        if not manifests:
            raise RuntimeError("A extracao terminou sem gerar manifesto.")
        stock_path = Path(json.loads(manifests[-1].read_text(encoding="utf-8"))["file"])
        result_dir = OUTPUTS_DIR / f"estoque_atual_mais_notas_sem_checkin_e_rejeitados_{start:%Y%m%d}_{end:%Y%m%d}"
        run_command(
            [
                PYTHON_BIN,
                "scripts/somar_estoque_com_notas_sem_checkin.py",
                "--estoque", str(stock_path),
                "--start-date", start.isoformat(),
                "--end-date", end.isoformat(),
                "--rejeitados-consolidado", str(rejected_consolidated),
                "--out-dir", str(result_dir),
                "--preserve-layout",
                "--verify",
            ],
            "Somando notas sem check-in e conferindo",
        )
        final_path = result_dir / stock_path.name
        if not final_path.exists():
            raise RuntimeError("O arquivo final nao foi encontrado.")
        with job_lock:
            job["status"] = "completed"
            job["result"] = {"file": str(final_path), "folder": str(result_dir), "name": final_path.name}
        append_log("Concluido: notas pendentes e rejeitados sem movimento foram aplicados; itens ausentes no estoque-base ficaram fora.")
    except Exception as error:
        with job_lock:
            job["status"] = "failed"
            job["error"] = str(error)
        append_log(f"ERRO: {error}")


def update_deployment(message: str) -> None:
    with job_lock:
        job["deployment"] = {"status": "sending", "message": message}
    append_log(message)


def run_with_ssh_password(
    command: list[str], password: str, label: str, log_output: bool = True
) -> tuple[int, str]:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix="pleno_askpass_", delete=False) as askpass:
        askpass.write("#!/bin/sh\nprintf '%s\\n' \"$STOCK_DEPLOY_PASSWORD\"\n")
        askpass_path = Path(askpass.name)
    askpass_path.chmod(0o700)
    try:
        env = os.environ | {
            "SSH_ASKPASS": str(askpass_path),
            "SSH_ASKPASS_REQUIRE": "force",
            "DISPLAY": ":0",
            "STOCK_DEPLOY_PASSWORD": password,
        }
        process = subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        output = []
        if process.stdout:
            for line in process.stdout:
                clean = line.strip()
                if clean:
                    output.append(clean)
                    if log_output:
                        append_log(f"{label}: {clean}")
        return process.wait(), "\n".join(output)
    finally:
        askpass_path.unlink(missing_ok=True)


def deploy_result(password: str) -> None:
    with job_lock:
        result = job.get("result")
    if not result:
        raise RuntimeError("Nenhum arquivo final esta disponivel para envio.")
    if not password:
        raise RuntimeError("Informe a senha do usuario amc018br para enviar.")
    local_file = safe_output_path(str(result["file"]))
    host = "amc018br@172.22.20.101"
    remote_dir = "/servpleno/exportacao"
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    remote_temp = f"{remote_dir}/.{local_file.name}.upload-{stamp}"
    update_deployment(f"SCP: enviando {local_file.name} ({local_file.stat().st_size / 1024 / 1024:.1f} MB) para o Pleno.")
    upload_code, upload_output = run_with_ssh_password(
        ["scp", "-v", "-o", "StrictHostKeyChecking=accept-new", str(local_file), f"{host}:{remote_temp}"],
        password,
        "SCP",
    )
    if upload_code:
        raise RuntimeError(f"Falha no envio: {upload_output}")
    update_deployment("SSH: publicando o arquivo e ajustando permissoes no Pleno.")
    script = (
        f"set -eu; DIR={shlex.quote(remote_dir)}; TARGET={shlex.quote(remote_dir + '/' + local_file.name)}; "
        f"TMP={shlex.quote(remote_temp)}; STAMP={shlex.quote(stamp)}; "
        "echo 'SSH: verificando arquivos anteriores'; "
        "for OLD in \"$DIR\"/estoque_*.csv; do [ -e \"$OLD\" ] || continue; echo \"SSH: renomeando $OLD\"; mv \"$OLD\" \"$OLD.old-$STAMP\"; done; "
        "echo 'SSH: publicando novo arquivo'; mv \"$TMP\" \"$TARGET\"; "
        "echo 'SSH: aplicando permissao 775'; chmod 775 \"$TARGET\"; "
        "echo 'SSH: publicacao concluida'"
    )
    finalize_code, finalize_output = run_with_ssh_password(
        ["ssh", "-o", "StrictHostKeyChecking=accept-new", host, script], password, "SSH"
    )
    if finalize_code:
        raise RuntimeError(f"O arquivo foi enviado, mas nao foi publicado: {finalize_output}")
    with job_lock:
        if isinstance(job.get("result"), dict):
            job["result"]["deployed"] = True
        job["deployment"] = {"status": "completed", "message": "Arquivo enviado e publicado no Pleno."}
        record_deployment("painel", job["result"])
    append_log(f"Arquivo enviado para {remote_dir}; CSVs anteriores foram renomeados com .old-{stamp}.")


def safe_output_path(value: str) -> Path:
    path = Path(value).resolve()
    if OUTPUTS_DIR.resolve() not in path.parents:
        raise ValueError("Caminho invalido.")
    return path


def restore_latest_result() -> None:
    files = sorted(OUTPUTS_DIR.glob("estoque_atual_mais_notas_sem_checkin*/estoque_*.csv"), key=lambda item: item.stat().st_mtime)
    if not files:
        return
    latest = files[-1]
    with job_lock:
        job.update(
            status="completed",
            result={"file": str(latest), "folder": str(latest.parent), "name": latest.name},
            error=None,
        )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, status: int, data: object) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            with job_lock:
                self.send_json(HTTPStatus.OK, job)
            return
        if parsed.path == "/api/deployments":
            self.send_json(HTTPStatus.OK, deployment_history())
            return
        if parsed.path == "/api/download":
            try:
                path = safe_output_path(parse_qs(parsed.query).get("path", [""])[0])
                if not path.is_file():
                    raise ValueError("Arquivo nao encontrado.")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
                self.send_header("Content-Length", str(path.stat().st_size))
                self.end_headers()
                with path.open("rb") as source:
                    while chunk := source.read(1024 * 1024):
                        self.wfile.write(chunk)
            except ValueError as error:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": str(error)})
            return
        path = (PUBLIC_DIR / ("index.html" if parsed.path == "/" else parsed.path.lstrip("/"))).resolve()
        if PUBLIC_DIR.resolve() not in path.parents and path != PUBLIC_DIR / "index.html":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        if self.path == "/api/run":
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
            with job_lock:
                if job["status"] == "running":
                    self.send_json(HTTPStatus.CONFLICT, {"error": "Ja existe uma execucao em andamento."})
                    return
            threading.Thread(
                target=run_job,
                args=(data.get("startDate", ""), data.get("endDate", ""), data.get("password", "")),
                daemon=True,
            ).start()
            self.send_json(HTTPStatus.ACCEPTED, {"status": "running"})
            return
        if self.path == "/api/open-folder":
            with job_lock:
                result = job.get("result")
            if not result:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Nenhum resultado disponivel."})
                return
            folder = safe_output_path(str(result["folder"]))
            command = ["open", str(folder)] if platform.system() == "Darwin" else ["xdg-open", str(folder)]
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.send_json(HTTPStatus.OK, {"opened": True})
            return
        if self.path == "/api/deploy":
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
            try:
                deploy_result(str(data.get("password", "")))
                self.send_json(HTTPStatus.OK, {"deployed": True})
            except RuntimeError as error:
                with job_lock:
                    job["deployment"] = {"status": "failed", "message": str(error)}
                append_log(f"ERRO NO ENVIO: {error}")
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        if self.path == "/api/register-manual-deploy":
            with job_lock:
                result = job.get("result")
            if not result:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Nenhum arquivo final esta disponivel para registrar."})
                return
            record_deployment("manual", result)
            append_log("Envio manual registrado no historico.")
            self.send_json(HTTPStatus.OK, {"registered": True})
            return
        self.send_error(HTTPStatus.NOT_FOUND)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8110)
    args = parser.parse_args()
    restore_latest_result()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Painel: http://127.0.0.1:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
