"""Render every observed paired exact-field/reader change (including losses), without model calls."""
from collections import defaultdict
import argparse
from pathlib import Path
from benchmark import read, grades, HERE
from blind import join


def render():
    d=HERE.parents[1]/'docs/promptbench-v1'; runs=d/'runs'; keys=read(HERE/'keys.json')
    pairs=defaultdict(dict)
    for p in sorted(runs.glob('[0-9]*.json')):
        r=read(p);pairs[r['model'],r['case'],r['rep']][r['arm']]=r
    assert len(pairs)==60 and all(set(q)==set('AB') for q in pairs.values())
    lines=['# Детализация журнала: PromptBench-RU v1','',
    'Источник: [120 ответов и методика](README.md). Для коротких задач ниже все пары с изменением хотя бы одного строго оценённого поля. Пропущенные пары совпали по всем отметкам, не обязательно по тексту. Изменение имени ключа может изменить балл, не смысл. Для записок — все пары и обе слепые оценки, биты соответствуют порядку [пяти требований своей задачи](../../evals/promptbench/rubric.md). 1 на позиции означает зачтённое требование. Риск указан отдельно (1 = отмечен). Не суммировать как независимые подтверждения.', '', '|Модель|Задача, повтор|Ответ A → B|Стало верно|Перестало быть верно|','|---|---|---|---|---|']
    nums=lambda a,b:' → '.join(f'[{n:03d}](runs/{n:03d}.json)' for n in [a['seq'],b['seq']])
    for (m,c,rep),q in sorted(pairs.items()):
        if c not in keys:continue
        a,b=q['A'],q['B'];x=grades(a,keys[c]);y=grades(b,keys[c]);
        if x==y:continue
        pos=', '.join(k for k,i,j in zip(keys[c],x,y) if j and not i) or '—';neg=', '.join(k for k,i,j in zip(keys[c],x,y) if i and not j) or '—'
        lines.append(f'|{m}|{c}, {rep}|{nums(a,b)}|{pos}|{neg}|')
    lines+=['','|Модель|Кейс, повтор|Ответ A → B|Читатель 1: отметки; риск|Читатель 2: отметки; риск|','|---|---|---|---|---|']
    raters=[]
    for which in ('one','two'):
        path=d/'audit'/which;raters.append({r['seq']:r for r in join(runs,read(path/'mapping.json'),read(path/'marks.json'))})
    for (m,c,rep),q in sorted(pairs.items()):
        if c in keys:continue
        a,b=q['A'],q['B'];cells=[]
        for reader in raters:
            x,y=[reader[r['seq']] for r in [a,b]];cells.append(f"`{x['bits']}` → `{y['bits']}`; {x['risk']} → {y['risk']}")
        lines.append(f'|{m}|{c}, {rep}|{nums(a,b)}|'+ '|'.join(cells)+'|')
    return '\n'.join(lines)+'\n'

if __name__=='__main__':print(render(),end='')
