"""Validate the saved GigaChat series and both reader maps, regenerate aggregate observations offline."""
from pathlib import Path
import sys
from collections import Counter

D=Path(__file__).resolve().parent
sys.path.insert(0,str(D.parents[1]/'evals/promptbench'))
from benchmark import HERE, read, sha, score, messages, MODELS, dump
from blind import join

def main():
    runs=D/'runs'; cases={c['id']:c for c in read(HERE/'cases.json')}; design=read(runs/'design.json'); planned=design['schedule']; assert len(planned)==len({tuple(x) for x in planned})==120
    closed=score(runs); assert read(D/'closed.json')==closed
    rows={}; assert len(list(runs.glob('[0-9]*.json')))==120
    for i,(m,c,r,a) in enumerate(planned,1):
        x=read(runs/f'{i:03d}.json'); rows[i]=x; assert (x['seq'],x['model'],x['case'],x['rep'],x['arm'])==(i,m,c,r,a); assert x['status']=='ok' and x['finish']=='stop' and x['answer_sha']==sha(x['answer']); assert x['served'].split(':')[0]==m
        assert [x['system_sha'],x['user_sha']]==[sha(msg['content']) for msg in messages(cases[c],a=='B')]
    raters=[]
    for which in ('one','two'):
        where=D/'audit'/which; mapping=read(where/'mapping.json'); packet=read(where/'packet.json'); marks=read(where/'marks.json'); assert packet['rubric']==(HERE/'rubric.md').read_text(encoding='utf-8')
        assert len(packet['papers'])==len(mapping)==24 and {p['code'] for p in packet['papers']}==set(mapping)
        for p in packet['papers']:
            seq,h=mapping[p['code']]; assert p['case']==rows[seq]['case'] and sha(p['text'])==rows[seq]['answer_sha']==h
        rr=join(runs,mapping,marks); assert {x['seq'] for x in rr}=={i for i,x in rows.items() if x['case'] in ('09','10')};raters.append(rr)
    print('Все 120 ответов, 240 хешей сообщений, 2 x 24 слепые оценки и замороженная рубрика сверены.')
    for m in MODELS:
        s=closed[m];diff=Counter(v for z in s['paired_strict_B_minus_A'] for v in z['deltas']);print(m,'strict B vs A W/T/L',*[diff[i] for i in (1,0,-1)])
        for arm in 'AB':
            print(arm,s['arms'][arm]);
            for idx,rr in enumerate(raters,1):
                subset=[x for x in rr if x['model']==m and x['arm']==arm]; assert len(subset)==4
                print('reader',idx,'pts',sum(x['points'] for x in subset),'/20 risks',sum(x['risk'] for x in subset),'by case', {c:sum(x['points'] for x in subset if x['case']==c) for c in ('09','10')})
    equal=sum(a==b for x,y in zip(*raters) for a,b in zip(x['bits'],y['bits']));print('agreement',equal,'/120; risk agreement',sum(x['risk']==y['risk'] for x,y in zip(*raters)),'/24');print('tokens',sum(x['usage']['total_tokens'] for x in rows.values()),'; seconds',round(sum(x['seconds'] for x in rows.values()),3))
if __name__=='__main__':main()
