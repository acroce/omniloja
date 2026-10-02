from __future__ import annotations

import csv
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from argparse import ArgumentParser
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_PACKAGES = ROOT / ".python_packages"
if str(PYTHON_PACKAGES) not in sys.path:
    sys.path.insert(0, str(PYTHON_PACKAGES))

import pymysql


REPORTS = [
    {
        "sql_path": Path("/Users/alexandrematheuscrose/Documents/Scripts Pleno/exportaçao de vendas .sql"),
    },
    {
        "sql_path": Path("/Users/alexandrematheuscrose/Documents/Scripts Pleno/encerramento_caixa_incluir_fechamento_pdv.sql"),
    },
    {
        "sql_path": Path("/Users/alexandrematheuscrose/Documents/Scripts Pleno/Integração de Vendas v2.sql"),
    },
    {
        "sql_path": Path("/Users/alexandrematheuscrose/Documents/Scripts Pleno/Relatorio de Retiradas.sql"),
    },
]

BETWEEN_DATE_PATTERN = re.compile(
    r"BETWEEN\s+'?\d{4}-\d{2}-\d{2}'?\s+AND\s+'?\d{4}-\d{2}-\d{2}'?",
    re.IGNORECASE,
)
DATE_INITIAL_PATTERN = re.compile(
    r"DATE\('?\d{4}-\d{2}-\d{2}'?\)\s+AS\s+data_inicial",
    re.IGNORECASE,
)
DATE_FINAL_PATTERN = re.compile(
    r"DATE\('?\d{4}-\d{2}-\d{2}'?\)\s+AS\s+data_final",
    re.IGNORECASE,
)
OUTPUT_ROOT = ROOT / "outputs" / "daily_pleno_reports"
DEFAULT_EMAIL = "marcela.silva@diagroup.com"


def load_env(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def parse_args() -> ArgumentParser:
    parser = ArgumentParser(description="Generate daily Pleno reports from SQL files.")
    parser.add_argument(
        "--date",
        dest="report_date",
        help="Reference date in YYYY-MM-DD format. Defaults to today.",
    )
    parser.add_argument(
        "--start-date",
        dest="start_date",
        help="Initial date in YYYY-MM-DD format. Defaults to the first day of the reference month.",
    )
    parser.add_argument(
        "--email",
        dest="recipient_email",
        default=DEFAULT_EMAIL,
        help="Recipient email to document in the manifest.",
    )
    parser.add_argument(
        "--no-chat",
        action="store_true",
        help="Generate the files without sending the Google Chat notification.",
    )
    return parser


def resolve_report_date(raw_date: str | None) -> date:
    if raw_date:
        return datetime.strptime(raw_date, "%Y-%m-%d").date()
    return date.today()


def resolve_start_date(raw_date: str | None, report_date: date) -> date:
    if raw_date:
        return datetime.strptime(raw_date, "%Y-%m-%d").date()
    return report_date.replace(day=1)


def safe_report_name(sql_path: Path) -> str:
    normalized = unicodedata.normalize("NFKD", sql_path.stem)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r"[^A-Za-z0-9]+", "_", ascii_name).strip("_").lower()
    return ascii_name or "relatorio"


def render_sql(sql_path: Path, start_date: date, end_date: date) -> str:
    sql = sql_path.read_text(encoding="utf-8")
    sql = BETWEEN_DATE_PATTERN.sub(
        f"BETWEEN '{start_date.isoformat()}' AND '{end_date.isoformat()}'",
        sql,
    )
    sql = DATE_INITIAL_PATTERN.sub(
        f"DATE('{start_date.isoformat()}') AS data_inicial",
        sql,
    )
    sql = DATE_FINAL_PATTERN.sub(
        f"DATE('{end_date.isoformat()}') AS data_final",
        sql,
    )

    lines = sql.splitlines()
    start_idx = 0
    for idx, line in enumerate(lines):
        stripped = line.strip().upper()
        if stripped.startswith("WITH") or stripped.startswith("SELECT"):
            start_idx = idx
            break

    cleaned = "\n".join(lines[start_idx:]).strip()
    return cleaned


def connect(env: dict[str, str]) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=env["MYSQL_HOST"],
        port=int(env.get("MYSQL_PORT", "3306")),
        user=env["MYSQL_USER"],
        password=env["MYSQL_PASSWORD"],
        database=env["MYSQL_DATABASE"],
        charset="latin1",
        connect_timeout=15,
        read_timeout=3600,
        write_timeout=3600,
    )


def write_csv(output_path: Path, headers: list[str], rows: list[tuple]) -> None:
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(headers)
        writer.writerows(rows)


def write_cursor_csv(output_path: Path, headers: list[str], cursor: pymysql.cursors.Cursor) -> int:
    row_count = 0
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(headers)
        for row in cursor:
            writer.writerow(row)
            row_count += 1
    return row_count


def build_manifest(
    manifest_path: Path,
    start_date: date,
    report_date: date,
    recipient_email: str,
    delivery_files: list[Path],
    delivery_status: str,
) -> None:
    lines = [
        f"start_date={start_date.isoformat()}",
        f"report_date={report_date.isoformat()}",
        f"generated_at={datetime.now().isoformat(timespec='seconds')}",
        f"recipient_email={recipient_email}",
        f"delivery_status={delivery_status}",
        "delivery_files=",
    ]
    lines.extend(f"- {path.name}" for path in delivery_files)
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def post_google_chat_webhook(webhook_url: str, message: str) -> None:
    payload = json.dumps({"text": message}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google Chat webhook returned HTTP {exc.code}: {body}") from exc


def notify_google_chat(
    env: dict[str, str],
    start_date: date,
    report_date: date,
    recipient_email: str,
    delivery_files: list[Path],
) -> str:
    webhook_url = env.get("GOOGLE_CHAT_WEBHOOK_URL", "").strip().strip('"')
    if not webhook_url:
        return "pending_google_chat_webhook_url"

    file_lines = "\n".join(f"- {path.name}" for path in delivery_files)
    message = (
        f"Relatórios Pleno gerados para {recipient_email}\n"
        f"Período: {start_date.isoformat()} até {report_date.isoformat()}\n"
        f"Arquivos separados para envio:\n{file_lines}"
    )
    post_google_chat_webhook(webhook_url, message)
    return "sent_google_chat_webhook"


def main() -> int:
    parser = parse_args()
    args = parser.parse_args()
    report_date = resolve_report_date(args.report_date)
    start_date = resolve_start_date(args.start_date, report_date)
    env = load_env(ROOT / ".env")

    required = ["MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"]
    missing = [key for key in required if not env.get(key)]
    if missing:
        raise SystemExit(f"Missing required .env keys: {', '.join(missing)}")

    output_dir = OUTPUT_ROOT / report_date.strftime("%Y%m%d")
    output_dir.mkdir(parents=True, exist_ok=True)

    delivery_files: list[Path] = []
    conn = connect(env)
    try:
        with conn.cursor(pymysql.cursors.SSCursor) as cur:
            cur.execute("SET NAMES latin1")
            cur.execute("SET collation_connection = 'latin1_swedish_ci'")

            for report in REPORTS:
                sql_path = report["sql_path"]
                sql = render_sql(sql_path, start_date, report_date)
                cur.execute(sql)
                headers = [column[0] for column in cur.description]
                csv_path = output_dir / f"{safe_report_name(sql_path)}_{report_date.strftime('%Y%m%d')}.csv"
                write_cursor_csv(csv_path, headers, cur)
                delivery_files.append(csv_path)
    finally:
        conn.close()

    delivery_status = "skipped_google_chat"
    if not args.no_chat:
        delivery_status = notify_google_chat(
            env,
            start_date,
            report_date,
            args.recipient_email,
            delivery_files,
        )

    manifest_path = output_dir / f"manifest_{report_date.strftime('%Y%m%d')}.txt"
    build_manifest(manifest_path, start_date, report_date, args.recipient_email, delivery_files, delivery_status)

    print(output_dir)
    for file_path in [*delivery_files, manifest_path]:
        print(file_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
