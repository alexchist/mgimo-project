#!/usr/bin/env python3
"""Compare retention across two cohorts after holding the segment mix fixed."""

import argparse
import csv
from fractions import Fraction
import json
from pathlib import Path
import sys

from strategist import parse_csv_dict, sha256_bytes


COUNT_COLUMNS = {'active_users', 'cohort_size'}
KEY_COLUMNS = {'cohort', 'period'}


def compare(data: bytes, segment: str, before: str, after: str, period: str) -> dict:
    if before == after or period == '0' or not all(x.strip() for x in (before, after, period, segment)):
        raise ValueError('Нужны две разные когорты и окно наблюдения, отличное от начального 0.')
    if segment in KEY_COLUMNS | COUNT_COLUMNS:
        raise ValueError('Имя сегмента должно отличаться от полей периода, когорты и счётчиков.')
    rows, headers, _ = parse_csv_dict(data.decode('utf-8-sig'), strict=True)
    required = KEY_COLUMNS | COUNT_COLUMNS | {segment}
    if set(headers) != required:
        raise ValueError(f'Проверьте размерность CSV. Не хватает: {sorted(required-set(headers))}; лишние поля: {sorted(set(headers)-required)}.')
    cells = {}
    names = set()
    for n, row in enumerate(rows, start=2):
        cohort, name, window = ((row[k] or '').strip() for k in ('cohort', segment, 'period'))
        if not cohort or not name or not window:
            raise ValueError(f'row:{n}: пропущена часть ключа cohort × {segment} × period.')
        if cohort not in (before, after):
            continue
        names.add(name)
        if window not in ('0', period):
            continue
        key = cohort, name, window
        if key in cells:
            raise ValueError(f'Две строки для {key}: row:{cells[key][2]} и row:{n}. Уточните гранулярность до сравнения.')
        active, size = ((row[k] or '').strip() for k in ('active_users', 'cohort_size'))
        if not all(x.isascii() and x.isdecimal() for x in (active, size)):
            raise ValueError(f'row:{n}: нужны целые неотрицательные количества, не доли и не пропуски.')
        active, size = int(active), int(size)
        if not 0 <= active <= size or size == 0:
            raise ValueError(f'row:{n}: нужны 0 ≤ active_users ≤ cohort_size и положительная база.')
        cells[key] = active, size, n
    if not names:
        raise ValueError('Ни одна из указанных когорт не найдена.')

    def observed(cohort, name):
        for window in ('0', period):
            if (cohort, name, window) not in cells:
                raise ValueError(f'Нет строки для {(cohort, name, window)}. Не заменяйте пропуск нулём.')
        _, base, n0 = cells[cohort, name, '0']
        active, size, nt = cells[cohort, name, period]
        if base != size:
            raise ValueError(f'База {(cohort, name)} изменилась: row:{n0} = {base}, row:{nt} = {size}. Сначала согласуйте знаменатель.')
        return {'base': base, 'active': active, 'base_row': f'row:{n0}', 'window_row': f'row:{nt}',
                'rate_pct': round(100 * float(Fraction(active, base)), 6)}

    segments = [{'segment': name, 'before': observed(before, name), 'after': observed(after, name)} for name in sorted(names)]
    totals = {k: {f: sum(s[k][f] for s in segments) for f in ('base', 'active')} for k in ('before', 'after')}
    old, new = (Fraction(t['active'], t['base']) for t in totals.values())
    fixed = sum(Fraction(s['before']['base'], totals['before']['base']) * Fraction(s['after']['active'], s['after']['base']) for s in segments)

    def pct(x):
        return round(float(100 * x), 6)

    return {'source_sha256': sha256_bytes(data), 'segment_column': segment, 'cohorts': [before, after], 'period': period,
            'segments': segments, 'totals': totals, 'observed_before_pct': pct(old), 'observed_after_pct': pct(new),
            'after_at_before_mix_pct': pct(fixed), 'observed_delta_pp': pct(new - old),
            'within_at_before_mix_pp': pct(fixed - old), 'mix_at_after_rates_pp': pct(new - fixed),
            'interpretation': 'Описательное сравнение, не причинный эффект. Проверьте зрелость окна, определение активности, полноту и непересечение сегментов в источниках.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', type=Path)
    parser.add_argument('--segment', required=True, help='Столбец с взаимоисключающими сегментами')
    parser.add_argument('--before', required=True, help='Когорта, задающая стандартные веса')
    parser.add_argument('--after', required=True)
    parser.add_argument('--period', required=True, help='Одинаковое окно после старта; база в period=0')
    args = parser.parse_args()
    try:
        result = compare(args.csv.read_bytes(), args.segment, args.before, args.after, args.period)
    except (csv.Error, ValueError, OSError) as exc:
        print(f'Сравнение не выполнено: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
