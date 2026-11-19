import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / 'examples/demo'


def readback(case, *args, text='Это письмо.\n'):
    return subprocess.run([sys.executable, '-B', str(ROOT/'tools/copydesk.py'), str(case), '-', *args],
                          input=text, capture_output=True, text=True)


class CopyDeskTest(unittest.TestCase):
    def test_final_edit_invalidates_reading_without_a_semantic_verdict(self):
        good = 'В Orbit доступны записанные уроки.'
        seen = readback(DEMO, 'E-014', text=good)
        self.assertEqual(seen.returncode, 0, seen.stderr)
        before = json.loads(seen.stdout)
        self.assertIsNone(before['same_as_seen'])
        self.assertEqual(before['draft'], good)
        fragment, = before['evidence'][0]['fragments']
        self.assertEqual(fragment['address'], 'S-005#p[2]')
        self.assertIn('Еженедельного группового Q&A нет', fragment['quote'])
        stamp = before['view_sha256']
        self.assertIs(json.loads(readback(DEMO, 'E-014', '--seen', stamp, text=good).stdout)['same_as_seen'], True)
        edited = readback(DEMO, 'E-014', '--seen', stamp, text=good + ' Мы напишем вам лично.')
        self.assertEqual(edited.returncode, 1, edited.stderr)
        self.assertIs(json.loads(edited.stdout)['same_as_seen'], False)
        self.assertEqual(json.loads(edited.stdout)['semantic_check'], 'not_performed_by_tool')
        unreviewed = readback(DEMO, 'E-014', text='Каждую неделю будет Q&A.')
        self.assertIsNone(json.loads(unreviewed.stdout)['same_as_seen'])

    def test_changed_claim_is_new_reading_and_retracted_claim_is_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            case = Path(folder)/'case'; shutil.copytree(DEMO, case)
            stamp = json.loads(readback(case, 'E-014').stdout)['view_sha256']
            path = case/'evidence/claims.csv'
            with path.open(encoding='utf-8', newline='') as f:
                rows = list(csv.DictReader(f))
            selected = next(r for r in rows if r['claim_id'] == 'E-014')
            for field, value, code in [('limitations', 'Иные условия', 1), ('status', 'retracted', 2)]:
                selected[field] = value
                with path.open('w', encoding='utf-8', newline='') as f:
                    w = csv.DictWriter(f, fieldnames=selected.keys()); w.writeheader(); w.writerows(rows)
                self.assertEqual(readback(case, 'E-014', '--seen', stamp).returncode, code)

    def test_legacy_deterministic_address_only_and_multiple_facts(self):
        view = readback(DEMO, 'E-014', 'E-001', 'E-015')
        self.assertEqual(view.returncode, 0, view.stderr)
        rows = json.loads(view.stdout)['evidence']
        self.assertEqual(rows[0]['fragments'][0]['address'], 'S-001#page:1,line:2')
        self.assertEqual(len(rows[2]['fragments']), 4)
        for key in ['E-006', 'E-013', 'E-999']:
            bad = readback(DEMO, key)
            self.assertEqual(bad.returncode, 2); self.assertFalse(bad.stdout)

    def test_unreadable_or_changed_evidence_is_not_a_match(self):
        for which in ('stored_path', 'extract_path'):
            with self.subTest(which=which), tempfile.TemporaryDirectory() as folder:
                case = Path(folder)/'case'; shutil.copytree(DEMO, case)
                idx = json.loads((case/'sources/index.json').read_text())
                item = next(i for i in idx if i['source_id'] == 'S-005')
                p = case / item[which]; p.write_bytes(p.read_bytes()+b' ')
                self.assertEqual(readback(case, 'E-014').returncode, 2)
                p.unlink(); self.assertEqual(readback(case, 'E-014').returncode, 2)
