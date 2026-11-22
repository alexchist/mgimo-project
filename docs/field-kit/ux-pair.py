"""One paid/subscription arm per explicit invocation, no retries. Images must be permitted for this provider."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory', type=Path, help='Empty lab except 1.png, 2.png; use a different one for each arm')
    p.add_argument('--instruction', type=Path, help='B only: instruction text included with the common question')
    p.add_argument('--model', required=True)
    p.add_argument('--output', type=Path, required=True, help='NEW directory outside lab')
    a = p.parse_args(); d=a.directory.resolve(); out=a.output.resolve()
    if set(x.name for x in d.iterdir()) != {'1.png','2.png'} or out.is_relative_to(d):
        p.error('Expected a clean image-only folder, and a separate output directory')
    imgs=[d/'1.png',d/'2.png']; question=Path(__file__).with_name('ux-question.txt').read_text(encoding='utf-8')
    instruction=a.instruction.read_text(encoding='utf-8') if a.instruction else ''
    prompt=(instruction+'\n\n' if instruction else '')+question
    out.mkdir(parents=True, exist_ok=False); (out/'prompt.txt').write_text(prompt,encoding='utf-8')
    receipt={'requested_model':a.model, 'effort':'medium', 'images_sha256':[digest(f.read_bytes()) for f in imgs], 'prompt_sha256':digest(prompt.encode()), 'cost':None,'status':'started'}
    target=out/'receipt.json'; target.write_text(json.dumps(receipt,indent=2)+'\n'); t=time.monotonic()
    cmd=['codex','exec','--skip-git-repo-check','--ignore-user-config','--ephemeral','--sandbox','read-only','-m',a.model,'-c','model_reasoning_effort="medium"','--color','never','--json','-i',str(imgs[0]),'-i',str(imgs[1]),'-']
    with (out/'events.jsonl').open('wb') as stdout, (out/'stderr.txt').open('wb') as stderr:
        run=subprocess.run(cmd,input=prompt.encode(),cwd=d,stdout=stdout,stderr=stderr)
    rows=[json.loads(s) for s in (out/'events.jsonl').read_text().splitlines() if s.strip()]
    answer=[r['item']['text'] for r in rows if r.get('type')=='item.completed' and r.get('item',{}).get('type')=='agent_message']; usage=[r.get('usage') for r in rows if r.get('type')=='turn.completed']
    receipt.update(seconds=round(time.monotonic()-t,2), exit_code=run.returncode,usage=usage,status='answered' if answer and usage and run.returncode==0 else 'no_complete_answer'); target.write_text(json.dumps(receipt,indent=2)+'\n'); (out/'answer.md').write_text('\n\n'.join(answer)+'\n',encoding='utf-8');print(receipt);return 0 if receipt['status']=='answered' else 1


if __name__=='__main__':
    raise SystemExit(main())
