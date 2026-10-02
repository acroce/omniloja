"""Bounded retries and shared, host-local NOC API incident tracking."""
from __future__ import annotations
import fcntl
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

class ApiUnavailable(RuntimeError):
    pass

def safe_url(url):
    p=urllib.parse.urlsplit(url)
    host=p.hostname or ''
    if ':' in host: host='['+host+']'
    return urllib.parse.urlunsplit((p.scheme,host+((':'+str(p.port)) if p.port else ''),p.path,'',''))

def request_json(url, scope, observations):
    clean=safe_url(url)
    for attempt in range(1,4):
        started=time.monotonic()
        event={'at':datetime.now().astimezone().isoformat(timespec='seconds'),'scope':scope,'url':clean,'attempt':attempt}
        try:
            with urllib.request.urlopen(url,timeout=20) as response:
                event['http_status']=response.status
                data=json.loads(response.read().decode('utf-8'))
                if not isinstance(data,dict) or not isinstance(data.get('stages'),list):
                    raise ValueError('invalid monitor response')
            event['ok']=True
        except Exception as exc:
            event.update(ok=False,exception=type(exc).__name__)
            if isinstance(exc,urllib.error.HTTPError):event['http_status']=exc.code
            reason=getattr(exc,'reason',None)
            if reason is not None:event['reason_type']=type(reason).__name__
            errno=getattr(reason or exc,'errno',None)
            if isinstance(errno,int):event['errno']=errno
        event['elapsed_ms']=round((time.monotonic()-started)*1000,2)
        observations.append(event)
        if event['ok']:return data
        if attempt<3:time.sleep(attempt) # 1s then 2s; at most 63s per endpoint.
    raise ApiUnavailable('NOC internal API failed after three attempts')

def process_observations(directory: Path, observations, send, dry_run=False):
    """One incident across scopes/processes; preserve business alert state separately."""
    if dry_run or not observations:return
    directory.mkdir(parents=True,exist_ok=True)
    state_path=directory/'noc_api_alert_state.json'
    log_path=directory/'logs/noc_api_requests.jsonl'
    log_path.parent.mkdir(parents=True,exist_ok=True)
    with (directory/'noc_api_alert.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if state_path.exists():state=json.loads(state_path.read_text())
        else:state={'endpoints':{}}
        if log_path.exists() and log_path.stat().st_size>2_000_000:
            for i in range(4,0,-1):
                old=Path(str(log_path)+f'.{i}')
                if old.exists():old.replace(Path(str(log_path)+f'.{i+1}'))
            log_path.replace(Path(str(log_path)+'.1'))
        with log_path.open('a') as log:
            for event in observations:log.write(json.dumps(event,ensure_ascii=False)+'\n')
        for event in observations:
            state['endpoints'][event['url']]=event
        failures=[v for v in state['endpoints'].values() if not v['ok']]
        now=time.time()
        if failures:
            state.setdefault('firstErrorAt',failures[0]['at'])
            state['lastErrorAt']=max(v['at'] for v in failures)
            state['active']=True
            # One global notice, even when cron launches separate scope processes.
            if now-state.get('lastSentEpoch',0)>=3600:
                message='❌ NOC interno (10.106.69.19) — API indisponível após 3 tentativas.\nFalha na consulta do painel; não identifica queda de produção ou homologação.\n'
                message+='\n'.join(f"{v['scope']}: {v['url']} — HTTP {v.get('http_status','-')}, {v.get('exception','erro')}, {v['elapsed_ms']} ms na última tentativa" for v in failures)
                try:
                    send(message)
                    state['lastSentEpoch']=now
                    state['sentAt']=datetime.now().astimezone().isoformat(timespec='seconds')
                    state.pop('deliveryError',None)
                except Exception as exc:
                    state['deliveryError']=type(exc).__name__
                    # Reserve a short retry interval; never print webhook/token errors.
                    state['lastSentEpoch']=now-3300
        else:
            if state.get('active'):state['recoveredAt']=datetime.now().astimezone().isoformat(timespec='seconds')
            state['active']=False
            state.pop('firstErrorAt',None)
        tmp=state_path.with_name(state_path.name+f'.{os.getpid()}.tmp')
        tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
        tmp.replace(state_path)
