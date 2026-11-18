from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'tools/economics.py'
TABLE = ROOT / 'evals/cases/decision-economics/economics.csv'


def run_cli(table, *args):
    return subprocess.run([sys.executable, str(TOOL), str(table), *args], capture_output=True, text=True)


class EconomicsTest(unittest.TestCase):
    def test_preserved_fixture_and_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            receipt = Path(folder) / 'check.json'
            args = ('--months', '3', '--expect-net', 'paid_pilot', '165000', '--receipt', str(receipt))
            call = run_cli(TABLE, *args)
            self.assertEqual(call.returncode, 0, call.stderr)
            original = receipt.read_bytes()
            r = json.loads(call.stdout)
            self.assertEqual(r, json.loads(original))
            self.assertEqual(r['input_sha256'], sha256(TABLE.read_bytes()).hexdigest())
            self.assertEqual(r['status'], 'match')
            self.assertEqual(r['scenarios']['paid_pilot']['min_accounts_for_net_nonnegative'], 18)
            self.assertEqual(r['scenarios']['manual_service']['net_rub'], '48000.00')
            self.assertEqual(run_cli(TABLE, *args).returncode, 2)
            self.assertEqual(receipt.read_bytes(), original)

    def test_exact_cents_zero_margin_and_claim_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'normalized.csv'
            header = TABLE.read_text().splitlines()[0]
            path.write_text(header + '\nx,1.20,0.97,1.10,0.01,3,scenario\ny,1,1,0,1,3,scenario\n')
            call = run_cli(path, '--months', '2', '--expect-net', 'x', '-0.26')
            self.assertEqual(call.returncode, 1, call.stderr)
            r = json.loads(call.stdout)
            self.assertEqual(r['status'], 'mismatch')
            self.assertEqual(r['comparisons']['x']['calculated_net_rub'], '0.26')
            self.assertEqual(r['scenarios']['x']['min_accounts_for_net_nonnegative'], 3)
            self.assertIsNone(r['scenarios']['y']['min_accounts_for_net_nonnegative'])
            self.assertEqual(json.loads(run_cli(path, '--months', '1').stdout)['status'], 'calculated_only')

    def test_missing_duplicate_or_unsupported_data_never_give_match(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'normalized.csv'
            header, row, other = TABLE.read_text().splitlines()
            for content in (header, header+'\n'+row+'\n'+row, header+'\n'+row+',7',
                            header+'\n'+row.replace(',6000,', ',,'), header+'\n'+row.replace('1500', '-1'),
                            header.replace('monthly_price_rub', 'annual_price_usd')+'\n'+row,
                            header+'\n'+other.replace(',20,', ',1.5,')):
                with self.subTest(content=content):
                    path.write_text(content)
                    result = run_cli(path, '--months', '3')
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, '')
            self.assertEqual(run_cli(TABLE, '--months', '0').returncode, 2)
            self.assertEqual(run_cli(TABLE, '--months', '3', '--expect-net', 'absent', '0').returncode, 2)
