"""Read-only file evidence for ARIUS; no upstream or final-PDV claims."""
import datetime
import hashlib
import re
import time
from pathlib import Path

AREA_PATHS = ('PROD', 'PROM', 'PROM/CLUBDIA', 'PROM/CLUBDIA/bkp')


def probe_files(options, base='/servidor/importacao', now=None):
    # Self-contained so the collector can send this function in its existing SSH.
    now = now or datetime.datetime.now().astimezone()
    deadline = time.monotonic() + 20
    remaining = 64 * 1024 * 1024
    areas = ('PROD', 'PROM', 'PROM/CLUBDIA', 'PROM/CLUBDIA/bkp')
    slots = []
    for value in options.get('runs', ['04:30', '06:30']):
        parsed = datetime.datetime.strptime(value, '%H:%M')
        slots.append(now.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0))
    eligible = [slot for slot in slots if slot <= now]
    start = max(eligible) if eligible else None
    preprod = {str(int(s)) for s in options.get('preprodStores', []) if str(s).isdigit()}
    ignored = {name.lower() for name in options.get('warningFiles', [])} | {'out.csv', 'intpropremio.csv'}
    rows, errors = [], []
    candidates = []
    for area in areas:
        directory = Path(base) / area
        backup = area.endswith('/bkp')
        originals, imported = {}, {}
        try:
            for file in directory.iterdir():
                if not file.is_file():
                    continue
                match = re.fullmatch(r'imp\.(\d{12}|\d{14})\.(.+)', file.name)
                if match:
                    stamp, original_name = match.groups()
                    try:
                        imported_at = datetime.datetime.strptime(stamp, '%Y%m%d%H%M' if len(stamp) == 12 else '%Y%m%d%H%M%S').replace(tzinfo=now.tzinfo)
                    except ValueError:
                        continue
                    if start and start <= imported_at <= now:
                        old = imported.get(original_name)
                        if not old or imported_at > old[1]:
                            imported[original_name] = (file, imported_at)
                elif not file.name.startswith('imp.'):
                    stat = file.stat()
                    mtime = datetime.datetime.fromtimestamp(stat.st_mtime, tz=now.tzinfo)
                    if backup or mtime.date() == now.date():
                        originals[file.name] = (file, mtime)
        except OSError:
            errors.append({'area': area, 'error': 'Diretório indisponível ou alterado durante a leitura.'})
            continue
        for name in sorted(originals.keys() | imported.keys()):
            original = originals.get(name)
            imp = imported.get(name)
            # A consumed/renamed file can have an old original still present.
            if not original and (directory / name).is_file():
                file = directory / name
                original = (file, datetime.datetime.fromtimestamp(file.stat().st_mtime, tz=now.tzinfo))
            match = re.match(r'^(\d{1,5})[_-]', name)
            store = str(int(match.group(1))) if match else None
            if store is not None and not backup:
                if (store in preprod) != (options.get('environmentKey') == '1'):
                    continue
            status = 'not_verified'
            detail = 'Sem evidência suficiente para classificar o arquivo nesta janela.'
            is_candidate = name.lower().endswith('.csv') and (
                store is not None or name.lower().startswith('int') or name.lower() == 'dim_produtos.csv')
            warning = name.lower() in ignored or ' - copy' in name.lower()
            if backup:
                status, detail = 'not_applicable', 'Backup histórico; não constitui pendência de importação.'
            elif imp:
                status, detail = 'imported', 'Marcador imp. observado na janela de importação ARIUS; consumo final no PDV não confirmado.'
            elif start and original and is_candidate and not warning:
                status, detail = 'pending', 'Original do dia sem marcador imp. nesta janela de importação ARIUS.'
            elif warning:
                detail = 'Arquivo auxiliar ou exceção; não contado como pendência.'
            row = {'environment': options['environment'], 'area': area,
                   'store': store, 'originalName': name, 'originalPresent': bool(original),
                   'originalMtime': original[1].isoformat() if original else None,
                   'importedName': imp[0].name if imp else None,
                   'importedAt': imp[1].isoformat() if imp else None,
                   'sha256Match': None, 'status': status, 'detail': detail,
                   'roundStart': start.isoformat() if start else None,
                   'roundEnd': now.isoformat(), 'comparison': 'original_arius'}
            rows.append(row)
            if original and imp and not backup:
                try:
                    candidates.append((original[0].stat().st_size + imp[0].stat().st_size,
                                       original[0], imp[0], row))
                except OSError:
                    row['detail'] += ' Arquivo alterado durante a coleta; igualdade não verificada.'
    # Small pairs first: stay within bounded IO, never extrapolate sample matches.
    for size, original, imported, row in sorted(candidates, key=lambda item: item[0]):
        if size > remaining or time.monotonic() > deadline:
            row['detail'] += ' SHA256 não calculado: limite de leitura desta coleta.'
            continue
        remaining -= size
        try:
            hashes, signatures = [], []
            for file in (original, imported):
                stat = file.stat()
                signatures.append((stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
                digest = hashlib.sha256()
                with file.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        if time.monotonic() > deadline:
                            raise TimeoutError
                        digest.update(block)
                hashes.append(digest.hexdigest())
            stable = []
            for file in (original, imported):
                stat = file.stat()
                stable.append((stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
            if stable == signatures:
                row['sha256Match'] = hashes[0] == hashes[1]
                row['detail'] += ' SHA256 comparado com o original atual no ARIUS; não com origem externa.'
            else:
                row['detail'] += ' Arquivo alterado durante a comparação; resultado indeterminado.'
        except (OSError, TimeoutError):
            row['detail'] += ' Não foi possível concluir a comparação estável de conteúdo.'
    return {'fileRows': rows, 'fileErrors': errors,
            'round': {'environment': options['environment'],
                      'start': start.isoformat() if start else None, 'end': now.isoformat(),
                      'basis': 'imp_prefix', 'label': 'Janela de importação ARIUS'}}


def summarize_areas(rows, errors):
    result = []
    for area in AREA_PATHS:
        subset = [r for r in rows if r['area'] == area and not r.get('stale')]
        failures = [e for e in errors if e.get('area') in (area, '*')]
        pairs = [r for r in subset if r.get('originalPresent') and r.get('importedName') and r['status'] != 'not_applicable']
        checked = sum(r.get('sha256Match') is not None for r in pairs)
        equal = sum(r.get('sha256Match') is True for r in pairs)
        backup = area.endswith('/bkp')
        result.append({'name': 'PROM raiz' if area == 'PROM' else area,
                       'equalToSource': f'{equal}/{len(pairs)}' if checked and not failures else 'Não verificado',
                       'impConfirmed': 'N/A' if backup else str(sum(r['status'] == 'imported' for r in subset)),
                       'originalName': str(sum(bool(r['originalPresent']) for r in subset)),
                       'comparisonLabel': 'Conteúdo igual ao original ARIUS',
                       'checkedPairs': checked, 'eligiblePairs': len(pairs), 'incomplete': bool(failures),
                       'detail': 'Sem validação de origem externa. ' + ('Backup histórico, fora da importação.' if backup else f'{checked} pares comparados por SHA256; comparação pode ser parcial.')})
    return result
