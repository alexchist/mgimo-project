"""Separate Cursor ask-mode lane: fresh empty workspace, text-only request, observed tools disqualify a run."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile
import time

MODEL='grok-4.7-medium'
PREFIX='Answer using only the text below. Do not use tools, read files or browse. Return the JSON decision, not a discussion.\n\n'


def collect(j, out):
    msgs=j['messages']; prompt=PREFIX+'\n\n'.join(m['content'] for m in msgs)
    dest=out/f"{j['name']}.{j['turn']}.json"
    h=lambda x:sha256(x.encode()).hexdigest()
    row={'name':j['name'],'turn':j['turn'],'messages_sha256':h(json.dumps(msgs,ensure_ascii=False,sort_keys=True)),'wire_text_sha256':h(prompt),'utc':datetime.now(timezone.utc).isoformat(),'requested':MODEL,'cost_usd':None}
    with dest.open('x') as f:json.dump(dict(row,status='dispatch_intent'),f)
    start=time.monotonic()
    with tempfile.TemporaryDirectory(prefix='pj-text-') as cwd:
        cmd=['agent','--mode','ask','--model',MODEL,'--print','--output-format','stream-json','--workspace',cwd,prompt]
        r=subprocess.run(cmd,cwd=cwd,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=600)
        events=[json.loads(x) for x in r.stdout.splitlines() if x.strip()]
        init=[x for x in events if x.get('type')=='system' and x.get('subtype')=='init']; results=[x for x in events if x.get('type')=='result']
        end=results[-1] if results else {}; usage=end.get('usage') or {}; tools=[x for x in events if x.get('type')=='tool_call']
        observed=init[-1].get('model','') if init else ''
        row.update(returncode=r.returncode,seconds=round(time.monotonic()-start,3),cli_model=observed,served=observed,finish=end.get('subtype'),answer=end.get('result',''),tool_events=len(tools),cli_usage=usage,usage={'prompt_tokens':usage.get('inputTokens'),'completion_tokens':usage.get('outputTokens'),'total_tokens':None})
        ok=r.returncode==0 and end.get('subtype')=='success' and bool(row['answer']) and not tools and 'grok 4.7' in observed.lower() and 'medium' in observed.lower()
        row['status']='answered' if ok else 'invalid_cli_observation'
        tmp=dest.with_suffix('.tmp'); tmp.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n');tmp.replace(dest)
        print(j['name'],row['status'],observed,flush=True)
        if not ok: raise RuntimeError('Missing usable tool-free Grok result. No automatic retry.')


def main():
    p=argparse.ArgumentParser(); p.add_argument('batch',type=Path); a=p.parse_args(); jobs=json.loads(a.batch.read_text()); out=a.batch.parent
    if len(jobs)>48: raise ValueError('call ceiling exceeded')
    # Waves keep the declared order of each scenario pair (A/B never share a session).
    with ThreadPoolExecutor(max_workers=3) as pool:
        for start in range(0,len(jobs),6):
            wave=jobs[start:start+6]
            for offset in (0,1):
                futures=[pool.submit(collect,j,out) for j in wave[offset::2]]
                for f in futures:f.result()

if __name__=='__main__':main()
