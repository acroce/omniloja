#!/usr/bin/env python3
import csv
import json
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = ROOT / "outputs" / "pleno_stock_audit"
OFFICIAL_DIR = ROOT / "outputs" / "pleno_stock_official"
INDEX_DIR = ROOT / "outputs" / "pleno_stock_official_index"
MIN_AUDIT_DATE = date.fromisoformat("2026-07-08")


def parse_number(value):
    text = str(value or "").strip()
    if not text:
        return 0.0
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def parse_run_name(name):
    match = re.match(r"(\d{4}-\d{2}-\d{2})_lojas_(.+)$", name)
    if not match:
        return None
    run_date = date.fromisoformat(match.group(1))
    stores = [part.strip() for part in re.split(r"[-,\s]+", match.group(2)) if part.strip()]
    return run_date, stores


def stock_date_from_name(name):
    match = re.match(r"estoque_(\d{8}).*\.csv$", name)
    if not match:
        return None
    raw = match.group(1)
    return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))


def target_stores_by_date():
    targets = defaultdict(set)
    if not AUDIT_DIR.exists():
      return targets
    for folder in AUDIT_DIR.iterdir():
        if not folder.is_dir():
            continue
        parsed = parse_run_name(folder.name)
        if not parsed:
            continue
        run_date, stores = parsed
        if run_date < MIN_AUDIT_DATE:
            continue
        if "todas" in stores:
            targets[run_date] = None
            if run_date > MIN_AUDIT_DATE:
                targets[run_date - timedelta(days=1)] = None
            continue
        if run_date in targets and targets[run_date] is None:
            continue
        for store in stores:
            targets[run_date].add(store)
            previous_run_date = run_date - timedelta(days=1)
            if run_date > MIN_AUDIT_DATE and not (previous_run_date in targets and targets[previous_run_date] is None):
                targets[run_date - timedelta(days=1)].add(store)
    return targets


def latest_stock_files():
    files = {}
    if not OFFICIAL_DIR.exists():
        return files
    for file_path in OFFICIAL_DIR.glob("estoque_*.csv"):
        stock_date = stock_date_from_name(file_path.name)
        if not stock_date:
            continue
        current = files.get(stock_date)
        if not current or file_path.name > current.name:
            files[stock_date] = file_path
    return files


def write_index(file_path, stock_date, stores):
    all_stores = stores is None
    stores = set() if all_stores else {str(store) for store in stores}
    if not all_stores and not stores:
        return []
    aggregates = defaultdict(
        lambda: {
            "linhas": 0,
            "qtd": 0.0,
            "valor": 0.0,
            "rows": defaultdict(lambda: [0.0, 0.0]),
        }
    )

    with file_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            store = str(row.get("nro_loja", "")).strip()
            if not store or (not all_stores and store not in stores):
                continue
            sku = str(row.get("codigo_interno", "")).strip()
            if not sku:
                continue
            qtd = parse_number(row.get("qtd_estoque"))
            valor = parse_number(row.get("valor_estoque"))
            data = aggregates[store]
            data["linhas"] += 1
            data["qtd"] += qtd
            data["valor"] += valor
            data["rows"][sku][0] += qtd
            data["rows"][sku][1] += valor

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for store, data in aggregates.items():
        out_path = INDEX_DIR / f"{file_path.stem}_loja_{store}.json"
        payload = {
            "date": stock_date.isoformat(),
            "file": file_path.name,
            "loja": store,
            "linhas": data["linhas"],
            "qtd": data["qtd"],
            "valor": data["valor"],
            "rows": [[sku, values[0], values[1]] for sku, values in data["rows"].items()],
        }
        temp_path = out_path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        temp_path.replace(out_path)
        written.append(out_path)
    return written


def main():
    targets = target_stores_by_date()
    files = latest_stock_files()
    total = 0
    for stock_date, stores in sorted(targets.items()):
        file_path = files.get(stock_date)
        if not file_path:
            print(f"sem arquivo oficial para {stock_date}")
            continue
        written = write_index(file_path, stock_date, stores)
        total += len(written)
        print(f"{stock_date}: {file_path.name} -> {len(written)} indice(s)")
    print(f"indices gerados: {total}")


if __name__ == "__main__":
    main()
