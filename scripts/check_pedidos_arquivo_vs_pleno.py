#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
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

DEFAULT_OUT = ROOT / "outputs" / "pleno_business_monitor" / "pedidos_arquivo_vs_pleno.json"
DEFAULT_STATUS = ROOT / "outputs" / "pleno_business_monitor" / "pedidos.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cruza os NUMERO_PEDIDO do arquivo PEDIDO do servidor com o Pleno."
    )
    parser.add_argument("--date", default=date.today().strftime("%Y%m%d"))
    parser.add_argument("--remote-dir", default="/servpleno/importacao")
    parser.add_argument("--out-file", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--status-file", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--tipo-pedido", type=int, default=3)
    return parser.parse_args()


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
    env = dict(os.environ)
    env.update(load_env_file(ROOT / ".env"))
    for path in (
        ROOT / "config" / "pedidos_business_monitor_pull.env",
        ROOT / "config" / "pleno_fetch_remote.env",
    ):
        for key, value in load_env_file(path).items():
            env.setdefault(key, value)
    return env


def remote_config(env: dict[str, str]) -> tuple[str, str, str, str]:
    user = env.get("PEDIDOS_REMOTE_USER") or env.get("STOCK_REMOTE_USER") or ""
    host = env.get("PEDIDOS_REMOTE_HOST") or env.get("STOCK_REMOTE_HOST") or ""
    port = env.get("PEDIDOS_REMOTE_PORT") or env.get("STOCK_REMOTE_PORT") or "22"
    password = env.get("PEDIDOS_SSH_PASSWORD") or env.get("STOCK_REMOTE_PASSWORD") or ""
    if not user or not host:
        raise SystemExit("Configure PEDIDOS_REMOTE_USER/PEDIDOS_REMOTE_HOST para acessar o servidor dos pedidos.")
    return user, host, port, password


def run_remote_cat(env: dict[str, str], remote_dir: str, yyyymmdd: str, tipo_pedido: int = 3) -> tuple[str, str]:
    user, host, port, password = remote_config(env)
    selector = (ROOT / "scripts" / "select_pedidos_files.py").read_text(encoding="utf-8")
    remote_cmd = "python3 -c " + sh_quote(selector) + " " + " ".join(
        sh_quote(value) for value in [remote_dir, yyyymmdd, "content", str(tipo_pedido)]
    )
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
        remote_cmd,
    ]
    askpass_path = None
    proc_env = os.environ.copy()
    if password:
        fd, askpass_path = tempfile.mkstemp(prefix="pedidos-askpass.", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            fp.write('#!/bin/sh\nprintf "%s\\n" "$PEDIDOS_SSH_PASSWORD"\n')
        os.chmod(askpass_path, 0o700)
        proc_env.update(
            {
                "DISPLAY": proc_env.get("DISPLAY", ":0"),
                "SSH_ASKPASS": askpass_path,
                "SSH_ASKPASS_REQUIRE": "force",
                "PEDIDOS_SSH_PASSWORD": password,
            }
        )
    try:
        completed = subprocess.run(
            cmd,
            env=proc_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    finally:
        if askpass_path:
            Path(askpass_path).unlink(missing_ok=True)

    if completed.returncode != 0:
        raise SystemExit(f"Falha no comando remoto (codigo {completed.returncode}): {completed.stderr.strip() or 'sem diagnostico remoto'}")

    lines = completed.stdout.splitlines()
    marker_index = next((i for i, line in enumerate(lines) if line.startswith("__PEDIDOS_FILE__=")), -1)
    if marker_index < 0:
        raise SystemExit("Nao encontrei o marcador do arquivo na saida SSH.")
    file_name = lines[marker_index].split("=", 1)[1].strip()
    if not file_name:
        raise SystemExit(f"Nenhum arquivo PEDIDO_{yyyymmdd}*.csv com TIPO_PEDIDO={tipo_pedido} encontrado em {remote_dir}.")
    csv_text = "\n".join(lines[marker_index + 1 :])
    return file_name, csv_text


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def read_pedidos(csv_text: str) -> tuple[list[str], dict[str, str]]:
    sample = csv_text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,|\t")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"
    reader = csv.DictReader(io.StringIO(csv_text), dialect=dialect)
    if not reader.fieldnames or "NUMERO_PEDIDO" not in reader.fieldnames:
        raise SystemExit(f"Coluna NUMERO_PEDIDO nao encontrada. Colunas: {reader.fieldnames}")
    pedidos = []
    lojas_por_pedido: dict[str, str] = {}
    for row in reader:
        pedido = str(row.get("NUMERO_PEDIDO") or "").strip()
        if pedido:
            pedidos.append(pedido)
            cnpj_destino = str(row.get("CNPJ_FILIAL_DESTINATARIO") or "").strip()
            if cnpj_destino:
                lojas_por_pedido[pedido] = cnpj_destino.zfill(14)
    return sorted(set(pedidos)), lojas_por_pedido


def query_pleno(env: dict[str, str], pedidos: list[str], tipo_pedido: int) -> tuple[dict[str, Any], dict[str, Any]]:
    import pymysql

    conn = pymysql.connect(
        host=env["MYSQL_HOST"],
        port=int(env["MYSQL_PORT"]),
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        database=env["MYSQL_DATABASE"],
        charset="latin1",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        encontrados: dict[str, Any] = {}
        todos_tipos: dict[str, Any] = {}
        for chunk in chunks(pedidos, 500):
            placeholders = ", ".join(["%s"] * len(chunk))
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        CAST(com16_nro_pedtransf_trd AS CHAR) AS pedido,
                        dom83_tipo_pedtransf_id AS tipo,
                        cfg06_numero AS loja,
                        pes03_cnpj AS cnpj_destino,
                        COUNT(*) AS registros,
                        SUM(item_stats.itens) AS itens,
                        SUM(item_stats.qtd_confirmada_preenchida) AS qtd_confirmada_preenchida,
                        SUM(item_stats.itens_alterados) AS itens_alterados,
                        MAX(CASE
                            WHEN com16_flgrevisado = 1
                             AND com16_dthr_cancelado IS NULL
                            THEN 1 ELSE 0
                        END) AS situacao_concluido,
                        MIN(com16_dthr) AS primeiro,
                        MAX(com16_dthr) AS ultimo
                    FROM pleno.com16_pretransferencia
                    LEFT JOIN pleno.cfg06_filial
                        ON cfg06_id = cfg06_filial_dest_id
                    LEFT JOIN pleno.pes03_estabelecimento
                        ON pes03_estabelecimento_id = pes03_id
                    LEFT JOIN (
                        SELECT
                            com16_pretransferencia_id,
                            COUNT(*) AS itens,
                            SUM(CASE WHEN com19_qtd_confirmada IS NOT NULL THEN 1 ELSE 0 END) AS qtd_confirmada_preenchida,
                            SUM(CASE WHEN com19_qtd_confirmada IS NOT NULL AND com19_qtd_confirmada <> com19_qtd THEN 1 ELSE 0 END) AS itens_alterados
                        FROM pleno.com19_pretransferencia_item
                        GROUP BY com16_pretransferencia_id
                    ) item_stats
                        ON item_stats.com16_pretransferencia_id = com16_id
                    WHERE com16_nro_pedtransf_trd IN ({placeholders})
                    GROUP BY com16_nro_pedtransf_trd, dom83_tipo_pedtransf_id, cfg06_numero, pes03_cnpj
                    """,
                    chunk,
                )
                for row in cur.fetchall():
                    pedido = str(row["pedido"])
                    row["primeiro"] = str(row["primeiro"]) if row["primeiro"] is not None else None
                    row["ultimo"] = str(row["ultimo"]) if row["ultimo"] is not None else None
                    todos_tipos.setdefault(pedido, []).append(row)
                    if int(row["tipo"]) == tipo_pedido:
                        encontrados[pedido] = row
    finally:
        conn.close()
    return encontrados, todos_tipos


def query_filiais_por_cnpj(env: dict[str, str], cnpjs: list[str]) -> dict[str, dict[str, Any]]:
    if not cnpjs:
        return {}

    import pymysql

    conn = pymysql.connect(
        host=env["MYSQL_HOST"],
        port=int(env["MYSQL_PORT"]),
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        database=env["MYSQL_DATABASE"],
        charset="latin1",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        filiais: dict[str, dict[str, Any]] = {}
        for chunk in chunks(cnpjs, 500):
            placeholders = ", ".join(["%s"] * len(chunk))
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        e.pes03_cnpj AS cnpj,
                        f.cfg06_id AS filial_id,
                        f.cfg06_numero AS loja,
                        f.cfg06_nome AS nome,
                        f.cfg06_situacao AS situacao
                    FROM pleno.pes03_estabelecimento e
                    INNER JOIN pleno.cfg06_filial f
                        ON f.pes03_estabelecimento_id = e.pes03_id
                    WHERE e.pes03_cnpj IN ({placeholders})
                    ORDER BY e.pes03_cnpj, f.cfg06_situacao = 'A' DESC, f.cfg06_numero
                    """,
                    chunk,
                )
                for row in cur.fetchall():
                    cnpj = str(row["cnpj"]).zfill(14)
                    filiais.setdefault(cnpj, row)
    finally:
        conn.close()
    return filiais


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {"collector": "pedidos-monitor", "events": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def chunks(values: list[str], size: int):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def pleno_timestamp_to_iso(value: Any) -> str:
    """Convert the naive MySQL datetime into the local timestamp used by the NOC."""
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed.isoformat(timespec="seconds")


def main() -> None:
    args = parse_args()
    env = load_env()
    file_name, csv_text = run_remote_cat(env, args.remote_dir, args.date, args.tipo_pedido)
    pedidos_arquivo, lojas_por_pedido = read_pedidos(csv_text)
    encontrados_todos, todos_tipos = query_pleno(env, pedidos_arquivo, args.tipo_pedido)
    cnpjs_arquivo = sorted(set(lojas_por_pedido.values()))
    filiais_por_cnpj = query_filiais_por_cnpj(env, cnpjs_arquivo)
    cnpjs_sem_filial = sorted(set(cnpjs_arquivo) - set(filiais_por_cnpj))

    def loja_do_pedido(pedido: str) -> int | None:
        cnpj = lojas_por_pedido.get(pedido)
        filial = filiais_por_cnpj.get(cnpj or "")
        if not filial or filial.get("loja") in (None, ""):
            return None
        return int(filial["loja"])

    # Franquias podem existir no arquivo por cadastro indevido no Pleno, mas nao fazem parte
    # do fluxo RELEX de lojas proprias.
    pedidos_franquia = sorted(pedido for pedido in pedidos_arquivo if (loja := loja_do_pedido(pedido)) is not None and loja > 3000)
    pedidos_monitorados = [pedido for pedido in pedidos_arquivo if pedido not in set(pedidos_franquia)]
    encontrados = {pedido: row for pedido, row in encontrados_todos.items() if pedido in set(pedidos_monitorados)}
    faltando = [pedido for pedido in pedidos_monitorados if pedido not in encontrados]
    encontrados_outro_tipo = {
        pedido: todos_tipos[pedido]
        for pedido in faltando
        if pedido in todos_tipos
    }

    lojas_numeros_arquivo = sorted(
        {
            int(filial["loja"])
            for filial in filiais_por_cnpj.values()
            if filial.get("loja") not in (None, "") and int(filial["loja"]) <= 3000
        }
    )
    lojas_numeros_pleno = sorted(
        {
            loja
            for pedido in encontrados
            for loja in [loja_do_pedido(pedido)]
            if loja is not None
        }
    )
    lojas_faltando = sorted(set(lojas_numeros_arquivo) - set(lojas_numeros_pleno))
    lojas_stats: dict[int, dict[str, int]] = {}
    for pedido, row in encontrados.items():
        loja = loja_do_pedido(pedido)
        if loja is None:
            continue
        stats = lojas_stats.setdefault(loja, {"pedidos": 0, "itens": 0, "confirmados": 0, "alterados": 0})
        stats["pedidos"] += 1
        stats["itens"] += int(row.get("itens") or 0)
        stats["confirmados"] += int(row.get("qtd_confirmada_preenchida") or 0)
        stats["alterados"] += int(row.get("itens_alterados") or 0)
    pedidos_concluidos = sorted(
        pedido
        for pedido, row in encontrados.items()
        if int(row.get("situacao_concluido") or 0) == 1
    )
    pedidos_concluidos_lojas = sorted(
        {
            loja_do_pedido(pedido)
            for pedido in pedidos_concluidos
            if loja_do_pedido(pedido) is not None
        }
    )
    lojas_pendentes_conclusao = sorted(set(lojas_numeros_pleno) - set(pedidos_concluidos_lojas))
    pedidos_pendentes_conclusao = sorted(set(encontrados) - set(pedidos_concluidos))
    pleno_first_times = [pleno_timestamp_to_iso(row.get("primeiro")) for row in encontrados.values()]
    pleno_last_times = [pleno_timestamp_to_iso(row.get("ultimo")) for row in encontrados.values()]
    pleno_first_at = min((value for value in pleno_first_times if value), default="")
    pleno_last_at = max((value for value in pleno_last_times if value), default="")

    result = {
        "checkedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "date": args.date,
        "remoteFile": file_name,
        "tipoPedidoValidado": args.tipo_pedido,
        "totalArquivo": len(pedidos_monitorados),
        "totalArquivoOriginal": len(pedidos_arquivo),
        "totalFranquiasIgnoradas": len(pedidos_franquia),
        "pedidosFranquiaIgnorados": pedidos_franquia,
        "totalPleno": len(encontrados),
        "totalPedidosConcluidos": len(pedidos_concluidos),
        "totalFaltando": len(faltando),
        "totalLojasArquivo": len(lojas_numeros_arquivo),
        "totalLojasPleno": len(lojas_numeros_pleno),
        "totalLojasPedidoConcluido": len(pedidos_concluidos_lojas),
        "primeiroPedidoNoPlenoAt": pleno_first_at,
        "ultimoPedidoNoPlenoAt": pleno_last_at,
        "filiaisPorCnpj": filiais_por_cnpj,
        "cnpjsSemFilial": cnpjs_sem_filial,
        "lojasNumerosPleno": lojas_numeros_pleno,
        "lojasNumerosPedidoConcluido": pedidos_concluidos_lojas,
        "lojasNumerosPendentesConclusao": lojas_pendentes_conclusao,
        "lojasStats": lojas_stats,
        "pedidosConcluidos": pedidos_concluidos,
        "pedidosPendentesConclusao": pedidos_pendentes_conclusao,
        "lojasFaltando": lojas_faltando,
        "faltando": faltando,
        "encontradosOutroTipo": encontrados_outro_tipo,
        "status": "ok" if not faltando and not lojas_faltando and not cnpjs_sem_filial else "falha",
    }

    write_json(args.out_file, result)

    details = (
        f"Arquivo x Pleno OK. Pedidos: {len(encontrados)}/{len(pedidos_monitorados)}. "
        f"Lojas importadas: {len(lojas_numeros_pleno)}/{len(lojas_numeros_arquivo)}"
    )
    if pleno_first_at and pleno_last_at:
        details += f" Consumo no Pleno: {pleno_first_at[11:16]} a {pleno_last_at[11:16]}."
    if lojas_numeros_pleno:
        details += f" ({', '.join(str(loja) for loja in lojas_numeros_pleno)})."
    else:
        details += "."
    filiais_nao_ativas = [
        filial
        for filial in filiais_por_cnpj.values()
        if str(filial.get("situacao") or "").upper() != "A"
    ]
    if filiais_nao_ativas:
        details += " Conferir filial: " + "; ".join(
            f"CNPJ {filial.get('cnpj')} -> {filial.get('loja')} {filial.get('nome')} ({filial.get('situacao')})"
            for filial in filiais_nao_ativas
        ) + "."
    if pedidos_franquia:
        details += f" Franquias ignoradas: {len(pedidos_franquia)}."
    if faltando:
        details = f"Arquivo x Pleno com falha. Pedidos faltando: {', '.join(faltando)}."
    elif lojas_faltando:
        details = f"Arquivo x Pleno com falha. Lojas faltando: {', '.join(str(loja) for loja in lojas_faltando)}."
    elif cnpjs_sem_filial:
        details = f"Arquivo x Pleno com falha. CNPJs sem filial: {', '.join(cnpjs_sem_filial)}."

    status = load_json(args.status_file)
    checked_at = result["checkedAt"]
    status["collector"] = "pedidos-monitor"
    status["updatedAt"] = checked_at
    status.setdefault("events", {})
    status["events"]["arquivo_vs_pleno"] = {
        "targetTime": "08:10",
        "status": "ok" if result["status"] == "ok" and not cnpjs_sem_filial else "erro",
        "actualAt": pleno_last_at if result["status"] == "ok" and not cnpjs_sem_filial else "",
        "checkedAt": checked_at,
        "firstPlenoAt": pleno_first_at,
        "lastPlenoAt": pleno_last_at,
        "count": len(encontrados),
        "source": f"{file_name} -> pleno.com16_pretransferencia",
        "details": details,
        "pedidosArquivo": len(pedidos_monitorados),
        "pedidosFranquiaIgnorados": len(pedidos_franquia),
        "pedidosImportados": len(encontrados),
        "lojasArquivo": len(lojas_numeros_arquivo),
        "lojasPleno": len(lojas_numeros_pleno),
        "lojasNumerosPleno": lojas_numeros_pleno,
        "pendingStores": lojas_faltando,
    }
    conclusao_details = (
        f"Pedidos importados: {len(encontrados)}/{len(pedidos_monitorados)}. "
        f"Pedidos concluidos: {len(pedidos_concluidos)}/{len(encontrados)}. "
        f"Itens confirmados: {sum(stats['confirmados'] for stats in lojas_stats.values())}/"
        f"{sum(stats['itens'] for stats in lojas_stats.values())}. "
        "Situacao concluida no Pleno: revisado e nao cancelado."
    )
    if pedidos_concluidos:
        conclusao_details += f" Concluidos: {', '.join(str(pedido) for pedido in pedidos_concluidos)}."
    if pedidos_pendentes_conclusao:
        conclusao_details += f" Pendentes: {', '.join(str(pedido) for pedido in pedidos_pendentes_conclusao)}."
    status["events"].pop("lojas_fechadas", None)
    status["events"]["pedido_concluido"] = {
        "targetTime": "09:30",
        "status": "ok" if len(pedidos_concluidos) == len(encontrados) and encontrados else "warning",
        "actualAt": checked_at if len(pedidos_concluidos) == len(encontrados) and encontrados else "",
        "count": len(pedidos_concluidos),
        "source": "pleno.com16_pretransferencia.com16_flgrevisado (nao cancelado)",
        "details": conclusao_details,
        "pedidosArquivo": len(pedidos_monitorados),
        "pedidosFranquiaIgnorados": len(pedidos_franquia),
        "pedidosImportados": len(encontrados),
        "pedidosConcluidos": len(pedidos_concluidos),
        "pedidosPendentesConclusao": pedidos_pendentes_conclusao,
        "lojasArquivo": len(lojas_numeros_arquivo),
        "lojasPleno": len(lojas_numeros_pleno),
        "lojasPedidoConcluido": len(pedidos_concluidos_lojas),
        "lojasNumerosPleno": lojas_numeros_pleno,
        "lojasNumerosPedidoConcluido": pedidos_concluidos_lojas,
        "pendingStores": [],
    }
    write_json(args.status_file, status)

    if faltando:
        print(
            f"Falha: {len(faltando)} de {len(pedidos_monitorados)} pedido(s) de lojas proprias nao encontrados no Pleno tipo {args.tipo_pedido}."
        )
        print("Faltando:", ", ".join(faltando))
        if encontrados_outro_tipo:
            print("Encontrados em outro tipo:", ", ".join(encontrados_outro_tipo))
    elif lojas_faltando:
        print(f"Falha: {len(lojas_faltando)} loja(s) do arquivo nao encontradas no Pleno.")
        print("Lojas faltando:", ", ".join(str(loja) for loja in lojas_faltando))
    elif cnpjs_sem_filial:
        print(f"Falha: {len(cnpjs_sem_filial)} CNPJ(s) do arquivo sem filial no Pleno.")
        print("CNPJs sem filial:", ", ".join(cnpjs_sem_filial))
    else:
        print(
            f"OK: todos os {len(pedidos_monitorados)} pedido(s) de lojas proprias do arquivo {file_name} estao no Pleno tipo {args.tipo_pedido}. "
            f"Pedidos concluidos: {len(pedidos_concluidos)}/{len(encontrados)}."
        )
    print(args.out_file)


if __name__ == "__main__":
    main()
