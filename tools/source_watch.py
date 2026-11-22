#!/usr/bin/env python3
"""Opt-in local source-change hook. Watch one named input; never rewrite a case."""
import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

from strategist import REVISION_SNAPSHOT_DOCUMENTS, read_resume_registry, sha256


def case_file(case, relative):
    path = (case / relative).resolve()
    if not path.is_relative_to(case):
        raise ValueError(f'Файл вне кейса: {relative}')
    return path


def impact(case, sid):
    def linked(relative, identity, refs, wanted):
        rows = read_resume_registry(case_file(case, relative), (identity, refs))
        result = []
        for row in rows:
            if wanted.intersection(i.strip() for i in row[refs].split(';')):
                if not re.fullmatch(r'[ECDK]-\d{3,}', row[identity]):
                    raise ValueError(f'Некорректная ссылка: {relative}')
                result.append(row[identity])
        return result

    claims = linked('evidence/claims.csv', 'claim_id', 'source_ids', {sid})
    conclusions = linked('evidence/conclusions.csv', 'conclusion_id', 'evidence_ids', set(claims))
    decisions = linked('decisions/decisions.csv', 'decision_id', 'conclusion_ids', set(conclusions))
    commitments = linked('commitments.csv', 'commitment_id', 'decision_id', set(decisions))
    ids = {sid, *claims, *conclusions, *decisions, *commitments}
    documents = {}
    for name in REVISION_SNAPSHOT_DOCUMENTS:
        path = case_file(case, name)
        if path.is_file():
            hits = [n for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1)
                    if ids.intersection(re.findall(r'(?<![A-Za-z0-9-])[SECDK]-\d{3,}(?!\d)', line))]
            if hits:
                documents[name] = hits
    return dict(claims=claims, conclusions=conclusions, decisions=decisions, commitments=commitments,
                document_lines=documents, scope='Только явные ID и связи. Без ссылки строка может быть затронута по смыслу.')


def watch(case, sid, source_file, interval, once, until_change, claude_hook=False):
    if not re.fullmatch(r'S-\d{3,}', sid):
        raise ValueError('Нужен ID источника вида S-001.')
    if claude_hook:
        inp = json.load(sys.stdin)
        if not isinstance(inp, dict):
            raise ValueError('Ожидалось событие PostToolUse в формате JSON object.')
        if inp.get('hook_event_name') != 'PostToolUse' or inp.get('tool_name') not in {'Edit', 'Write'}:
            return
        body = inp.get('tool_input'); edited = body.get('file_path') if isinstance(body, dict) else None
        if not isinstance(edited, str) or Path(edited).resolve() != source_file.resolve():
            return  # Ignore other edits without looking at case files.
    case = case.resolve(strict=True)
    index = json.loads(case_file(case, 'sources/index.json').read_text(encoding='utf-8'))
    if not isinstance(index, list) or any(not isinstance(row, dict) for row in index):
        raise ValueError('Не удалось прочитать реестр источников.')
    matches = [s for s in index if s.get('source_id') == sid]
    if len(matches) != 1 or not re.fullmatch(r'[0-9a-f]{64}', matches[0].get('sha256') or ''):
        raise ValueError(f'Нет однозначного отпечатка для {sid}.')
    expected = matches[0]['sha256']
    last = object()
    while True:
        # The caller chooses this local file. Never dereference a path/URL from source content.
        try:
            if source_file.is_symlink():
                raise ValueError('Выберите обычный файл, не символическую ссылку.')
            if source_file.exists() and not source_file.is_file():
                raise ValueError('Ожидался обычный файл.')
            observed = sha256(source_file)
        except FileNotFoundError:
            observed = None
        if observed != last:
            status = 'missing' if observed is None else ('matches_import' if observed == expected else 'changed')
            row = dict(source_id=sid, event=status, imported_sha256=expected, observed_sha256=observed)
            if status != 'matches_import':
                row['review'] = impact(case, sid)
                row['next'] = 'Сверьте новый материал. Если это поправка, импортируйте её отдельно и вызовите revise до редактирования записки. Ничего не изменено.'
            if claude_hook:
                if status != 'matches_import':
                    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PostToolUse',
                          'additionalContext': json.dumps(row, ensure_ascii=False)}}, ensure_ascii=False))
                return
            print(json.dumps(row, ensure_ascii=False), flush=True)
            last = observed
            if once or (until_change and status != 'matches_import'):
                return
        time.sleep(interval)


def main():
    p = argparse.ArgumentParser(description='Локально заметить правку одного исходного файла и показать, какие выводы и строки записки перечитать. Остановка: Ctrl+C.')
    p.add_argument('case', type=Path); p.add_argument('source_id'); p.add_argument('file', type=Path)
    mode = p.add_mutually_exclusive_group(); mode.add_argument('--once', action='store_true'); mode.add_argument('--until-change', action='store_true')
    mode.add_argument('--claude-hook', action='store_true', help='Один PostToolUse от Claude Code на stdin; результат для контекста ведущего')
    p.add_argument('--interval', default=2.0, type=float, help='Интервал чтения в секундах (0.1–3600)')
    a = p.parse_args()
    if not .1 <= a.interval <= 3600:
        p.error('Недопустимый интервал.')
    try:
        watch(a.case, a.source_id, a.file, a.interval, a.once, a.until_change, a.claude_hook)
    except (OSError, ValueError, csv.Error) as exc:
        p.exit(2, f'Невозможно проверить: {exc}\n')
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
