#!/usr/bin/env python3
"""Persistencia e consulta do acompanhamento de transferencias para Cofre Inteligente."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "outputs" / "tesouraria_cofre_inteligente" / "acompanhamento.sqlite"


def db_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tesouraria_cofre_processos (
          process_key TEXT PRIMARY KEY,
          closing_date TEXT NOT NULL,
          store_code TEXT NOT NULL,
          store_name TEXT NOT NULL DEFAULT '',
          transaction_id INTEGER,
          planned_date TEXT,
          performed_date TEXT,
          value REAL,
          ocr_value REAL,
          brinks_value REAL,
          brinks_status TEXT,
          status TEXT NOT NULL,
          error_stage TEXT,
          error_message TEXT,
          pdf_file TEXT,
          evidence_file TEXT,
          pleno_file TEXT,
          brinks_file TEXT,
          receipt_dates_match INTEGER,
          receipt_value_match INTEGER,
          brinks_dates_match INTEGER,
          brinks_value_match INTEGER,
          source_signature TEXT,
          started_at TEXT,
          closed_at TEXT,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tesouraria_cofre_closing_store
          ON tesouraria_cofre_processos (closing_date, store_code);
        CREATE INDEX IF NOT EXISTS idx_tesouraria_cofre_status
          ON tesouraria_cofre_processos (closing_date, status);
        CREATE INDEX IF NOT EXISTS idx_tesouraria_cofre_planned_store
          ON tesouraria_cofre_processos (planned_date, store_code);
        CREATE TABLE IF NOT EXISTS tesouraria_cofre_snapshot (
          snapshot_date TEXT NOT NULL,
          planned_date TEXT NOT NULL,
          transaction_id INTEGER NOT NULL,
          store_code TEXT NOT NULL,
          store_name TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL,
          performed_date TEXT,
          value REAL,
          PRIMARY KEY (snapshot_date, transaction_id)
        );
        CREATE TABLE IF NOT EXISTS tesouraria_cofre_lojas (
          store_code TEXT PRIMARY KEY,
          store_name TEXT NOT NULL DEFAULT '',
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          is_active INTEGER NOT NULL DEFAULT 1
        );
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tesouraria_cofre_processos)")}
    if "brinks_status" not in columns:
        conn.execute("ALTER TABLE tesouraria_cofre_processos ADD COLUMN brinks_status TEXT")
    if "evidence_file" not in columns:
        conn.execute("ALTER TABLE tesouraria_cofre_processos ADD COLUMN evidence_file TEXT")
    if "pleno_file" not in columns:
        conn.execute("ALTER TABLE tesouraria_cofre_processos ADD COLUMN pleno_file TEXT")
    if "brinks_file" not in columns:
        conn.execute("ALTER TABLE tesouraria_cofre_processos ADD COLUMN brinks_file TEXT")
    if "source_signature" not in columns:
        conn.execute("ALTER TABLE tesouraria_cofre_processos ADD COLUMN source_signature TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tesouraria_cofre_transaction_updated "
        "ON tesouraria_cofre_processos (transaction_id, updated_at)"
    )
    store_columns = {row[1] for row in conn.execute("PRAGMA table_info(tesouraria_cofre_lojas)")}
    if "is_active" not in store_columns:
        conn.execute("ALTER TABLE tesouraria_cofre_lojas ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    return conn


def as_bool(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if bool(value) else 0


def process_key(record: dict[str, Any]) -> str:
    transaction = record.get("transactionId") or "sem-transacao"
    return f"{record['closingDate']}:{record['storeCode']}:{transaction}"


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    required = ("closingDate", "storeCode", "status")
    missing = [key for key in required if not record.get(key)]
    if missing:
        raise ValueError(f"Campos obrigatorios ausentes: {', '.join(missing)}")
    validation = record.get("validation") or {}
    now = datetime.now(timezone.utc).isoformat()
    return {
        "process_key": process_key(record),
        "closing_date": record["closingDate"],
        "store_code": str(record["storeCode"]),
        "store_name": record.get("storeName") or "",
        "transaction_id": record.get("transactionId"),
        "planned_date": record.get("plannedDate"),
        "performed_date": record.get("performedDate"),
        "value": record.get("value"),
        "ocr_value": record.get("ocrValue"),
        "brinks_value": record.get("brinksValue"),
        "brinks_status": record.get("brinksStatus"),
        "status": record["status"],
        "error_stage": record.get("errorStage"),
        "error_message": record.get("errorMessage"),
        "pdf_file": record.get("pdfFile"),
        "evidence_file": record.get("evidenceFile"),
        "pleno_file": record.get("plenoFile"),
        "brinks_file": record.get("brinksFile"),
        "receipt_dates_match": as_bool(validation.get("receiptDatesMatch")),
        "receipt_value_match": as_bool(validation.get("receiptValueMatch")),
        "brinks_dates_match": as_bool(validation.get("brinksDatesMatch")),
        "brinks_value_match": as_bool(validation.get("brinksValueMatch")),
        "source_signature": record.get("sourceSignature"),
        "started_at": record.get("startedAt"),
        "closed_at": record.get("closedAt"),
        "updated_at": now,
    }


def upsert(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    row = normalize_record(record)
    columns = list(row)
    placeholders = ", ".join(f":{column}" for column in columns)
    updates = ", ".join(f"{column}=excluded.{column}" for column in columns if column != "process_key")
    conn.execute(
        f"INSERT INTO tesouraria_cofre_processos ({', '.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT(process_key) DO UPDATE SET {updates}",
        row,
    )
    if row["status"] == "concluido":
        conn.execute(
            "DELETE FROM tesouraria_cofre_processos "
            "WHERE closing_date = ? AND store_code = ? AND planned_date = ? "
            "AND transaction_id IS NULL AND status = 'erro'",
            (row["closing_date"], row["store_code"], row["planned_date"]),
        )
    conn.commit()


def summary(conn: sqlite3.Connection, start_date: str, end_date: str, store: str, pending_only: bool, status_filter: str) -> dict[str, Any]:
    where = "planned_date BETWEEN ? AND ?"
    params: list[Any] = [start_date, end_date]
    if store != "all":
        where += " AND store_code = ?"
        params.append(store)
    process_rows = [dict(row) for row in conn.execute(
        f"SELECT * FROM tesouraria_cofre_processos WHERE {where} ORDER BY store_code, transaction_id", params
    )]
    stores_by_code = {
        str(row["store_code"]): {"code": str(row["store_code"]), "name": row["store_name"] or ""}
        for row in conn.execute("SELECT store_code, store_name FROM tesouraria_cofre_lojas WHERE is_active = 1")
    }
    for row in process_rows:
        stores_by_code.setdefault(str(row["store_code"]), {"code": str(row["store_code"]), "name": row["store_name"] or ""})
    snapshots: dict[str, dict[str, Any]] = {}
    for row in conn.execute(
        "SELECT store_code, store_name, status, planned_date, performed_date, value FROM tesouraria_cofre_snapshot "
        "WHERE planned_date BETWEEN ? AND ? ORDER BY planned_date DESC",
        (start_date, end_date),
    ):
        # Mantem o snapshot mais recente de cada loja no periodo.
        snapshots.setdefault(str(row["store_code"]), dict(row))
    processed_stores = {str(row["store_code"]) for row in process_rows}
    virtual_rows: list[dict[str, Any]] = []
    for store_code, store_info in stores_by_code.items():
        if store != "all" and store_code != store:
            continue
        if store_code in processed_stores:
            continue
        snapshot = snapshots.get(store_code)
        pleno_status = str(snapshot["status"] or "").upper() if snapshot else ""
        is_open = pleno_status in {"VENCIDO", "EM ABERTO"}
        is_liquidated = pleno_status in {"LIQUIDADO", "CONCLUIDO", "CONCLUÍDO"}
        virtual_rows.append({
            "transaction_id": None,
            "store_code": store_code,
            "store_name": store_info["name"] or (snapshot["store_name"] if snapshot else ""),
            "planned_date": snapshot["planned_date"] if snapshot else end_date,
            "performed_date": snapshot["performed_date"] if snapshot else None,
            "closing_date": None,
            "closed_at": None,
            "started_at": None,
            "value": snapshot["value"] if snapshot else 0,
            "ocr_value": None,
            "brinks_value": None,
            "status": "em_aberto" if is_open else "ja_liquidada" if is_liquidated else "sem_transferencia",
            "error_stage": None,
            "brinks_status": None,
            "error_message": None,
            "pdf_file": None,
            "evidence_file": None,
            "pleno_file": None,
            "brinks_file": None,
            "receipt_dates_match": None,
            "receipt_value_match": None,
            "brinks_dates_match": None,
            "brinks_value_match": None,
        })
    rows = process_rows + virtual_rows
    if pending_only:
        rows = [row for row in rows if row["status"] not in {"concluido", "ja_liquidada", "cancelado_duplicidade"}]
    if status_filter != "all":
        rows = [row for row in rows if row["status"] == status_filter]
    rows.sort(key=lambda row: (int(row["store_code"]) if str(row["store_code"]).isdigit() else 999999, str(row["store_code"]), row["transaction_id"] or 0))
    stores = sorted(stores_by_code.values(), key=lambda row: (int(row["code"]) if row["code"].isdigit() else 999999, row["code"]))
    records = [
        {
            "transactionId": row["transaction_id"], "storeCode": row["store_code"], "storeName": row["store_name"],
            "plannedDate": row["planned_date"], "performedDate": row["performed_date"], "closingDate": row["closing_date"],
            "closedAt": row["closed_at"], "startedAt": row["started_at"], "value": row["value"], "ocrValue": row["ocr_value"],
            "brinksValue": row["brinks_value"], "status": row["status"], "errorStage": row["error_stage"],
            "brinksStatus": row["brinks_status"],
            "errorMessage": row["error_message"], "pdfFile": row["pdf_file"], "evidenceFile": row["evidence_file"],
            "plenoFile": row["pleno_file"], "brinksFile": row["brinks_file"],
            "validation": {
                "receiptDatesMatch": bool(row["receipt_dates_match"]) if row["receipt_dates_match"] is not None else None,
                "receiptValueMatch": bool(row["receipt_value_match"]) if row["receipt_value_match"] is not None else None,
                "brinksDatesMatch": bool(row["brinks_dates_match"]) if row["brinks_dates_match"] is not None else None,
                "brinksValueMatch": bool(row["brinks_value_match"]) if row["brinks_value_match"] is not None else None,
            },
        }
        for row in rows
    ]
    return {
        "plannedDate": end_date, "startDate": start_date, "endDate": end_date,
        "store": store,
        "stores": stores,
        "records": records,
        "totals": {
            "processed": len(records),
            "approved": sum(record["status"] in {"concluido", "cancelado_duplicidade"} for record in records),
            "pending": sum(record["status"] in {"pendente", "em_aberto", "sem_transferencia"} for record in records),
            "errors": sum(record["status"] == "erro" for record in records),
            "duplicates": sum(record["status"] == "duplicado" for record in records),
            "attention": sum(record["status"] not in {"concluido", "cancelado_duplicidade"} for record in records),
            "totalValue": sum(float(record["value"] or 0) for record in records if record["status"] == "concluido"),
        },
    }


def analytics(conn: sqlite3.Connection, start_date: str, end_date: str) -> dict[str, Any]:
    stores: dict[str, dict[str, Any]] = {}

    def store(code: str, name: str = "") -> dict[str, Any]:
        item = stores.setdefault(code, {"storeCode": code, "storeName": name, "openTransfers": 0, "failures": 0, "ocrFailures": 0, "duplicates": 0, "offlineBrinks": 0, "completed": 0, "hasTransfer": False, "plenoStatus": ""})
        if name:
            item["storeName"] = name
        return item

    for row in conn.execute("SELECT store_code, store_name FROM tesouraria_cofre_lojas WHERE is_active = 1 ORDER BY store_code"):
        store(row[0], row[1])
    for row in conn.execute("SELECT store_code, store_name, status FROM tesouraria_cofre_snapshot WHERE planned_date BETWEEN ? AND ?", (start_date, end_date)):
        item = store(row[0], row[1])
        item["hasTransfer"] = True
        item["plenoStatus"] = str(row[2] or "")
        if str(row[2]).upper() in {"VENCIDO", "EM ABERTO"}:
            item["openTransfers"] += 1
    for row in conn.execute("SELECT store_code, store_name, status, error_message, brinks_status FROM tesouraria_cofre_processos WHERE planned_date BETWEEN ? AND ?", (start_date, end_date)):
        item = store(row[0], row[1])
        item["hasTransfer"] = True
        status = row[2]
        message = (row[3] or "").lower()
        brinks_status = (row[4] or "").upper()
        if status in {"concluido", "cancelado_duplicidade"}:
            item["completed"] += 1
        elif status == "duplicado":
            item["duplicates"] += 1
        elif status == "erro":
            item["failures"] += 1
            if "ocr" in message or "comprovante" in message:
                item["ocrFailures"] += 1
        if brinks_status in {"OFFLINE", "SEM COMUNICAÇÃO"}:
            item["offlineBrinks"] += 1
    for item in stores.values():
        if not item["hasTransfer"]:
            item["dailyStatus"] = "Sem transferência"
        elif item["openTransfers"]:
            item["dailyStatus"] = "Em aberto"
        elif item["failures"]:
            item["dailyStatus"] = "Falha"
        elif item["duplicates"]:
            item["dailyStatus"] = "Duplicada"
        elif item["completed"]:
            item["dailyStatus"] = "Concluída"
        else:
            item["dailyStatus"] = "Já liquidada"
    ordered = sorted(stores.values(), key=lambda item: (-item["failures"], -item["openTransfers"], int(item["storeCode"]) if item["storeCode"].isdigit() else 999999, item["storeCode"]))
    return {"plannedDate": end_date, "startDate": start_date, "endDate": end_date, "stores": ordered, "totals": {"stores": len(ordered), "openTransfers": sum(item["openTransfers"] for item in ordered), "failures": sum(item["failures"] for item in ordered), "ocrFailures": sum(item["ocrFailures"] for item in ordered), "duplicates": sum(item["duplicates"] for item in ordered), "offlineBrinks": sum(item["offlineBrinks"] for item in ordered)}}


def problem_ranking(conn: sqlite3.Connection, dates: list[str]) -> dict[str, Any]:
    if not dates:
        return {"periodDates": [], "topFailures": None, "topPhotoErrors": None, "topTypingErrors": None}
    marks = ", ".join("?" for _ in dates)
    stores: dict[str, dict[str, Any]] = {}
    rows = conn.execute(
        f"SELECT store_code, store_name, error_message FROM tesouraria_cofre_processos "
        f"WHERE planned_date IN ({marks}) AND status = 'erro'",
        dates,
    )
    for row in rows:
        code, name, message = row[0], row[1], (row[2] or "").lower()
        item = stores.setdefault(code, {"storeCode": code, "storeName": name, "failures": 0, "photoErrors": 0, "typingErrors": 0})
        item["failures"] += 1
        if "ocr" in message or "comprovante" in message or "foto" in message or "imagem" in message:
            item["photoErrors"] += 1
        elif any(term in message for term in ("digita", "preench", "data brinks", "data pleno", "data nao", "valor nao")):
            item["typingErrors"] += 1

    def top(field: str) -> dict[str, Any] | None:
        candidates = [item for item in stores.values() if item[field] > 0]
        return max(candidates, key=lambda item: (item[field], item["failures"], -int(item["storeCode"]) if str(item["storeCode"]).isdigit() else 0)) if candidates else None

    return {
        "periodDates": dates,
        "topFailures": top("failures"),
        "topPhotoErrors": top("photoErrors"),
        "topTypingErrors": top("typingErrors"),
    }


def existing_concluded(conn: sqlite3.Connection, store_code: str, planned_date: str, exclude_transaction_id: int | None) -> dict[str, Any]:
    row = conn.execute(
        "SELECT transaction_id FROM tesouraria_cofre_processos "
        "WHERE store_code = ? AND planned_date = ? AND status = 'concluido' "
        "AND (? IS NULL OR transaction_id <> ?) ORDER BY closed_at DESC LIMIT 1",
        (store_code, planned_date, exclude_transaction_id, exclude_transaction_id),
    ).fetchone()
    return {"exists": row is not None, "transactionId": row["transaction_id"] if row else None}


def handled_transaction_ids(conn: sqlite3.Connection) -> list[int]:
    """IDs que nao devem ser tentados novamente automaticamente no mesmo ciclo."""
    return [
        int(row["transaction_id"])
        for row in conn.execute(
            "SELECT DISTINCT transaction_id FROM tesouraria_cofre_processos "
            "WHERE transaction_id IS NOT NULL AND status IN ('erro', 'duplicado', 'concluido', 'cancelado_duplicidade')"
        )
    ]


def failed_transaction_ids(conn: sqlite3.Connection) -> list[int]:
    """IDs que podem entrar somente em uma execução manual de reprocessamento."""
    return [
        int(row["transaction_id"])
        for row in conn.execute(
            "SELECT DISTINCT transaction_id FROM tesouraria_cofre_processos "
            "WHERE transaction_id IS NOT NULL AND status = 'erro'"
        )
    ]


def unchanged_failed_transaction_ids(conn: sqlite3.Connection, candidates: list[dict[str, Any]], max_age_hours: float) -> list[int]:
    """Falhas cuja ultima tentativa corresponde exatamente ao registro atual do Pleno."""
    current = {
        int(item["id"]): str(item.get("sourceSignature") or "")
        for item in candidates
        if item.get("id") and item.get("sourceSignature")
    }
    if not current:
        return []
    marks = ", ".join("?" for _ in current)
    rows = conn.execute(
        f"SELECT current.transaction_id, current.source_signature, current.updated_at "
        f"FROM tesouraria_cofre_processos AS current "
        f"JOIN ("
        f"  SELECT transaction_id, MAX(updated_at) AS updated_at "
        f"  FROM tesouraria_cofre_processos "
        f"  WHERE transaction_id IN ({marks}) "
        f"  GROUP BY transaction_id"
        f") AS latest ON latest.transaction_id = current.transaction_id AND latest.updated_at = current.updated_at "
        f"WHERE current.status = 'erro'",
        list(current),
    ).fetchall()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(0, max_age_hours))
    unchanged: list[int] = []
    for row in rows:
        if not row["source_signature"] or row["source_signature"] != current[int(row["transaction_id"])]:
            continue
        try:
            updated_at = datetime.fromisoformat(row["updated_at"]).astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        if updated_at >= cutoff:
            unchanged.append(int(row["transaction_id"]))
    return unchanged


def recent_processes(conn: sqlite3.Connection, limit: int, closing_date: str | None) -> list[dict[str, Any]]:
    where = "WHERE closing_date = ?" if closing_date else ""
    params: tuple[Any, ...] = (closing_date, limit) if closing_date else (limit,)
    rows = conn.execute(
        f"SELECT store_code, store_name, transaction_id, planned_date, performed_date, closing_date, closed_at, started_at, "
        f"value, ocr_value, brinks_value, brinks_status, status, error_stage, error_message, pdf_file, evidence_file, pleno_file, brinks_file, "
        f"receipt_dates_match, receipt_value_match, brinks_dates_match, brinks_value_match, updated_at "
        f"FROM tesouraria_cofre_processos {where} ORDER BY updated_at DESC LIMIT ?", params,
    ).fetchall()
    return [dict(row) for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("record")
    migrate = subparsers.add_parser("migrate-json")
    migrate.add_argument("--input", type=Path, required=True)
    status = subparsers.add_parser("summary")
    status.add_argument("--planned-date")
    status.add_argument("--start-date")
    status.add_argument("--end-date")
    status.add_argument("--store", default="all")
    status.add_argument("--only-pending", action="store_true")
    status.add_argument("--status", default="all", choices=("all", "pendente", "em_aberto", "sem_transferencia", "erro", "duplicado", "concluido", "cancelado_duplicidade", "ja_liquidada"))
    duplicate = subparsers.add_parser("existing-concluded")
    duplicate.add_argument("--store-code", required=True)
    duplicate.add_argument("--planned-date", required=True)
    duplicate.add_argument("--exclude-transaction-id", type=int)
    subparsers.add_parser("handled-transaction-ids")
    subparsers.add_parser("failed-transaction-ids")
    unchanged = subparsers.add_parser("unchanged-failed-transaction-ids")
    unchanged.add_argument("--max-age-hours", type=float, default=24)
    recent = subparsers.add_parser("recent-processes")
    recent.add_argument("--limit", type=int, default=12)
    recent.add_argument("--closing-date")
    analytics_parser = subparsers.add_parser("analytics")
    analytics_parser.add_argument("--planned-date")
    analytics_parser.add_argument("--start-date")
    analytics_parser.add_argument("--end-date")
    ranking_parser = subparsers.add_parser("problem-ranking")
    ranking_parser.add_argument("--dates", required=True)
    args = parser.parse_args()
    conn = db_connection(args.db)
    try:
        if args.command == "record":
            upsert(conn, json.load(sys.stdin))
        elif args.command == "migrate-json":
            for record in json.loads(args.input.read_text(encoding="utf-8")):
                upsert(conn, record)
        elif args.command == "summary":
            start = args.start_date or args.planned_date
            end = args.end_date or args.planned_date
            print(json.dumps(summary(conn, start, end, args.store, args.only_pending, args.status), ensure_ascii=False))
        elif args.command == "analytics":
            start = args.start_date or args.planned_date
            end = args.end_date or args.planned_date
            print(json.dumps(analytics(conn, start, end), ensure_ascii=False))
        elif args.command == "problem-ranking":
            print(json.dumps(problem_ranking(conn, [day for day in args.dates.split(",") if day]), ensure_ascii=False))
        elif args.command == "handled-transaction-ids":
            print(json.dumps(handled_transaction_ids(conn)))
        elif args.command == "failed-transaction-ids":
            print(json.dumps(failed_transaction_ids(conn)))
        elif args.command == "unchanged-failed-transaction-ids":
            print(json.dumps(unchanged_failed_transaction_ids(conn, json.load(sys.stdin), args.max_age_hours)))
        elif args.command == "recent-processes":
            print(json.dumps(recent_processes(conn, args.limit, args.closing_date), ensure_ascii=False))
        else:
            print(json.dumps(existing_concluded(conn, args.store_code, args.planned_date, args.exclude_transaction_id), ensure_ascii=False))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
