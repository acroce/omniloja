#!/usr/bin/env python3
"""Read-only ARIUS import evidence. Never asserts final PDV consumption."""
from __future__ import annotations

import concurrent.futures
import datetime
import fcntl
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from update_pdv_queue_monitor import ServerConfig, askpass_env, load_env
from pdv_import_file_evidence import probe_files, summarize_areas

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / 'outputs/pleno_business_monitor/pdv_consumo.json'
VERSION = 'v2026.09.28-6'


def remote_probe(upgrade='/servidor/pdv/linux/upgrade', retag='/retag'):
    """Bounded metadata/report reads; do not return product lines or secrets."""
    now = datetime.datetime.now().astimezone()
    def meta(p):
        s = p.stat()
        return {'name': p.name, 'size': s.st_size, 'epoch': s.st_mtime,
                'at': datetime.datetime.fromtimestamp(s.st_mtime).astimezone().isoformat()}
    rows = {}
    for directory in (upgrade, retag):
        if not Path(directory).is_dir():
            raise RuntimeError('Diretório ARIUS indisponível')
    for p in Path(upgrade).glob('loja*/tab*.tar.gz'):
        match = re.fullmatch(r'loja(\d+)', p.parent.name)
        if not match or not p.is_file():
            continue
        item = rows.setdefault(match[1], {'store': match[1], 'fileCount': 0})
        item['fileCount'] += 1
        package = meta(p)
        if package['epoch'] > item.get('package', {}).get('epoch', 0):
            item['package'] = package
    for pattern, regex, kind in (
        ('importa.*.lock', r'importa\.(\d+)\.lock', 'lock'),
        ('importa.rep.*.txt', r'importa\.rep\.(\d+)\.txt', 'report'),
    ):
        for p in Path(retag).glob(pattern):
            match = re.fullmatch(regex, p.name)
            if not match or not p.is_file():
                continue
            item = rows.setdefault(match[1], {'store': match[1], 'fileCount': 0})
            data = meta(p)
            if kind == 'report':
                # The result is normally in the header; retain the tail for failures.
                with p.open('rb') as f:
                    header = f.read(32768)
                    if data['size'] > 32768:
                        f.seek(max(32768, data['size'] - 32768))
                        header += f.read(32768)
                content = header.decode('latin1', errors='replace')
                success = re.search(r'Importacao concluida com sucesso\.\s*(\d+) registros na base, lidos (\d+) em (\d+):(\d+):(\d+)', content, re.I)
                data.update(success=bool(success), failed=bool(re.search(
                    r'erro na importa[cç][aã]o|importa[cç][aã]o.*(?:falhou|falha|abortada)|importation failed', content, re.I)),
                    warningCount=len(re.findall(r'ignorado', content, re.I)),
                    warningsTruncated=data['size'] > 65536)
                if success:
                    base, read, h, minute, sec = map(int, success.groups())
                    data.update(baseRecords=base, readRecords=read,
                                durationSeconds=h * 3600 + minute * 60 + sec)
            item[kind] = data
    return {'remoteTime': now.isoformat(), 'rows': list(rows.values())}


def make_rows(snapshot, environment):
    rows = []
    for evidence in sorted(snapshot['rows'], key=lambda r: r['store']):
        package, report, lock = (evidence.get(k, {}) for k in ('package', 'report', 'lock'))
        active = bool(lock and lock['epoch'] > report.get('epoch', 0))
        later = bool(package and report and report['epoch'] >= package['epoch'])
        status, label = 'aguardando', 'Aguardando relatório posterior ao pacote'
        if active:
            label = 'Importação ARIUS possivelmente em andamento'
        elif later and report.get('failed'):
            status, label = 'erro', 'Relatório ARIUS indica falha'
        elif later and report.get('success'):
            status, label = 'atencao', 'Importação ARIUS registrada; consumo final no PDV não confirmado'
        elif not package:
            label = 'Sem pacote observado para correlação'
            if report.get('failed') and not active:
                status, label = 'erro', 'Relatório ARIUS indica falha; sem pacote observado'
        warnings = report.get('warningCount', 0)
        detail = 'Correlação apenas temporal por loja; sem recibo de consumo final no PDV.'
        if report:
            detail += f' Relatório: {warnings} itens ignorados' + (' (contagem parcial).' if report.get('warningsTruncated') else '.')
            if report.get('durationSeconds') is not None:
                detail += f" Duração informada da importação: {report['durationSeconds']} s."
            if package and not later:
                detail += ' O relatório é anterior ao pacote atual.'
        if active:
            detail += ' Lock mais recente que o relatório; atividade inferida, sem ETA validada.'
        rows.append({
            'environment': environment, 'store': evidence['store'], 'name': 'Importação ARIUS',
            'status': status, 'label': label, 'publishedAt': package.get('at'),
            'startedAt': lock.get('at'), 'completedAt': report.get('at'), 'consumedAt': None,
            'fileCount': evidence['fileCount'], 'packageStatus': package.get('name', 'Sem pacote'),
            'deliveryId': '', 'detail': detail, 'warningCount': warnings,
            'estimateMinutes': None, 'correlation': 'temporal_only',
            'remoteTime': snapshot['remoteTime'], 'evidence': evidence,
        })
    return rows


def collect(config, env=None):
    env = env or {}
    if not config.host or not config.user:
        return None, 'Configuração central PROMOPRECO ausente.'
    proc_env, askpass = askpass_env(config)
    command = ['ssh', '-p', str(config.port), '-o', 'BatchMode=no' if config.password else 'BatchMode=yes',
               '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={ROOT / "config/arius_known_hosts"}',
               '-o', 'ConnectTimeout=12',
               '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2',
               f'{config.user}@{config.host}', 'sh', '-s']
    options = {'environment': config.title, 'environmentKey': config.key,
               'runs': [s.strip() for s in (env.get('PROMOPRECO_RUNS') or '04:30,06:30').split(',') if s.strip()],
               'preprodStores': [s.strip() for s in (env.get('PROMOPRECO_PREPROD_STORE_IDS') or '1155,1141,461,1174').split(',')],
               'warningFiles': [s.strip() for s in env.get('PROMOPRECO_WARNING_PENDING_FILES', '').split(',') if s.strip()]}
    script = "python3 - <<'ARIUS_READ_ONLY'\nimport datetime, hashlib, json, re, time\nfrom pathlib import Path\n"
    script += inspect.getsource(remote_probe) + '\n' + inspect.getsource(probe_files)
    script += '\nsnapshot = remote_probe()\nsnapshot.update(probe_files(' + repr(options) + '))\nprint(json.dumps(snapshot))\nARIUS_READ_ONLY\n' 
    try:
        result = subprocess.run(command, input=script, text=True, capture_output=True,
                                env=proc_env, timeout=40, check=False)
        if result.returncode:
            return None, 'Falha SSH ou leitura ARIUS; dados anteriores não confirmam a situação atual.'
        snapshot = json.loads(result.stdout)
        return {'rows': make_rows(snapshot, config.title), 'fileRows': snapshot['fileRows'],
                'fileErrors': [{**error, 'environment': config.title} for error in snapshot['fileErrors']],
                'round': snapshot['round']}, None
    except subprocess.TimeoutExpired:
        return None, 'Tempo limite de 40 segundos na coleta ARIUS.'
    except (OSError, ValueError, KeyError, TypeError):
        return None, 'Resposta ARIUS inválida ou indisponível.'
    finally:
        if askpass:
            Path(askpass).unlink(missing_ok=True)


def main():
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    with STATUS.with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Coleta ARIUS já em andamento.')
            return 75
        env = load_env()
        configs = []
        for index, title in ((1, 'Pré Produção'), (2, 'Produção')):
            prefix = f'PROMOPRECO_S{index}_'
            configs.append(ServerConfig(str(index), title, env.get(prefix + 'HOST', ''),
                env.get(prefix + 'USER', ''), int(env.get(prefix + 'PORT') or '22'),
                env.get(prefix + 'PASSWORD', '')))
        try:
            previous = json.loads(STATUS.read_text())
        except (OSError, ValueError):
            previous = {}
        rows, errors, file_rows, file_errors, rounds = [], [], [], [], []
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            for config, (result, error) in zip(configs, pool.map(lambda config: collect(config, env), configs)):
                if error:
                    errors.append(config.title + ': ' + error)
                    file_errors.append({'environment': config.title, 'area': '*', 'error': error})
                    prior = [r for r in previous.get('rows', []) if r.get('environment') == config.title]
                    for row in prior or [{'environment': config.title, 'store': '-', 'name': 'Importação ARIUS'}]:
                        row.update(status='erro', label='Falha na coleta ARIUS', error=error,
                                   detail=error + ' Última evidência preservada; coleta atual falhou.',
                                   estimateMinutes=None, stale=True)
                        rows.append(row)
                else:
                    rows.extend(result['rows'] or [{'environment': config.title, 'store': '-', 'status': 'aguardando',
                                                  'label': 'Nenhum arquivo observado', 'estimateMinutes': None}])
                    file_rows.extend(result['fileRows'])
                    file_errors.extend(result['fileErrors'])
                    rounds.append(result['round'])
                    errors.extend(config.title + ': ' + e['area'] + ': ' + e['error'] for e in result['fileErrors'])
                failed_areas = {e['area'] for e in file_errors if e['environment'] == config.title}
                for prior in previous.get('fileRows', []):
                    if prior.get('environment') == config.title and ('*' in failed_areas or prior['area'] in failed_areas):
                        old = dict(prior)
                        old.update(status='not_verified', stale=True, sha256Match=None,
                                   detail='Falha na coleta atual; evidência anterior preservada, fora das contagens.')
                        file_rows.append(old)
        now = datetime.datetime.now().astimezone().isoformat()
        payload = {'generatedAt': now, 'lastAttemptAt': now, 'version': VERSION, 'rows': rows,
                   'fileRows': file_rows, 'areas': summarize_areas(file_rows, file_errors), 'rounds': rounds,
                   'comparisonLabel': 'Conteúdo igual ao original ARIUS',
                   'notice': 'Conteúdo comparado ao original atual no ARIUS, não à origem externa. SHA256 pode ser parcial. Marcador imp. não confirma consumo final no PDV.',
                   'fileErrors': file_errors,
                   'collection': {'status': 'erro' if errors else 'ok', 'error': ' '.join(errors)}}
        fd, filename = tempfile.mkstemp(dir=STATUS.parent, prefix='.pdv-consumo-', suffix='.json')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(payload, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(filename, STATUS)
        finally:
            Path(filename).unlink(missing_ok=True)
        print(json.dumps({'rows': len(rows), 'failedEnvironments': len(errors)}))
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
