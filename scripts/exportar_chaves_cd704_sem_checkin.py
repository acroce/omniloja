#!/usr/bin/env python3
from __future__ import annotations

import csv
import os
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".python_packages"))

OUT_DIR = ROOT / "outputs" / "pleno_chaves_cd704_sem_checkin"


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


def main() -> None:
    env = load_env_file(ROOT / ".env")
    env.update(os.environ)
    start_date = env.get("CHAVES_CD704_START_DATE") or "2026-08-01"
    end_date = env.get("CHAVES_CD704_END_DATE") or "2026-08-04"
    cd_store = int(env.get("CHAVES_CD704_CD") or "704")

    import pymysql

    conn = pymysql.connect(
        host=env["MYSQL_HOST"],
        port=int(env.get("MYSQL_PORT", "3306")),
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        database=env["MYSQL_DATABASE"],
        charset="latin1",
        cursorclass=pymysql.cursors.DictCursor,
    )
    sql = """
        SELECT
            f_destino.cfg06_numero AS loja,
            f_destino.cfg06_nome AS nome_loja,
            nf.fis01_nronf AS nota,
            nf.fis01_serienf AS serie,
            nf.fis01_data_emissao AS emissao,
            nf.fis01_data_entrada_saida AS entrada_saida,
            nf.fis01_nfe_chave AS chave_acesso
        FROM fis01_notafiscal nf
        JOIN fis02_notafiscal_item ni
            ON ni.fis01_notafiscal_id = nf.fis01_id
        LEFT JOIN pes04_pessoa p_origem
            ON p_origem.pes04_id = nf.pes04_pessoa_emit
        LEFT JOIN pes03_estabelecimento origem
            ON origem.pes03_id = p_origem.pes03_estabelecimento_id
        LEFT JOIN cfg06_filial f_origem
            ON f_origem.pes03_estabelecimento_id = origem.pes03_id
        LEFT JOIN pes04_pessoa p_destino
            ON p_destino.pes04_id = nf.pes04_pessoa_dest
        LEFT JOIN pes03_estabelecimento destino
            ON destino.pes03_id = p_destino.pes03_estabelecimento_id
        LEFT JOIN cfg06_filial f_destino
            ON f_destino.pes03_estabelecimento_id = destino.pes03_id
        WHERE nf.fis01_entrada_saida = 'S'
          AND COALESCE(nf.fis01_flgcancelada, 0) = 0
          AND nf.adm05_usuario_checkin_id IS NULL
          AND f_origem.cfg06_numero = %s
          AND f_destino.cfg06_numero IS NOT NULL
          AND f_destino.cfg06_numero <> %s
          AND f_destino.cfg06_numero < 3000
          AND (
              nf.fis01_data_emissao BETWEEN %s AND %s
              OR nf.fis01_data_entrada_saida BETWEEN %s AND %s
          )
        GROUP BY
            f_destino.cfg06_numero,
            f_destino.cfg06_nome,
            nf.fis01_id,
            nf.fis01_nronf,
            nf.fis01_serienf,
            nf.fis01_data_emissao,
            nf.fis01_data_entrada_saida,
            nf.fis01_nfe_chave
        ORDER BY f_destino.cfg06_numero, nf.fis01_data_emissao, nf.fis01_nronf
    """
    params = (cd_store, cd_store, start_date, end_date, start_date, end_date)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = list(cur.fetchall())
    finally:
        conn.close()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = OUT_DIR / f"chaves_cd{cd_store}_sem_checkin_{start_date}_a_{end_date}_{stamp}.csv"
    txt_path = OUT_DIR / f"chaves_cd{cd_store}_sem_checkin_{start_date}_a_{end_date}_{stamp}.txt"
    latest_csv = OUT_DIR / "chaves_cd704_sem_checkin_ultima.csv"
    latest_txt = OUT_DIR / "chaves_cd704_sem_checkin_ultima.txt"

    fieldnames = ["loja", "nome_loja", "nota", "serie", "emissao", "entrada_saida", "chave_acesso"]
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})

    keys = [str(row.get("chave_acesso") or "").strip() for row in rows if str(row.get("chave_acesso") or "").strip()]
    txt_path.write_text("\n".join(keys) + ("\n" if keys else ""), encoding="utf-8")
    latest_csv.write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")
    latest_txt.write_text(txt_path.read_text(encoding="utf-8"), encoding="utf-8")

    stores = sorted({int(row["loja"]) for row in rows if row.get("loja") is not None})
    print(f"notas={len(rows)} chaves={len(keys)} lojas={len(stores)}")
    print(f"csv={csv_path}")
    print(f"txt={txt_path}")


if __name__ == "__main__":
    main()
