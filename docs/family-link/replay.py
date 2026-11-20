"""Check the published run from sources, without a model, network or file writes."""
import csv
import json
import math
import subprocess
import sys
from pathlib import Path
from fractions import Fraction

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def rows(path):
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def main():
    start = ROOT / 'evals/cases/family-link/start'
    update = start.parent / 'update'
    plan = {r['parameter']: int(r['value']) for r in rows(start / 'design.csv')}
    obs = rows(update / 'shadow.csv')
    require(len(obs) == 4 and [int(r['week']) for r in obs] == [1, 2, 3, 4], 'Unexpected weeks')
    events = sum(int(r['trigger_events']) for r in obs)
    unique = sum(int(r['new_unique_eligible_families']) for r in obs)
    flow = Fraction(unique, len(obs))
    possible = flow * plan['recruitment_window']
    short = plan['sample_target'] - possible
    more_weeks = math.ceil(short / flow)
    require((unique, events, flow, possible, short, more_weeks) == (400, 620, 100, 900, 2700, 27), 'Input values differ from the recorded exercise')
    print(f'{unique} families / {len(obs)} weeks = {flow}/week (not {events} events); expected at this flow: {possible}/{plan["sample_target"]}, short {short}; {more_weeks} extra recruitment weeks.')
    before, after = (HERE / 'run' / s for s in ('before', 'after'))
    for case, sources in [(before, list(start.iterdir())), (after, [*start.iterdir(), *update.iterdir()])]:
        for cmd in ('check', 'resume'):
            proc = subprocess.run([sys.executable, str(ROOT / 'tools/strategist.py'), cmd, str(case)], capture_output=True, text=True, check=True)
            result = json.loads(proc.stdout)
            require((result if cmd == 'check' else result['structural_check'])['ok'] is True, f'{case.name}: {cmd} did not pass')
        require(json.loads((case/'project.json').read_text())['business_decision_status'] == 'pending' and not rows(case/'decisions/decisions.csv'), 'Unexpected decision')
        original = case/'sources/originals'
        require(len([p for p in original.iterdir() if not p.name.startswith('.')]) == len(sources), 'Wrong original count')
        for source in sources:
            [p] = original.glob('S-*__' + source.name)
            require(p.read_bytes() == source.read_bytes(), f'Original differs: {source.name}')
        require(all(r.get('synthetic') is True for r in json.loads((case/'sources/index.json').read_text())), 'Missing synthetic label')
    [snapshot] = (after/'revisions').glob('R-*-before')
    for name in ('brief.md', 'options.md', 'strategy.md', 'decision-memo.md', 'state.md'):
        require((before/name).read_bytes() == (snapshot/name).read_bytes(), f'Changed archive: {name}')
    require((before/'decision-memo.md').read_bytes() != (after/'decision-memo.md').read_bytes(), 'The current memo did not change')
    print('Both saved cases reopen; originals match inputs; five archived files match the first session byte for byte. Business decision: pending.')


if __name__ == '__main__':
    main()
