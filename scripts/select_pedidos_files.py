"""Read-only selection shared by the remote file stages and Pleno comparison."""
import csv
import io
import json
import re
import shlex
import sys
from pathlib import Path


def select_pair(directory, day, order_type=3):
    root = Path(directory)
    paths = [p for folder in (root, root / 'pedido_processado') if folder.is_dir() for p in folder.iterdir() if p.is_file()]
    pattern = re.compile(r'^(?:imp\.[^.]+\.)?PEDIDO_(' + re.escape(day) + r'\d{6})\.csv$')
    candidates = []
    for p in paths:
        match = pattern.match(p.name)
        if not match:
            continue
        with p.open(encoding='utf-8-sig', errors='replace', newline='') as f:
            rows = list(csv.DictReader(f, delimiter=';'))
        typed = [r for r in rows if str(r.get('TIPO_PEDIDO', '')).strip() == str(order_type)]
        if typed:
            candidates.append((match.group(1), p, typed))
    empty = dict(original_pedido_file='', original_item_file='', imp_pedido_file='', imp_item_file='')
    if not candidates:
        return empty, None, []
    # The daily timeline represents the first execution of the scheduled run.
    # A later retry must not replace a batch that was already imported and reconciled.
    execution, selected, rows = min(
        candidates,
        key=lambda x: (x[0], x[1].name.startswith('imp.'), str(x[1])),
    )
    def find(kind, imported):
        suffix = f'{kind}_{execution}.csv'
        matching = [p for p in paths if (p.name.endswith('.' + suffix) and p.name.startswith('imp.'))] if imported else [p for p in paths if p.name == suffix]
        return str(max(matching, key=lambda p: (p.stat().st_mtime_ns, str(p)))) if matching else ''
    result = dict(original_pedido_file=find('PEDIDO', False), original_item_file=find('PEDIDO_ITEM', False), imp_pedido_file=find('PEDIDO', True), imp_item_file=find('PEDIDO_ITEM', True))
    return result, selected, rows


def main():
    directory, day, mode = sys.argv[1:4]
    order_type = int(sys.argv[4]) if len(sys.argv) > 4 else 3
    pair, selected, rows = select_pair(directory, day, order_type)
    if mode == 'shell':
        for k, v in pair.items():
            print(k + '=' + shlex.quote(v))
    elif mode == 'content':
        print('__PEDIDOS_FILE__=' + (selected.name if selected else ''))
        if selected:
            out = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]), delimiter=';', lineterminator='\n')
            out.writeheader()
            out.writerows(rows)
    else:
        print(json.dumps({'pair': pair, 'selected': str(selected) if selected else None, 'type': order_type, 'rows': len(rows)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
