#!/usr/bin/env python3
"""Consulta o Pleno para snapshots diarios e duplicidades de Cofre Inteligente."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / ".python_packages"
if str(PACKAGES) not in sys.path:
    sys.path.insert(0, str(PACKAGES))

import pymysql

DEFAULT_DB = ROOT / "outputs" / "tesouraria_cofre_inteligente" / "acompanhamento.sqlite"


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip("\"'")
    return values


def pleno_connection() -> pymysql.connections.Connection:
    env = load_env()
    return pymysql.connect(
        host=env["MYSQL_HOST"], port=int(env.get("MYSQL_PORT", "3306")),
        user=env["MYSQL_USER"], password=env["MYSQL_PASSWORD"],
        database=env.get("MYSQL_DATABASE", "pleno"), charset="latin1", connect_timeout=15,
    )


BASE_SQL = """
WITH transacoes_elegiveis AS (
    SELECT t.fin07_id
      FROM fin07_transacao t
      JOIN fin11_categoria categoria ON categoria.fin11_id = t.fin11_categoria_id
     WHERE TRIM(t.fin07_descricao) = _latin1'DEPOSITO COFRE INTELIGENTE'
       AND categoria.fin11_codigo = _latin1'03.01'
), lancamentos AS (
    SELECT l.fin07_transacao_id,
           MAX(CASE WHEN conta.fin03_nome = _latin1'COFRE INTELIGENTE' THEN filial.cfg06_numero END) AS loja_codigo,
           MAX(CASE WHEN conta.fin03_nome = _latin1'COFRE INTELIGENTE' THEN filial.cfg06_nome END) AS loja_nome,
           SUM(CASE WHEN conta.fin03_nome = _latin1'CAIXA GERAL' THEN l.fin08_valor ELSE 0 END) AS valor_caixa,
           SUM(CASE WHEN conta.fin03_nome = _latin1'COFRE INTELIGENTE' THEN l.fin08_valor ELSE 0 END) AS valor_cofre,
           MAX(CASE WHEN conta.fin03_nome = _latin1'CAIXA GERAL' THEN conta.fin03_nome END) AS conta_origem,
           MAX(CASE WHEN conta.fin03_nome = _latin1'COFRE INTELIGENTE' THEN conta.fin03_nome END) AS conta_destino
      FROM fin08_transacao_lancamento l
      JOIN transacoes_elegiveis elegiveis ON elegiveis.fin07_id = l.fin07_transacao_id
      JOIN fin03_conta conta ON conta.fin03_id = l.fin03_conta_id
 LEFT JOIN cfg06_filial filial ON filial.cfg06_id = conta.cfg06_filial_id
     WHERE conta.fin03_nome IN (_latin1'CAIXA GERAL', _latin1'COFRE INTELIGENTE')
     GROUP BY l.fin07_transacao_id
)
SELECT t.fin07_id, l.loja_codigo, l.loja_nome, st.dom22_descricao,
       t.fin07_data_vencto_programada, t.fin07_data_vencto_realizada, t.fin07_valor
  FROM fin07_transacao t
  JOIN fin11_categoria categoria ON categoria.fin11_id = t.fin11_categoria_id
  JOIN dom22_situacao_trans_financeira st ON st.dom22_id = t.dom22_situacao_trans_financeira_id
  JOIN lancamentos l ON l.fin07_transacao_id = t.fin07_id
 WHERE TRIM(t.fin07_descricao) = _latin1'DEPOSITO COFRE INTELIGENTE'
   AND categoria.fin11_codigo = _latin1'03.01'
   AND l.conta_origem = _latin1'CAIXA GERAL'
   AND l.conta_destino = _latin1'COFRE INTELIGENTE'
   AND l.valor_caixa = l.valor_cofre
"""


def sqlite_connection(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript("""
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
        CREATE INDEX IF NOT EXISTS idx_tesouraria_snapshot_planned_store
        ON tesouraria_cofre_snapshot (planned_date, store_code);
      CREATE INDEX IF NOT EXISTS idx_tesouraria_snapshot_key_planned
        ON tesouraria_cofre_snapshot (snapshot_date, planned_date);
    """)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tesouraria_cofre_lojas)")}
    if "is_active" not in columns:
        conn.execute("ALTER TABLE tesouraria_cofre_lojas ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    return conn


def sync_stores(local: sqlite3.Connection, snapshot_date: str) -> None:
    """Mantem o cadastro de filiais ativas independente de haver transferencia."""
    with pleno_connection() as pleno, pleno.cursor() as cursor:
        cursor.execute("SET NAMES latin1")
        cursor.execute(
            "SELECT cfg06_numero, cfg06_nome FROM cfg06_filial "
            "WHERE cfg06_situacao = _latin1'A' AND cfg06_numero > 1 ORDER BY cfg06_numero"
        )
        stores = cursor.fetchall()
    local.execute("UPDATE tesouraria_cofre_lojas SET is_active = 0")
    for store_code, store_name in stores:
        local.execute(
            "INSERT INTO tesouraria_cofre_lojas (store_code, store_name, first_seen_at, last_seen_at, is_active) "
            "VALUES (?, ?, ?, ?, 1) "
            "ON CONFLICT(store_code) DO UPDATE SET store_name=excluded.store_name, last_seen_at=excluded.last_seen_at, is_active=1",
            (str(store_code), store_name or "", snapshot_date, snapshot_date),
        )


def snapshot(db: Path, planned_date: str, snapshot_date: str) -> int:
    sql = BASE_SQL + " AND t.fin07_data_vencto_programada = %s"
    with pleno_connection() as pleno, pleno.cursor() as cursor:
        cursor.execute("SET NAMES latin1")
        cursor.execute(sql, (planned_date,))
        rows = cursor.fetchall()
    with sqlite_connection(db) as local:
        sync_stores(local, snapshot_date)
        for transaction_id, store_code, store_name, status, planned, performed, value in rows:
            if not store_code:
                continue
            local.execute(
                "INSERT INTO tesouraria_cofre_snapshot VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(snapshot_date, transaction_id) DO UPDATE SET status=excluded.status, performed_date=excluded.performed_date, value=excluded.value, store_name=excluded.store_name",
                (snapshot_date, str(planned), int(transaction_id), str(store_code), store_name or "", status or "", str(performed) if performed else None, float(value or 0)),
            )
            local.execute(
                "INSERT INTO tesouraria_cofre_lojas (store_code, store_name, first_seen_at, last_seen_at, is_active) VALUES (?, ?, ?, ?, 1) "
                "ON CONFLICT(store_code) DO UPDATE SET store_name=excluded.store_name, last_seen_at=excluded.last_seen_at, is_active=1",
                (str(store_code), store_name or "", snapshot_date, snapshot_date),
            )
    return len(rows)


def open_dates(start_date: str | None = None, end_date: str | None = None) -> list[dict[str, object]]:
    sql = BASE_SQL + " AND st.dom22_descricao IN (_latin1'VENCIDO', _latin1'EM ABERTO')"
    params: list[object] = []
    if start_date:
        sql += " AND t.fin07_data_vencto_programada >= %s"
        params.append(start_date)
    if end_date:
        sql += " AND t.fin07_data_vencto_programada <= %s"
        params.append(end_date)
    with pleno_connection() as pleno, pleno.cursor() as cursor:
        cursor.execute("SET NAMES latin1")
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    grouped: dict[str, dict[str, object]] = {}
    for _, store_code, _, _, planned, _, _ in rows:
        if not planned or not store_code:
            continue
        day = str(planned)
        item = grouped.setdefault(day, {"plannedDate": day, "openTransfers": 0, "openStores": set()})
        item["openTransfers"] = int(item["openTransfers"]) + 1
        item["openStores"].add(str(store_code))
    return [
        {"plannedDate": day, "openTransfers": item["openTransfers"], "openStores": len(item["openStores"])}
        for day, item in sorted(grouped.items())
    ]


OPEN_TRANSFERS_SNAPSHOT = "__open_transfers__"


def transfer_records(rows: list[tuple[object, ...]]) -> list[dict[str, object]]:
    return [
        {
            "id": int(transaction_id),
            "store": f"{store_code} - {store_name or ''}".strip(),
            "origin": "CAIXA GERAL",
            "destination": "COFRE INTELIGENTE",
            "value": float(value or 0),
            "planned": planned.strftime("%d/%m/%Y") if hasattr(planned, "strftime") else str(planned),
            "performed": performed.strftime("%d/%m/%Y") if hasattr(performed, "strftime") else (str(performed) if performed else ""),
            "status": str(status or "").upper(),
        }
        for transaction_id, store_code, store_name, status, planned, performed, value in rows
        if transaction_id and store_code and planned
    ]


def fetch_open_transfer_rows() -> list[tuple[object, ...]]:
    """Consulta remota usada somente pelo robô no início de cada rodada."""
    sql = BASE_SQL + " AND st.dom22_descricao IN (_latin1'VENCIDO', _latin1'EM ABERTO')"
    with pleno_connection() as pleno, pleno.cursor() as cursor:
        cursor.execute("SET NAMES latin1")
        cursor.execute(sql)
        return cursor.fetchall()


def refresh_open_transfers(db: Path) -> list[dict[str, object]]:
    """Atualiza a fila local; esta é a única leitura geral do Pleno por rodada."""
    rows = fetch_open_transfer_rows()
    with sqlite_connection(db) as local:
        local.execute("DELETE FROM tesouraria_cofre_snapshot WHERE snapshot_date = ?", (OPEN_TRANSFERS_SNAPSHOT,))
        for transaction_id, store_code, store_name, status, planned, performed, value in rows:
            if transaction_id and store_code and planned:
                local.execute(
                    "INSERT INTO tesouraria_cofre_snapshot VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (OPEN_TRANSFERS_SNAPSHOT, str(planned), int(transaction_id), str(store_code), store_name or "", status or "", str(performed) if performed else None, float(value or 0)),
                )
    return transfer_records(rows)


def cached_open_transfers(db: Path) -> list[dict[str, object]]:
    """Fila para o painel: somente SQLite, sem nova consulta ao Pleno."""
    with sqlite_connection(db) as local:
        rows = local.execute(
            "SELECT transaction_id, store_code, store_name, status, planned_date, performed_date, value "
            "FROM tesouraria_cofre_snapshot WHERE snapshot_date = ? ORDER BY planned_date, store_code",
            (OPEN_TRANSFERS_SNAPSHOT,),
        ).fetchall()
    return transfer_records(rows)


def cached_open_dates(db: Path, start_date: str | None, end_date: str | None) -> list[dict[str, object]]:
    sql = (
        "SELECT planned_date, COUNT(*), COUNT(DISTINCT store_code) FROM tesouraria_cofre_snapshot "
        "WHERE snapshot_date = ?"
    )
    params: list[object] = [OPEN_TRANSFERS_SNAPSHOT]
    if start_date:
        sql += " AND planned_date >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND planned_date <= ?"
        params.append(end_date)
    sql += " GROUP BY planned_date ORDER BY planned_date"
    with sqlite_connection(db) as local:
        rows = local.execute(sql, params).fetchall()
    return [{"plannedDate": day, "openTransfers": total, "openStores": stores} for day, total, stores in rows]


def duplicate(store_code: str, planned_date: str, exclude_transaction_id: int | None) -> dict[str, object]:
    """Retorna outro fechamento já liquidado para a mesma loja e data prevista."""
    sql = BASE_SQL + " AND l.loja_codigo = %s AND t.fin07_data_vencto_programada = %s"
    params: list[object] = [store_code, planned_date]
    if exclude_transaction_id:
        sql += " AND t.fin07_id <> %s"
        params.append(exclude_transaction_id)
    # A existência de outra transferência aberta não impede a primeira de ser tratada.
    # O bloqueio só ocorre quando há outra já liquidada.
    sql += " AND t.fin07_data_vencto_realizada IS NOT NULL ORDER BY t.fin07_id DESC LIMIT 1"
    with pleno_connection() as pleno, pleno.cursor() as cursor:
        cursor.execute("SET NAMES latin1")
        cursor.execute(sql, params)
        row = cursor.fetchone()
    return {"exists": row is not None, "transactionId": int(row[0]) if row else None}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    commands = parser.add_subparsers(dest="command", required=True)
    take_snapshot = commands.add_parser("snapshot")
    take_snapshot.add_argument("--planned-date", required=True)
    take_snapshot.add_argument("--snapshot-date", default=date.today().isoformat())
    check_duplicate = commands.add_parser("duplicate")
    check_duplicate.add_argument("--store-code", required=True)
    check_duplicate.add_argument("--planned-date", required=True)
    check_duplicate.add_argument("--exclude-transaction-id", type=int)
    open_dates_parser = commands.add_parser("open-dates")
    open_dates_parser.add_argument("--start-date")
    open_dates_parser.add_argument("--end-date")
    commands.add_parser("refresh-open-transfers")
    commands.add_parser("cached-open-transfers")
    cached_dates_parser = commands.add_parser("cached-open-dates")
    cached_dates_parser.add_argument("--start-date")
    cached_dates_parser.add_argument("--end-date")
    args = parser.parse_args()
    if args.command == "snapshot":
        print(snapshot(args.db, args.planned_date, args.snapshot_date))
    elif args.command == "duplicate":
        import json
        print(json.dumps(duplicate(args.store_code, args.planned_date, args.exclude_transaction_id)))
    elif args.command == "refresh-open-transfers":
        import json
        print(json.dumps(refresh_open_transfers(args.db), ensure_ascii=False, default=str))
    elif args.command == "cached-open-transfers":
        import json
        print(json.dumps(cached_open_transfers(args.db), ensure_ascii=False, default=str))
    elif args.command == "cached-open-dates":
        import json
        print(json.dumps(cached_open_dates(args.db, args.start_date, args.end_date), ensure_ascii=False, default=str))
    else:
        import json
        print(json.dumps(open_dates(args.start_date, args.end_date)))


if __name__ == "__main__":
    main()
