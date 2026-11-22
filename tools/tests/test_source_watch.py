import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / 'docs/family-link/run/before'
TOOL = ROOT / 'tools/source_watch.py'


class SourceHook(unittest.TestCase):
    def test_event_from_real_edit(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / 'copy.csv'
            original = (ROOT / 'evals/cases/family-link/start/design.csv').read_bytes()
            src.write_bytes(original)
            cmd = [sys.executable, str(TOOL), str(CASE), 'S-003', str(src)]
            with subprocess.Popen(cmd + ['--until-change', '--interval', '0.1'], stdout=subprocess.PIPE, text=True) as p:
                try:
                    self.assertEqual(json.loads(p.stdout.readline())['event'], 'matches_import')
                    src.write_bytes(original + b'\n')
                    out, _ = p.communicate(timeout=8)
                    event = json.loads(out)
                    self.assertEqual(event['event'], 'changed')
                    self.assertEqual(event['observed_sha256'], hashlib.sha256(src.read_bytes()).hexdigest())
                    self.assertIn('C-004', event['review']['conclusions']); self.assertNotIn('C-003', event['review']['conclusions'])
                    self.assertIn(16, event['review']['document_lines']['decision-memo.md']); self.assertEqual(event['review']['decisions'], [])
                finally:
                    if p.poll() is None: p.kill()
            src.unlink()
            self.assertEqual(json.loads(subprocess.check_output(cmd + ['--once']))['event'], 'missing')
            bad = subprocess.run([sys.executable, str(TOOL), str(CASE), 'S-123', str(src), '--once'], capture_output=True)
            self.assertNotEqual(bad.returncode, 0); self.assertFalse(bad.stdout)

    def test_claude_only_delivers_a_relevant_edit(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'design.csv'; f.write_text('changed')
            def fire(name, path, case=CASE):
                event = {'hook_event_name':'PostToolUse','tool_name':name,'tool_input':{'file_path':str(path)}}
                return subprocess.check_output([sys.executable,str(TOOL),str(case),'S-003',str(f),'--claude-hook'],input=json.dumps(event),text=True)
            self.assertEqual(fire('Read',f), ''); self.assertEqual(fire('Edit',f.parent/'other',f.parent/'absent'), '')
            hook=json.loads(fire('Write',f))['hookSpecificOutput']; self.assertEqual(hook['hookEventName'],'PostToolUse')
            self.assertIn(16,json.loads(hook['additionalContext'])['review']['document_lines']['decision-memo.md'])
