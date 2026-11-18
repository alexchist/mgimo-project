"""Check a fixed-volume subscription scenario, without evaluating model-written arithmetic."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re


COLUMNS = ('option', 'monthly_price_rub', 'variable_cost_per_account_month_rub',
           'setup_cost_rub', 'monthly_fixed_cost_rub', 'accounts_scenario', 'scenario_kind')


def kopecks(text, *, signed=False):
    pattern = (r'[+-]?' if signed else '') + r'[0-9]+(?:\.[0-9]{1,2})?'
    if not re.fullmatch(pattern, text):
        raise ValueError(f'expected RUB amount with at most two decimal places, got {text!r}')
    whole, _, fraction = text.lstrip('+-').partition('.')
    value = int(whole) * 100 + int(fraction.ljust(2, '0'))
    return -value if text.startswith('-') else value


def rub(value):
    return f'{"-" if value < 0 else ""}{abs(value) // 100}.{abs(value) % 100:02d}'


def scenario(row, months):
    if not re.fullmatch('[0-9]+', row['accounts_scenario']):
        raise ValueError('accounts_scenario must be a non-negative whole number')
    n = int(row['accounts_scenario'])
    price, variable, setup, fixed = (kopecks(row[key]) for key in COLUMNS[1:5])
    sales, costs = months * n * price, months * n * variable
    fixed_total = setup + months * fixed
    contribution = months * (price - variable)
    threshold = ((fixed_total + contribution - 1) // contribution if contribution > 0
                 else 0 if fixed_total == 0 else None)
    return {'inputs': row, 'revenue_rub': rub(sales), 'variable_total_rub': rub(costs),
            'fixed_total_including_setup_rub': rub(fixed_total), 'net_rub': rub(sales - costs - fixed_total),
            'min_accounts_for_net_nonnegative': threshold}


def calculate(data, months, expected):
    if months < 1:
        raise ValueError('months must be positive')
    reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig'), newline=''), strict=True)
    if sorted(reader.fieldnames or []) != sorted(COLUMNS):
        raise ValueError('expected exactly these comma-separated columns: ' + ','.join(COLUMNS))
    rows = {}
    for idx, raw in enumerate(reader, 1):
        if None in raw or any(v is None or not v.strip() for v in raw.values()):
            raise ValueError(f'data record {idx}: missing or extra value (unknown is not zero)')
        row = {k: v.strip() for k, v in raw.items()}
        name = row['option']
        if name in rows:
            raise ValueError(f'duplicate option: {name}')
        rows[name] = {'data_record': idx, **scenario(row, months)}
    if not rows:
        raise ValueError('no scenario rows')
    checks = {}
    for name, amount in expected:
        if name not in rows or name in checks:
            raise ValueError(f'unknown or repeated option in comparison: {name}')
        claim = rub(kopecks(amount, signed=True))
        actual = rows[name]['net_rub']
        checks[name] = {'claimed_net_rub': claim, 'calculated_net_rub': actual, 'matches': claim == actual}
    return {'schema': 'strategist.subscription-scenario/1', 'months': months,
            'input_sha256': hashlib.sha256(data).hexdigest(),
            'scope': 'Constant paying accounts and rates for all months; scenario arithmetic only.',
            'formula': 'months * accounts * (price - variable) - setup - months * fixed',
            'scenarios': rows, 'comparisons': checks,
            'status': ('calculated_only' if not checks else 'match' if all(c['matches'] for c in checks.values()) else 'mismatch')}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('csv', type=Path, help='Normalized subscription scenarios in RUB, one row per option')
    p.add_argument('--months', required=True, type=int, help='Full months on unchanged terms')
    p.add_argument('--expect-net', nargs=2, metavar=('OPTION', 'RUB'), action='append', default=[],
                   help='Compare the net amount stated in a draft, not a value copied from this calculation')
    p.add_argument('--receipt', type=Path, help='Also save the same JSON to a NEW file; never overwrite')
    args = p.parse_args()
    try:
        result = calculate(args.csv.read_bytes(), args.months, args.expect_net)
        text = json.dumps(result, indent=2, ensure_ascii=False) + '\n'
        if args.receipt:
            with args.receipt.open('x', encoding='utf-8', newline='\n') as f:
                f.write(text)
    except (OSError, ValueError, csv.Error) as exc:
        p.exit(2, f'economics: {exc}\n')
    print(text, end='')
    return int(result['status'] == 'mismatch')


if __name__ == '__main__':
    raise SystemExit(main())
