"""Exercise check/resume on a disposable copy. Optional argument: older strategist.py."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
cli = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'tools/strategist.py'


def invoke(case, verb, *args):
    p = subprocess.run([sys.executable, str(cli), verb, str(case), *args], capture_output=True, text=True)
    if not p.stdout:
        raise RuntimeError(p.stderr)
    return p.returncode, json.loads(p.stdout)


with tempfile.TemporaryDirectory() as tmp:
    case = Path(tmp) / 'demo'
    shutil.copytree(ROOT / 'examples/demo', case)
    code, revision = invoke(case, 'revise', '--claim', 'E-003', '--status', 'retracted', '--reason', 'Synthetic archive check')
    assert code == 0
    rid = revision['revision_id']
    archived = case / 'revisions' / (rid + '-before') / 'strategy.md'
    current = case / 'strategy.md'
    assert archived.read_bytes() == current.read_bytes()
    for stage in ('intact', 'edit_current', 'edit_archive', 'missing_archived_file'):
        if stage == 'edit_current':
            current.write_bytes(current.read_bytes() + b'\ncurrent note\n')
        elif stage == 'edit_archive':
            original = archived.read_bytes()
            archived.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))  # same size, different content
        elif stage == 'missing_archived_file':
            archived.unlink()
        for verb in ('check', 'resume'):
            code, data = invoke(case, verb)
            s = data if verb == 'check' else data['structural_check']
            item = next((i for i in s.get('revision_snapshots', {}).get('items', []) if i['revision_id'] == rid), {})
            print(json.dumps([stage, verb, code, s['ok'], item.get('status'), [i['code'] for i in item.get('issues', [])]]))
