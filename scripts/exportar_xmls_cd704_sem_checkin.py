#!/usr/bin/env python3
from __future__ import annotations

import csv
import os
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".python_packages"))

OUT_DIR = ROOT / "outputs" / "pleno_xmls_cd704_sem_checkin"


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


def safe_name(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    return text[:160] or "sem_nome"


def xml_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def main() -> None:
    env = load_env_file(ROOT / ".env")
    env.update(os.environ)
    start_date = env.get("XMLS_CD704_START_DATE") or "2026-08-01"
    end_date = env.get("XMLS_CD704_END_DATE") or "2026-08-04"
    cd_store = int(env.get("XMLS_CD704_CD") or "704")

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
            nf.fis01_nfe_chave AS chave_acesso,
            COALESCE(NULLIF(nf.fis01_xml, ''), NULLIF(tab02.tab02_xml, '')) AS xml,
            CASE
                WHEN NULLIF(nf.fis01_xml, '') IS NOT NULL THEN 'fis01_xml'
                WHEN NULLIF(tab02.tab02_xml, '') IS NOT NULL THEN 'tab02_nfe_interesse.tab02_xml'
                ELSE ''
            END AS origem_xml
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
        LEFT JOIN tab02_nfe_interesse tab02
            ON tab02.tab02_chave = nf.fis01_nfe_chave
        WHERE nf.fis01_entrada_saida = 'S'
          AND COALESCE(nf.fis01_flgcancelada, 0) = 0
          AND nf.adm05_usuario_checkin_id IS NULL
          AND f_origem.cfg06_numero = %s
          AND f_destino.cfg06_numero IS NOT NULL
          AND f_destino.cfg06_numero <> %s
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
            nf.fis01_nfe_chave,
            nf.fis01_xml,
            tab02.tab02_xml
        ORDER BY f_destino.cfg06_numero, nf.fis01_data_emissao, nf.fis01_nronf
    """
    params = (cd_store, cd_store, start_date, end_date, start_date, end_date)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = list(cur.fetchall())
    finally:
        conn.close()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUT_DIR / f"xmls_cd{cd_store}_sem_checkin_{start_date}_a_{end_date}_{stamp}"
    xml_dir = run_dir / "xmls"
    xml_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifesto_xmls.csv"
    missing_path = run_dir / "notas_sem_xml.csv"
    zip_path = OUT_DIR / f"xmls_cd{cd_store}_sem_checkin_{start_date}_a_{end_date}_{stamp}.zip"
    latest_zip = OUT_DIR / "xmls_cd704_sem_checkin_ultimo.zip"

    written = []
    missing = []
    for row in rows:
        key = str(row.get("chave_acesso") or "").strip()
        xml = xml_text(row.get("xml")).strip()
        if not key or not xml:
            missing.append(row)
            continue
        filename = f"loja_{safe_name(row.get('loja'))}_nf_{safe_name(row.get('nota'))}_{safe_name(key)}.xml"
        path = xml_dir / filename
        path.write_text(xml, encoding="utf-8")
        written.append((row, path))

    fieldnames = ["loja", "nome_loja", "nota", "serie", "emissao", "entrada_saida", "chave_acesso", "origem_xml", "arquivo_xml"]
    with manifest_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row, path in written:
            writer.writerow({
                "loja": row.get("loja"),
                "nome_loja": row.get("nome_loja"),
                "nota": row.get("nota"),
                "serie": row.get("serie"),
                "emissao": row.get("emissao"),
                "entrada_saida": row.get("entrada_saida"),
                "chave_acesso": row.get("chave_acesso"),
                "origem_xml": row.get("origem_xml"),
                "arquivo_xml": str(path.relative_to(run_dir)),
            })

    with missing_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=[name for name in fieldnames if name != "arquivo_xml"])
        writer.writeheader()
        for row in missing:
            writer.writerow({
                "loja": row.get("loja"),
                "nome_loja": row.get("nome_loja"),
                "nota": row.get("nota"),
                "serie": row.get("serie"),
                "emissao": row.get("emissao"),
                "entrada_saida": row.get("entrada_saida"),
                "chave_acesso": row.get("chave_acesso"),
            })

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(manifest_path, manifest_path.relative_to(run_dir.parent))
        zf.write(missing_path, missing_path.relative_to(run_dir.parent))
        for _, path in written:
            zf.write(path, path.relative_to(run_dir.parent))

    latest_zip.write_bytes(zip_path.read_bytes())
    print(f"notas={len(rows)} xmls={len(written)} sem_xml={len(missing)}")
    print(f"pasta={run_dir}")
    print(f"zip={zip_path}")


if __name__ == "__main__":
    main()
