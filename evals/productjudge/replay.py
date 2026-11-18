"""Offline replay of one published lane. Nothing touches the dataset, provider, or inputs."""
import argparse
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('split', type=Path); p.add_argument('calls', type=Path); p.add_argument('output', type=Path); p.add_argument('--model', required=True); p.add_argument('--partial', action='store_true'); a=p.parse_args()
    out=a.output;out.mkdir(exist_ok=False,parents=True); rows=[json.loads(line) for line in a.calls.read_text().splitlines()]
    bridge=Path(__file__).with_name('bridge.py')
    with TemporaryDirectory() as temp:
        work=Path(temp);seen=set();ids={p.stem for p in a.split.rglob('*.yaml')}
        for r in rows:
            case,arm=r['name'].rsplit('.',1); turn=r['turn']; assert arm in 'AB' and len(arm)==1 and case in ids and turn in (1,2)
            pair=(case,arm,turn); assert pair not in seen; seen.add(pair)
            if r['status']=='answered' and r.get('cli_model'):
                assert r['tool_events']==0 and r['finish']=='success' and r['cli_model']==a.model
            (work/f'{case}.{arm}.{turn}.json').write_text(json.dumps(r))
        for kind in ['first','assemble']:
            subprocess.run([sys.executable,str(bridge),kind,str(a.split),str(work),'--model',a.model]+(['--paired-observed'] if a.partial else []),check=True)
            name='first' if kind=='first' else 'predictions'
            predictions=work/(name+'.jsonl');records=[json.loads(line) for line in predictions.read_text().splitlines()]
            selected={r['instance_id'] for r in records};assert selected and len(records)==len(selected)*2
            if not a.partial: assert selected==ids
            else: print('PARTIAL, matched pairs only; omitted:',sorted(ids-selected))
            actual=a.split
            if a.partial:
                actual=work/'matched-public'; actual.mkdir(exist_ok=True)
                for path in a.split.rglob('*.yaml'):
                    if path.stem in selected:shutil.copyfile(path,actual/path.name)
            if kind=='assemble':shutil.copyfile(predictions,out/'predictions.jsonl')
            subprocess.run([sys.executable,'-m','pjbench.cli','grade',str(predictions),'--scenarios',str(actual),'--out',str(out/(name+'-scores.json'))],check=True)
    a1,b1=json.loads((out/'predictions-scores.json').read_text()); assert a1['model'].endswith('/A') and b1['model'].endswith('/B'); aa={s['instance_id']:s for s in a1['scenarios']};bb={s['instance_id']:s for s in b1['scenarios']};assert aa.keys()==bb.keys()
    with (out/'paired.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['case','family','measure','A','B','detail_A','detail_B'])
        for k in sorted(aa):
            x,y=aa[k],bb[k]
            for prop in ['format_compliant','branch_correct','feasible','regret']:w.writerow([k,x['family'],prop,x[prop],y[prop],'',''])
            def items(s):return {i['gold_id']:i for i in s['items']}
            xx,yy=items(x),items(y)
            for i in sorted(set(xx)|set(yy)):
                left,right=xx.get(i,{}),yy.get(i,{})
                w.writerow([k,x['family'],i+':'+(left or right)['dimension'],left.get('score') if left.get('applicable') else None,right.get('score') if right.get('applicable') else None,left.get('detail'),right.get('detail')])
    print('Replayed',len(aa),'matched scenarios for',a.model)

if __name__=='__main__':main()
