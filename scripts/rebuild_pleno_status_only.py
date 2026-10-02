#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from build_devolucao_central_db import build_pleno_status


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "outputs/devolucao_central.sqlite"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recalcula a tabela pleno_status na base central existente."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db).expanduser().resolve()
    with sqlite3.connect(db_path) as conn:
        total = build_pleno_status(conn)
        conn.commit()
    print(f"pleno_status recalculado em {db_path} com {total} linhas")


if __name__ == "__main__":
    main()
