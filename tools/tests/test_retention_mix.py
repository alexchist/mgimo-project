import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / 'tools/retention_mix.py'
SOURCE = ROOT / 'evals/cases/mix-review/retention.csv'


class MixComparisonTest(unittest.TestCase):
    def run_csv(self, data, before='april', after='may', period='2', expect_error=None):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'вход.csv'
            path.write_bytes(data)
            result = subprocess.run([sys.executable, str(TOOL), str(path), '--before', before,
                                     '--after', after, '--segment', 'channel', '--period', period],
                                    cwd=folder, capture_output=True, text=True)
            self.assertEqual(list(Path(folder).iterdir()), [path])
            self.assertEqual(path.read_bytes(), data)
        if expect_error:
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn(expect_error, result.stderr)
            self.assertEqual(result.stdout, '')
            return
        self.assertEqual(result.returncode, 0, result.stderr)
        obj = json.loads(result.stdout)
        self.assertEqual(obj['source_sha256'], hashlib.sha256(data).hexdigest())
        return obj

    def test_changing_rates_and_mix(self):
        data = SOURCE.read_bytes().replace(b',', b';')
        r = self.run_csv(data)
        self.assertEqual((r['observed_before_pct'], r['observed_after_pct'], r['after_at_before_mix_pct']), (56, 30, 47.5))
        self.assertEqual((r['observed_delta_pp'], r['within_at_before_mix_pp'], r['mix_at_after_rates_pp']), (-26, -8.5, -17.5))
        self.assertEqual(r['segments'][0]['after']['window_row'], 'row:7')

    def test_orbit(self):
        data = (ROOT / 'examples/demo/sources/originals/S-002__retention.csv').read_bytes()
        r = self.run_csv(data, '2026-08', '2026-09', '4')
        self.assertEqual((r['observed_delta_pp'], r['within_at_before_mix_pp'], r['mix_at_after_rates_pp']), (-17, 1, -18))

    def test_missing_is_not_zero(self):
        data = SOURCE.read_bytes()
        self.run_csv(data.replace(b'may,partners,2,100,200\n', b''), expect_error='Нет строки')
        r = self.run_csv(data.replace(b'may,partners,2,100,200', b'may,partners,2,0,200'))
        self.assertEqual(r['segments'][0]['after']['rate_pct'], 0)
        self.run_csv(data, after='absent', expect_error='Нет строки')

    def test_ambiguous_counts_and_grain(self):
        data = SOURCE.read_bytes()
        for old, new, reason in [(b',2,100,200', b',2,100,175', 'База'), (b',2,100,200', b',2,201,200', 'active_users'),
                                 (b',2,100,200', b',2,1.5,200', 'целые'), (b'cohort,channel', b'cohort,cohort', 'заголовки'),
                                 (b'may,partners,2', b'may,,2', 'ключа')]:
            with self.subTest(reason=reason):
                self.run_csv(data.replace(old, new), expect_error=reason)
        self.run_csv(data + b'may,partners,2,100,200\n', expect_error='row:7 и row:10')

    def test_disallow_different_grain_and_identical_cohort(self):
        data = SOURCE.read_bytes()
        self.run_csv(data.replace(b'cohort_size\n', b'cohort_size,platform\n'), expect_error='лишние поля')
        self.run_csv(data, after='april', expect_error='разные когорты')
        self.run_csv(data, period='0', expect_error='окно наблюдения')


if __name__ == '__main__':
    unittest.main()
