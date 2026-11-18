"""Offline exchange for another chat backend; never executes a returned tool or code."""
import argparse
import json
from pathlib import Path
from benchmark import dump, messages, schedule, sha


def export(model, repeats):
    for i,(m,c,r,a) in enumerate(schedule([model],repeats),1):
        msgs=messages(c,a=='B'); yield {'id':f'{i:03}', 'case':c['id'],'rep':r,'arm':a,'payload':{'model':m,'messages':msgs,'temperature':0.2,'max_tokens':1200,'stream':False}}

def ingest(requests, answers, out):
    byid={}; rows=[]; design=[]; models=set(); repeats=set(); seen=set()
    for ans in answers:
        rid=ans['id']
        if rid in byid: raise ValueError('duplicate result id')
        byid[rid]=ans
    for i,q in enumerate(requests,1):
        cid=q['id']; payload=q['payload']; msgs=payload['messages'];m=payload['model']; c=q['case']; a=q['arm']; r=q['rep']; job=[m,c,r,a]; models.add(m);repeats.add(r)
        if cid in seen or job in design: raise ValueError('duplicate request')
        seen.add(cid); design.append(job)
        if cid not in byid:continue   # scorer keeps the planned-but-missing count
        ans=byid.pop(cid); status=ans['status']; text=ans.get('answer'); duration=ans.get('seconds'); usage=ans.get('usage',{})
        if status not in ('ok','incomplete','api_error','not_sent_after_error'):raise ValueError('unknown status')
        if status in ('ok','incomplete') and (not isinstance(text,str) or not isinstance(duration,(int,float)) or duration<0):raise ValueError('response needs raw text and observed seconds')
        if status=='ok' and (not text.strip() or ans.get('finish')!='stop'):raise ValueError('ok needs a completed response')
        rows.append({'seq':i,'case':c,'rep':r,'arm':a,'model':m,'system_sha':sha(msgs[0]['content']),'user_sha':sha(msgs[1]['content']),'status':status,'seconds':duration,'usage':{k:usage.get(k) for k in ('prompt_tokens','completion_tokens','total_tokens','precached_prompt_tokens')},'served':ans.get('served'),'finish':ans.get('finish'),**({'answer':text,'answer_sha':sha(text)} if isinstance(text,str) else {})})
    if byid:raise ValueError('unknown result id')
    if len(models)!=1 or not repeats or repeats!=set(range(1,max(repeats)+1)):raise ValueError('invalid single-model design')
    # Do not grade a partial or modified request design as the current suite.
    if [q for q in export(next(iter(models)),max(repeats))]!=requests:raise ValueError('request set differs from this checkout')
    out.mkdir(parents=True,exist_ok=False)
    (out/'design.json').write_text(dump({'source':'external exchange: reported observations, not a host attestation','model_list':sorted(models),'repeats':max(repeats),'schedule':design})+'\n',encoding='utf-8')
    for row in rows:(out/f"{row['seq']:03d}.json").write_text(dump(row)+'\n',encoding='utf-8')

def jsonlines(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]

if __name__=='__main__':
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='cmd',required=True)
    p=sub.add_parser('export');p.add_argument('model');p.add_argument('--repeats',type=int,default=2)
    p=sub.add_parser('import');p.add_argument('requests',type=Path);p.add_argument('answers',type=Path);p.add_argument('output',type=Path)
    args=parser.parse_args()
    if args.cmd=='export':
        if args.repeats<1:parser.error('repeats must be positive')
        for row in export(args.model,args.repeats):print(json.dumps(row,ensure_ascii=False))
    else:ingest(jsonlines(args.requests),jsonlines(args.answers),args.output)
