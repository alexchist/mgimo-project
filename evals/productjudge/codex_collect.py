"""Run the frozen public prompt batch over local Codex app-server stdio (v2).

One ephemeral thread and an empty directory per call; no shared conversations.
A prior intent is never retried. Stop a lane on an ambiguous or failed call.
"""
import argparse
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import time

from cursor_collect import PREFIX


def hashed(s):
    return sha256(s.encode()).hexdigest()


async def one(job, out, model):
    messages = job['messages']
    prompt = PREFIX + '\n\n'.join(m['content'] for m in messages)
    row = dict(name=job['name'], turn=job['turn'], requested=model, cost_usd=None,
               messages_sha256=hashed(json.dumps(messages, ensure_ascii=False, sort_keys=True)),
               wire_text_sha256=hashed(prompt), utc=datetime.now(timezone.utc).isoformat(),
               status='dispatch_intent', effort='medium', tool_events=0, cli='codex app-server',
               terminal=None, answer='', usage={'prompt_tokens':None,'completion_tokens':None,'total_tokens':None})
    dest = out / f"{job['name']}.{job['turn']}.json"
    with dest.open('x') as f:
        json.dump(row, f)
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='pj-codex-') as cwd:
        p = await asyncio.create_subprocess_exec('codex','app-server','--stdio',cwd=cwd,
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,limit=2**20)
        async def send(method, params, i=None):
            msg={'method':method,'params':params}
            if i is not None: msg['id']=i
            p.stdin.write((json.dumps(msg)+'\n').encode()); await p.stdin.drain()
        async def get():
            raw=await p.stdout.readline()
            if not raw: raise ValueError('ended_without_terminal')
            return json.loads(raw)
        async def reply(i):
            while True:
                m=await get()
                if m.get('id')==i:
                    if 'error' in m: raise ValueError('rpc_refused_'+str(m['error'].get('code')))
                    return m['result']
        async def exchange():
            await send('initialize',{'clientInfo':{'name':'pj-bench','version':'1.0'},'capabilities':{}},1); await reply(1)
            await send('initialized',{})
            await send('thread/start',{'cwd':cwd,'model':model,'sandbox':'read-only','approvalPolicy':'never','ephemeral':True,
                'config':{'web_search':'disabled','model_reasoning_effort':'medium','project_doc_max_bytes':0}},2)
            th=await reply(2); row['cli_model']=th.get('model'); row['provider']=th.get('modelProvider'); row['instruction_sources']=len(th.get('instructionSources',[])); row['thread_effort']=th.get('reasoningEffort'); row['thread_id']=th['thread']['id']
            if row['cli_model']!=model or row['instruction_sources']: raise ValueError('unexpected_thread_config')
            await send('turn/start',{'threadId':row['thread_id'],'effort':'medium','input':[{'type':'text','text':prompt}]},3)
            while True:
                m=await get(); par=m.get('params',{}); meth=m.get('method','')
                if 'error' in m: raise ValueError('rpc_error_'+str(m['error'].get('code')))
                if meth=='model/rerouted': raise ValueError('model_rerouted')
                if 'id' in m and meth: raise ValueError('unexpected_server_request')
                if meth=='item/started' and par['item']['type'] not in ('userMessage','agentMessage','reasoning'):
                    row['tool_events']+=1; raise ValueError('non_text_item_'+par['item']['type'])
                if meth=='item/completed' and par['item']['type']=='agentMessage': row['answer']=par['item'].get('text','')
                if meth=='thread/tokenUsage/updated':
                    u=par['tokenUsage']['total']; row['usage']={'prompt_tokens':u.get('inputTokens'),'completion_tokens':u.get('outputTokens'),'total_tokens':u.get('totalTokens')}
                if meth=='turn/completed':
                    row['terminal']=par['turn']['status']; row['turn_id']=par['turn']['id']
                    if row['terminal']!='completed' or not row['answer'].strip(): raise ValueError('no_completed_answer')
                    row.update(served=model,finish='success',status='answered'); return
        try:
            await asyncio.wait_for(exchange(),timeout=360)
        except Exception as e:
            row.update(status='no_usable_result',error_type=type(e).__name__,reason=str(e) if isinstance(e,ValueError) else None)
        finally:
            p.stdin.close()
            try: await asyncio.wait_for(p.wait(),timeout=3)
            except asyncio.TimeoutError:
                p.kill(); await p.wait()
            row['seconds']=round(time.monotonic()-t0,3)
            tmp=dest.with_suffix('.tmp');tmp.write_text(json.dumps(row,ensure_ascii=False)+'\n');tmp.replace(dest)
        print(model,row['name'],row['status'],row.get('reason',''),flush=True)
        return row['status']=='answered'


async def run(args):
    jobs=json.loads(args.batch.read_text()); assert len(jobs)<=48 and 0<=args.start<=args.stop<=48
    groups={}
    for j in jobs[args.start:args.stop]: groups.setdefault(j['name'].rsplit('.',1)[0],[]).append(j)
    queue=iter(groups.values()); stopped=asyncio.Event()
    async def worker():
        while not stopped.is_set():
            group=next(queue,None)
            if group is None: return
            for j in group:
                if stopped.is_set(): return
                if not await one(j,args.batch.parent,args.model): stopped.set(); return
    await asyncio.gather(*(worker() for _ in range(args.workers)))
    return int(stopped.is_set())


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('batch',type=Path);ap.add_argument('--model',required=True)
    ap.add_argument('--start',type=int,default=0);ap.add_argument('--stop',type=int,default=48);ap.add_argument('--workers',type=int,choices=(1,2,3),default=2)
    raise SystemExit(asyncio.run(run(ap.parse_args())))
