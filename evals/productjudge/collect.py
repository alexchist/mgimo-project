"""Network leg. Reads only rendered messages; never imports the benchmark or reads YAML."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from pathlib import Path
import time
from gigachat import GigaChat


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('batch', type=Path); p.add_argument('--ca'); p.add_argument('--max-calls', type=int, required=True); p.add_argument('--model',choices=['GigaChat-3-Ultra','GigaChat-3-Pro','GigaChat-3-Lightning'],default='GigaChat-3-Ultra'); a=p.parse_args()
    logging.disable(logging.CRITICAL)
    jobs=json.loads(a.batch.read_text()); out=a.batch.parent
    if len(jobs)>a.max_calls: raise SystemExit('call ceiling exceeded')
    if not jobs: print('no calls'); return
    with GigaChat(base_url='https://api.giga.chat/v1', verify_ssl_certs=True, ca_bundle_file=a.ca, max_retries=0, timeout=90) as client:
        for j in jobs:
            dest=out/f"{j['name']}.{j['turn']}.json"; msgs=j['messages']
            ident=sha256(json.dumps(msgs,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            row={'name':j['name'],'turn':j['turn'],'utc':datetime.now(timezone.utc).isoformat(),'messages_sha256':ident,'cost_usd':None}
            with dest.open('x') as f: json.dump(dict(row,status='dispatch_intent'),f)
            start=time.monotonic()
            try:
                r=client.chat(dict(model=a.model,messages=msgs,temperature=0.2,max_tokens=2048,stream=False)); c=r.choices[0]
                row.update(status='answered',answer=c.message.content or '',served=r.model,finish=c.finish_reason,usage={k:getattr(r.usage,k,None) for k in ['prompt_tokens','completion_tokens','total_tokens']})
            except Exception as exc:
                row.update(status='provider_error',error=type(exc).__name__)
            row['seconds']=round(time.monotonic()-start,3)
            temp=dest.with_suffix('.tmp');temp.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n');temp.replace(dest)
            print(row['name'],row['turn'], row['status'], row.get('served',row.get('error')),flush=True)
            if row['status']!='answered' or row['served'].split(':')[0]!=a.model:raise SystemExit('Stopped; no automatic replay')

if __name__=='__main__':main()
