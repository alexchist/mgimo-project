"""Offline bridge to the pinned ProductJudge-Bench; no API calls or credentials."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import random

from pjbench.prompt import build_prompt
from pjbench.providers import Completion, Usage
from pjbench.runner import PredictionRecord, REPAIR_TEMPLATE, parse_spec, run_scenario, write_predictions
from pjbench.schema import load_scenarios


def digest(messages):
    return sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def jobs(split, repository):
    scenarios = sorted(load_scenarios(split), key=lambda s: s.instance_id)
    if len(scenarios) != 24:
        raise ValueError('Expected 24 public scenarios at the pinned revision')
    random.Random(18024).shuffle(scenarios)
    policy = '\n\n'.join((repository / f).read_text(encoding='utf-8') for f in ['BIBLE.md', 'skills/compare-options/SKILL.md'])
    guided = [{'role':'system','content': 'Use the following product guidance only within the explicit scenario policy and required JSON format. No external actions.\n\n' + policy}]
    for n,s in enumerate(scenarios):
        for arm in ('AB' if n % 2 == 0 else 'BA'):
            user = [{'role':'user','content':build_prompt(s)}]
            yield s, arm, (guided if arm == 'B' else []), user


def key(s, arm):
    return f'{s.instance_id}.{arm}'


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_new(path, data):
    with path.open('x', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


def checked_answer(out, name, turn, messages):
    r = load(out / f'{name}.{turn}.json')
    if r['status'] != 'answered' or r['messages_sha256'] != digest(messages):
        raise ValueError(f'Missing answer or changed messages: {name}.{turn}')
    if 'wire_text_sha256' in r:
        from cursor_collect import PREFIX
        text = PREFIX + '\n\n'.join(m['content'] for m in messages)
        if r['wire_text_sha256'] != sha256(text.encode()).hexdigest():
            raise ValueError(f'CLI prompt text does not match the batch: {name}.{turn}')
    return r


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('step', choices=['prepare','repairs','assemble','first']); p.add_argument('split', type=Path); p.add_argument('work', type=Path)
    p.add_argument('--paired-observed',action='store_true',help='Only for a disclosed partial lane; keep scenarios with two observed first answers'); p.add_argument('--model',default='GigaChat-3-Ultra'); args = p.parse_args(); work=args.work
    root=Path(__file__).resolve().parents[2]
    work.mkdir(parents=True, exist_ok=True)
    batch=[]; records=[]
    for s, arm, prefix, user in jobs(args.split, root):
        name=key(s,arm); messages=prefix+user
        if args.step=='prepare':
            batch.append({'name':name,'turn':1,'messages':messages}); continue
        if args.paired_observed:
            paths=[work/f'{s.instance_id}.{a}.1.json' for a in 'AB']
            if not all(p.exists() and load(p)['status']=='answered' for p in paths):continue
        first=checked_answer(work, name, 1, messages)
        if args.step=='first':
            spec,err=parse_spec(first['answer'])
            if first['served'].split(':')[0]!=args.model: raise ValueError('wrong model')
            records.append(PredictionRecord(instance_id=s.instance_id,model=args.model+'/'+arm,
                scenario_hash=s.content_hash(),prompt_sha256=sha256(user[0]['content'].encode()).hexdigest(),
                raw_output=first['answer'],spec=spec,format_compliant=spec is not None,
                repair_attempted=False,error=err,prompt_tokens=first['usage']['prompt_tokens'] or 0,
                completion_tokens=first['usage']['completion_tokens'] or 0,duration_s=first['seconds']))
            continue
        if args.step=='repairs':
            spec,error=parse_spec(first['answer'])
            if spec is None:
                batch.append({'name':name,'turn':2,'messages':messages+[{'role':'assistant','content':first['answer']},{'role':'user','content':REPAIR_TEMPLATE.format(error=error)}]})
            continue
        used=[]
        def replay(msgs):
            r=checked_answer(work, name, len(used)+1, prefix+msgs)
            if r['served'].split(':')[0] != args.model: raise ValueError('wrong model')
            used.append(r)
            return Completion(r['answer'], Usage(r['usage']['prompt_tokens'] or 0, r['usage']['completion_tokens'] or 0))
        rec=run_scenario(s, args.model+'/'+arm, replay)
        if rec.is_provider_failure: raise ValueError(rec.error)
        rec.duration_s=round(sum(r['seconds'] for r in used),3)
        records.append(rec)
    if args.step in ('first','assemble'):
        # Numeric default cost in upstream schema does not attest an invoice.
        write_predictions(records,work/('first.jsonl' if args.step=='first' else 'predictions.jsonl'))
    else:
        write_new(work/(args.step+'.json'), batch)
    print(args.step, len(records) if records else len(batch))

if __name__=='__main__':main()
