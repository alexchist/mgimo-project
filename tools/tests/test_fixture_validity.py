from pathlib import Path
import subprocess
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]


class FixtureValidityTest(unittest.TestCase):
    def test_office_packages_are_real_zip_packages(self):
        for path in (ROOT / "evals/cases").glob("*/input/*"):
            if path.suffix in {".docx", ".xlsx"}:
                self.assertTrue(zipfile.is_zipfile(path), path)

    def test_pdfs_have_text_layer(self):
        for path in (ROOT / "evals/cases").glob("*/input/*.pdf"):
            result = subprocess.run(["pdftotext", str(path), "-"], capture_output=True, check=True)
            self.assertIn(b"SYNTHETIC", result.stdout, path)

    def test_every_case_is_explicitly_synthetic(self):
        for readme in (ROOT / "evals/cases").glob("*/README.md"):
            self.assertIn("синтет", readme.read_text(encoding="utf-8").lower())


if __name__ == "__main__":
    unittest.main()

