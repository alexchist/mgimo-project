"""Offline replay of the field trials. Verifies files/citations, not model quality."""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def check(ok, msg):
    if not ok: raise ValueError(msg)

def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def obj(p): return json.loads(p.read_text(encoding='utf-8'))

def main():
    base=ROOT/'docs/family-link/run/before'; case=HERE/'handoff/case'
    for cmd in ('resume','check'):
        res=json.loads(subprocess.check_output([sys.executable,str(ROOT/'tools/strategist.py'),cmd,str(case)]));check(res['ok'],cmd)
    [snapshot]=(case/'revisions').glob('R-*-before')
    for name in ['brief.md','options.md','strategy.md','state.md','decision-memo.md']:
        check(digest(base/name)==digest(snapshot/name),f'Archive changed: {name}')
    for name in ('decision-memo.md','strategy.md'): check(digest(case/name)!=digest(base/name),f'Missing new {name}')
    with (case/'decisions/decisions.csv').open(encoding='utf-8',newline='') as f: check(not list(csv.DictReader(f)),'Unexpected decision')
    check(obj(case/'project.json')['business_decision_status']=='pending','expected pending')
    for arm in ('A','B'):
        result=HERE/f'ux-{arm}'; rec=obj(result/'receipt.json'); check(rec['prompt_sha256']==digest(result/'prompt.txt'),'A/B prompt mismatch'); check(rec['images_sha256']==[digest(ROOT/'docs/media-ux/fixtures'/f'family-step-{i}.png') for i in (1,2)],'A/B images mismatch'); check(rec['status']=='answered' and (result/'answer.md').stat().st_size>0,'missing answer')
    gb=HERE/'data-share'; rec=obj(gb/'receipt.json');check([a['sha256'] for a in rec['attachments']]==[digest(gb/f'{n}.png') for n in ('select','confirm')],'GB image mismatch');check(rec['review']['sha256']==digest(gb/'review.md'),'GB answer changed')
    with tempfile.TemporaryDirectory() as t:
        f=Path(t)/'design.csv';src=ROOT/'evals/cases/family-link/start/design.csv';f.write_bytes(src.read_bytes().replace(b'weekly_flow,400,',b'weekly_flow,350,')); r=json.loads(subprocess.check_output([sys.executable,str(ROOT/'tools/source_watch.py'),str(base),'S-003',str(f),'--once']));check(r==obj(HERE/'hook-result.json')['response'],'hook replay differs')
    print('Handoff, five archived documents, no decision, A/B prompts and images, GB review and source-hook readback verified.')

if __name__=='__main__': main()
