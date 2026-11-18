"""Frozen, single-turn paired prompt eval. Preview/export and scoring never contact a provider."""
import argparse
import hashlib
import json
import logging
import math
import random
import statistics
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COMMON = ('Ты помогаешь руководителю цифрового продукта. Ответь по-русски, только по переданным материалам. '
          'Это текстовый режим без файлов, других инструментов и сети. Не заявляй о выполненных внешних действиях. '
          'Следуй требуемой форме ответа; правила работы с файлами применимы только там, где есть такой доступ.')
MODELS = ['GigaChat-3-Pro', 'GigaChat-3-Ultra', 'GigaChat-3-Lightning']

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def dump(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)

def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()

def messages(case, guided):
    system = COMMON
    if guided:
        for rel in ['BIBLE.md',case['guide']]:
            system += '\n\n--- '+rel+' ---\n'+(ROOT / rel).read_text(encoding='utf-8')
    task = case['question'] + (' Верни один объект JSON с этими полями, числа без единиц, без пояснений.' if int(case['id']) <= 8 else '')
    return [{'role':'system','content':system},{'role':'user','content': task+'\n\n'+'\n'.join(f'{k}: {v}' for k,v in case['sources'].items())}]

def schedule(models, repeats):
    cases = read(HERE/'cases.json'); rng=random.Random(18011)
    blocks=[(m,c) for m in models for c in cases]; first={}
    for m in models:
        order=cases.copy(); rng.shuffle(order)
        first.update({(m,c['id']):i%2 for i,c in enumerate(order)})
    for rep in range(repeats):
        rng.shuffle(blocks)
        for m,c in blocks:
            b=(rep+first[m,c['id']])%2
            for arm in (b,1-b):
                yield m,c,rep+1,'B' if arm else 'A'

def run(args):
    from gigachat import GigaChat
    logging.disable(logging.CRITICAL)
    models=args.models; repeats=args.repeats
    if not models or len(set(models))!=len(models) or repeats<1: raise ValueError('invalid design')
    jobs=list(schedule(models,repeats)); out=args.output
    if len(jobs)>args.max_calls: raise ValueError('design exceeds --max-calls')
    out.mkdir(parents=True,exist_ok=False)
    stopped=set(); seen={}
    paths={p for _,c,_,_ in jobs for p in [c['guide'],'BIBLE.md']}
    meta={'sdk':version('gigachat'),'model_list':models,'repeats':repeats,'temperature':0.2,'max_tokens':1200,'seed_order':18011,'corpus':sha((HERE/'cases.json').read_text()),'guides':{p:sha((ROOT/p).read_text()) for p in sorted(paths)},'schedule':[[m,c['id'],r,a] for m,c,r,a in jobs]}
    (out/'design.json').write_text(dump(meta)+'\n',encoding='utf-8')
    opts={'ca_bundle_file':args.ca} if args.ca else {}
    with GigaChat(base_url='https://api.giga.chat/v1', verify_ssl_certs=True, max_retries=0,timeout=60,**opts) as client:
        for i,(m,c,r,a) in enumerate(jobs):
            msgs=messages(c,a=='B'); row={'seq':i+1,'model':m,'case':c['id'],'rep':r,'arm':a,'system_sha':sha(msgs[0]['content']),'user_sha':sha(msgs[1]['content']),'utc':datetime.now(timezone.utc).isoformat()}
            if m in stopped: row.update(status='not_sent_after_error')
            else:
                # Reserve identity before dispatch; never replay existing output directories.
                dest=out/f'{i+1:03d}.json'; dest.write_text(dump(dict(row,status='dispatch_intent'))+'\n',encoding='utf-8'); t=time.monotonic()
                try:
                    res=client.chat(dict(model=m,messages=msgs,temperature=0.2,max_tokens=1200,stream=False)); choice=res.choices[0]
                    text=choice.message.content or ''; finish=choice.finish_reason
                    row.update(status='ok' if finish=='stop' and text.strip() else 'incomplete',answer=text,answer_sha=sha(text),served=res.model,finish=finish,usage={k:getattr(res.usage,k,None) for k in ('prompt_tokens','completion_tokens','precached_prompt_tokens','total_tokens')},seconds=round(time.monotonic()-t,3))
                except Exception as exc:
                    row.update(status='api_error',error=type(exc).__name__,seconds=round(time.monotonic()-t,3)); stopped.add(m)
                if m not in seen: print(m,row['status'],row.get('served',row.get('error')),flush=True);seen[m]=True
            (out/f'{i+1:03d}.json').write_text(dump(row)+'\n',encoding='utf-8')
    print('attempted',len(jobs)-sum(read(p)['status']=='not_sent_after_error' for p in out.glob('[0-9]*.json')), 'of',len(jobs))

def parse_answer(text):
    text=text.strip(); lines=text.splitlines()
    if len(lines)>=3 and lines[0].lower() in ('```json','```') and lines[-1]=='```':text='\n'.join(lines[1:-1])
    def unique(items):
        if len(items)!=len(dict(items)):raise ValueError('duplicate field')
        return dict(items)
    try: obj=json.loads(text,object_pairs_hook=unique)
    except ValueError:return None
    return obj if isinstance(obj,dict) else None

def match(got,want):
    if type(want) in (int,float):return type(got) in (int,float) and math.isfinite(got) and abs(got-want)<1e-6
    return type(got) is type(want) and got==want

def grades(row,key):
    obj=parse_answer(row.get('answer','')) if row['status']=='ok' else None
    return [bool(obj is not None and k in obj and match(obj[k],v)) for k,v in key.items()]

def score(folder):
    keys=read(HERE/'keys.json'); design=read(folder/'design.json'); rows=[read(p) for p in sorted(folder.glob('[0-9]*.json'))]; ix={}
    for row in rows:
        k=(row['model'],row['case'],row['rep'],row['arm']); assert k not in ix
        if 'answer' in row: assert sha(row['answer'])==row['answer_sha']
        ix[k]=row
    planned={tuple(x) for x in design['schedule']}; assert set(ix)<=planned
    summary={}
    for m in design['model_list']:
        byarm={}; pairs=[]
        for a in ('A','B'):
            items=[v for k,v in ix.items() if k[0]==m and k[3]==a]; observed=[v for v in items if v['status'] in ('ok','incomplete')]; closed=[v for v in observed if v['case'] in keys]; checks=[grades(v,keys[v['case']]) for v in closed]
            byarm[a]={'observed':len(observed),'closed':len(closed),'json_ok':sum(v['status']=='ok' and parse_answer(v['answer']) is not None for v in closed),'strict':sum(map(all,checks)),'fields':sum(sum(z) for z in checks),'fields_total':sum(map(len,checks)),'seconds_median':statistics.median(v['seconds'] for v in observed) if observed else None,'tokens':{col:(sum(v['usage'][col] for v in observed) if observed and all(v['usage'][col] is not None for v in observed) else None) for col in ('prompt_tokens','completion_tokens','total_tokens')}}
        for c,key in keys.items():
            diffs=[]
            for r in range(1,design['repeats']+1):
                x,y=[ix.get((m,c,r,a),{}) for a in 'AB']; eligible=('ok','incomplete')
                if x.get('status') in eligible and y.get('status') in eligible:
                    assert x['user_sha']==y['user_sha']; diffs.append(int(all(grades(y,key)))-int(all(grades(x,key))))
            if diffs:pairs.append({'case':c,'deltas':diffs})
        summary[m]={'arms':byarm,'paired_strict_B_minus_A':pairs,'statuses':{s:sum(v['status']==s for k,v in ix.items() if k[0]==m) for s in sorted({v['status'] for v in ix.values()})},'missing_rows':sum(k not in ix for k in planned if k[0]==m)}
    return summary

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd',required=True)
    q=sub.add_parser('run');q.add_argument('output',type=Path);q.add_argument('--ca');q.add_argument('--models',nargs='+',default=MODELS);q.add_argument('--repeats',type=int,default=2);q.add_argument('--max-calls',type=int,required=True)
    q=sub.add_parser('score');q.add_argument('output',type=Path)
    q=sub.add_parser('prompt');q.add_argument('case');q.add_argument('arm',choices=['A','B'])
    args=p.parse_args()
    if args.cmd=='run':run(args)
    elif args.cmd=='score':print(dump(score(args.output)))
    else:print(dump(messages(next(c for c in read(HERE/'cases.json') if c['id']==args.case),args.arm=='B')))
if __name__=='__main__':main()
