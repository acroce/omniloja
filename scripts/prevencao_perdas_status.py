#!/usr/bin/env python3
"""Persistencia do acompanhamento do robo de prevencao e perdas no Pleno."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "outputs" / "prevencao_perdas" / "acompanhamento.sqlite"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS prevencao_perdas_notas (
          process_key TEXT PRIMARY KEY,
          run_date TEXT NOT NULL,
          retificacao_id TEXT,
          nota_id TEXT,
          filial TEXT,
          nro_nf TEXT,
          data_nf TEXT,
          mercadoria TEXT,
          albaran TEXT,
          data_albaran TEXT,
          tipo_operacao TEXT,
          situacao_inicial TEXT,
          situacao_final TEXT,
          status TEXT NOT NULL,
          message TEXT,
          error_stage TEXT,
          screenshot_file TEXT,
          started_at TEXT,
          finished_at TEXT,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_prevencao_perdas_status
          ON prevencao_perdas_notas (run_date, status);
        CREATE INDEX IF NOT EXISTS idx_prevencao_perdas_filial
          ON prevencao_perdas_notas (run_date, filial);
        """
    )
    return conn


def key(record: dict[str, Any]) -> str:
    if record.get("processKey"):
        return f"{record['runDate']}:{record['processKey']}"
    identifier = record.get("retificacaoId") or record.get("notaId") or record.get("albaran") or record.get("nroNf")
    return f"{record['runDate']}:{identifier or datetime.now(timezone.utc).timestamp()}"


def normalize(record: dict[str, Any]) -> dict[str, Any]:
    if not record.get("runDate") or not record.get("status"):
        raise ValueError("runDate e status sao obrigatorios.")
    now = datetime.now(timezone.utc).isoformat()
    return {
        "process_key": key(record),
        "run_date": record["runDate"],
        "retificacao_id": record.get("retificacaoId"),
        "nota_id": record.get("notaId"),
        "filial": record.get("filial"),
        "nro_nf": record.get("nroNf"),
        "data_nf": record.get("dataNf"),
        "mercadoria": record.get("mercadoria"),
        "albaran": record.get("albaran"),
        "data_albaran": record.get("dataAlbaran"),
        "tipo_operacao": record.get("tipoOperacao"),
        "situacao_inicial": record.get("situacaoInicial"),
        "situacao_final": record.get("situacaoFinal"),
        "status": record["status"],
        "message": record.get("message"),
        "error_stage": record.get("errorStage"),
        "screenshot_file": record.get("screenshotFile"),
        "started_at": record.get("startedAt"),
        "finished_at": record.get("finishedAt"),
        "updated_at": now,
    }


def record(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    row = normalize(payload)
    cols = list(row)
    placeholders = ", ".join(f":{col}" for col in cols)
    updates = ", ".join(f"{col}=excluded.{col}" for col in cols if col != "process_key")
    conn.execute(
        f"INSERT INTO prevencao_perdas_notas ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(process_key) DO UPDATE SET {updates}",
        row,
    )
    conn.commit()


def recent(conn: sqlite3.Connection, run_date: str | None, limit: int) -> list[dict[str, Any]]:
    where = "WHERE run_date = ?" if run_date else ""
    params: tuple[Any, ...] = (run_date, limit) if run_date else (limit,)
    rows = conn.execute(
        f"SELECT * FROM prevencao_perdas_notas {where} ORDER BY updated_at DESC LIMIT ?",
        params,
    )
    return [dict(row) for row in rows]


def handled_ids(conn: sqlite3.Connection, run_date: str | None = None) -> list[str]:
    where = " AND run_date = ?" if run_date else ""
    params: tuple[Any, ...] = (run_date,) if run_date else ()
    rows = conn.execute(
        "SELECT DISTINCT COALESCE(retificacao_id, nota_id, albaran, nro_nf) AS id "
        f"FROM prevencao_perdas_notas WHERE status IN ('concluido', 'erro') AND id IS NOT NULL{where}",
        params,
    )
    return [str(row["id"]) for row in rows]


def summary(conn: sqlite3.Connection, run_date: str | None, status: str, filial: str) -> dict[str, Any]:
    clauses: list[str] = []
    params: list[Any] = []
    if run_date:
        clauses.append("run_date = ?")
        params.append(run_date)
    if status != "all":
        clauses.append("status = ?")
        params.append(status)
    if filial != "all":
        clauses.append("filial LIKE ?")
        params.append(f"{filial}%")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = [dict(row) for row in conn.execute(f"SELECT * FROM prevencao_perdas_notas {where} ORDER BY updated_at DESC", params)]
    filiais = sorted({row["filial"] for row in rows if row.get("filial")})
    return {
        "records": rows,
        "filiais": filiais,
        "totals": {
            "processed": len(rows),
            "completed": sum(row["status"] == "concluido" for row in rows),
            "errors": sum(row["status"] == "erro" for row in rows),
            "pending": sum(row["status"] in {"pendente", "em_processamento", "pendente_reconsulta", "pendente_revalidacao_pleno"} for row in rows),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("record")
    recent_parser = sub.add_parser("recent")
    recent_parser.add_argument("--run-date")
    recent_parser.add_argument("--limit", type=int, default=200)
    summary_parser = sub.add_parser("summary")
    summary_parser.add_argument("--run-date")
    summary_parser.add_argument("--status", default="all")
    summary_parser.add_argument("--filial", default="all")
    handled_parser = sub.add_parser("handled-ids")
    handled_parser.add_argument("--run-date")
    args = parser.parse_args()
    conn = connect(args.db)
    try:
        if args.command == "record":
            record(conn, json.load(sys.stdin))
        elif args.command == "recent":
            print(json.dumps(recent(conn, args.run_date, args.limit), ensure_ascii=False))
        elif args.command == "summary":
            print(json.dumps(summary(conn, args.run_date, args.status, args.filial), ensure_ascii=False))
        else:
            print(json.dumps(handled_ids(conn, args.run_date), ensure_ascii=False))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
