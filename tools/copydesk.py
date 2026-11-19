#!/usr/bin/env python3
"""Put a final client draft next to the exact fragments chosen for its read-through."""
import argparse
import csv
from functools import lru_cache
import json
from pathlib import Path
import re
import sys

from strategist import read_resume_registry, sha256, sha256_bytes


def case_file(root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError(f"Нужен путь относительно кейса: {relative!r}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"Файл недоступен внутри кейса: {relative}")
    return path


def one(rows, field, key):
    hits = [r for r in rows if isinstance(r, dict) and r.get(field) == key]
    if len(hits) != 1:
        raise ValueError(f"Для {key} нужна одна запись, найдено: {len(hits)}")
    return hits[0]


def read_source(root, index, sid):
    src = one(index, 'source_id', sid)
    if src.get('status') != 'active':
        raise ValueError(f'{sid}: источник не помечен действующим')
    original = case_file(root, src.get('stored_path'))
    extract = case_file(root, src.get('extract_path')).read_bytes()
    if sha256(original) != src.get('sha256') or sha256_bytes(extract) != src.get('extract_sha256'):
        raise ValueError(f'{sid}: оригинал или извлечение не совпадает с описью либо нет хеша')
    return src, extract.decode('utf-8').split('\n')


def spread(root, draft, claim_ids):
    root = root.resolve()
    text = draft.decode('utf-8')
    if not text.strip():
        raise ValueError('Пустой клиентский текст')
    index = json.loads(case_file(root, 'sources/index.json').read_text(encoding='utf-8'))
    if not isinstance(index, list):
        raise ValueError('sources/index.json: ожидался список источников')
    claims = read_resume_registry(case_file(root, 'evidence/claims.csv'),
                                  ('claim_id', 'type', 'status', 'statement', 'locator', 'source_ids'))
    @lru_cache(maxsize=None)
    def source(sid):
        return read_source(root, index, sid)

    material = []
    for key in sorted(set(claim_ids)):
        claim = one(claims, 'claim_id', key)
        if claim['status'] != 'active' or claim['type'] != 'fact':
            raise ValueError(f"{key}: {claim['type']} / {claim['status']}; нужен действующий факт. Откройте реестр и выберите актуальное основание.")
        refs = {v.strip() for v in claim['source_ids'].split(';') if v.strip()}
        fragments = []
        used = set()
        for piece in claim['locator'].split(';'):
            sid, sep, loc = piece.strip().partition('#')
            if not sep and len(refs) == 1:  # Earlier records sometimes have one exact, unqualified address.
                sid, loc = next(iter(refs)), piece.strip()
            if not loc or sid not in refs:
                raise ValueError(f'{key}: неоднозначная ссылка {piece!r}; проверьте оригинал вручную')
            src, lines = source(sid)
            prefix = f'- `{loc}` — '
            hits = [line[len(prefix):] for line in lines if line.startswith(prefix)]
            if len(hits) != 1 or not hits[0].strip():
                raise ValueError(f'{sid}#{loc}: нет единственного непустого фрагмента; проверьте оригинал вручную')
            fragments.append({'address': f'{sid}#{loc}', 'quote': hits[0], 'original': src['stored_path'],
                              'original_sha256': src['sha256'], 'synthetic': src.get('synthetic'),
                              'extraction_gaps': src.get('gaps')})
            used.add(sid)
        if used != refs:
            raise ValueError(f'{key}: не все источники имеют адрес фрагмента')
        material.append({'claim': key, 'statement': claim['statement'], 'limitations': claim.get('limitations'),
                         'period': claim.get('period'), 'unit': claim.get('unit'), 'fragments': fragments})
    view = {'draft': text, 'evidence': material}
    stamp = sha256_bytes(json.dumps(view, sort_keys=True, ensure_ascii=False).encode('utf-8'))
    return {**view, 'view_sha256': stamp, 'semantic_check': 'not_performed_by_tool'}


def main():
    p = argparse.ArgumentParser(description='Показать окончательный текст рядом с выбранными основаниями. Не оценивает смысл и не отправляет письмо.')
    p.add_argument('case', type=Path)
    p.add_argument('draft', help='UTF-8 файл либо - для stdin')
    p.add_argument('claims', nargs='+', help='ID действующих фактов, например E-014')
    p.add_argument('--seen', help='Отпечаток ранее прочитанной пары текст/основания')
    args = p.parse_args()
    try:
        if args.seen is not None and not re.fullmatch('[0-9a-f]{64}', args.seen):
            raise ValueError('--seen: нужен view_sha256 из предыдущего чтения')
        data = sys.stdin.buffer.read() if args.draft == '-' else Path(args.draft).read_bytes()
        view = spread(args.case, data, args.claims)
    except (OSError, ValueError, csv.Error) as e:
        print(f'Сверка не состоялась: {e}', file=sys.stderr)
        return 2
    same = None if args.seen is None else view['view_sha256'] == args.seen
    print(json.dumps({**view, 'same_as_seen': same}, ensure_ascii=False, indent=2))
    return 1 if same is False else 0


if __name__ == '__main__':
    sys.exit(main())
