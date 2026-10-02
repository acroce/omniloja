"""Fixed, parameterized Pleno reports. No SQL supplied by the browser."""
import csv
from datetime import date
from decimal import Decimal
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.python_packages'))
REPORTS = {'vendas', 'integracao', 'retiradas', 'encerramento', 'autoconsumo'}


def load_env():
    values = {}
    env_file = Path(os.environ.get('NOC_EXPORT_ENV_FILE', str(ROOT / '.env')))
    if env_file.exists():
        for raw in env_file.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key.strip()] = value
    return {**values, **os.environ}


def cell(value):
    if value is None:
        return ''
    if isinstance(value, Decimal):
        return format(value, 'f').replace('.', ',')
    if isinstance(value, float):
        return str(value).replace('.', ',')
    # Prevent a database text field from becoming an Excel formula.
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    if isinstance(value, str) and value.startswith(('\t', '\r', '\n')):
        return "'" + value
    return value


def export(report, start, end, destination):
    import pymysql
    if report not in REPORTS:
        raise ValueError('Invalid report')
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if not 0 <= (last - first).days <= 365:
        raise ValueError('Invalid period')
    env = load_env()
    connection = pymysql.connect(
        host=env['MYSQL_HOST'], port=int(env.get('MYSQL_PORT', 3306)),
        user=env['MYSQL_USER'], password=env['MYSQL_PASSWORD'],
        database=env['MYSQL_DATABASE'], charset='utf8mb4',
        connect_timeout=10, read_timeout=130, write_timeout=10,
        cursorclass=pymysql.cursors.SSCursor,
    )
    count = 0
    try:
        with connection.cursor() as cursor:
            cursor.execute('SET SESSION MAX_EXECUTION_TIME=120000')
            cursor.execute('START TRANSACTION READ ONLY')
            sql = (Path(__file__).parent / 'sql' / (report + '.sql')).read_text()
            cursor.execute(sql, {'start': start, 'end': end})
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8-sig', newline='') as output:
                writer = csv.writer(output, delimiter=';', lineterminator='\r\n')
                writer.writerow([field[0] for field in cursor.description])
                while True:
                    batch = cursor.fetchmany(1000)
                    if not batch:
                        break
                    writer.writerows([[cell(value) for value in row] for row in batch])
                    count += len(batch)
                    if output.tell() > 500 * 1024 * 1024:
                        raise ValueError('Export size exceeded')
    finally:
        connection.close()
    return {'rows': count, 'bytes': Path(destination).stat().st_size}


if __name__ == '__main__':
    try:
        print(json.dumps(export(*sys.argv[1:])))
    except Exception as error:
        # Do not leak SQL, credentials or database infrastructure to HTTP/logs.
        print(json.dumps({'error': type(error).__name__}), file=sys.stderr)
        sys.exit(1)
