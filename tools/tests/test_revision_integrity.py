from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "tools" / "strategist.py"
REVISION_FIELDS = [
    "revision_id", "recorded_at", "old_claim_id", "old_status", "new_status", "new_claim_id",
    "reason", "evidence_action", "affected_conclusions", "affected_decisions", "affected_commitments",
    "human_review_required", "snapshot_manifest_sha256",
]


class RevisionIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="strategist-revision-integrity-"))
        self.project = self.temp / "case"
        self.run_cli("init", str(self.project), "--slug", "integrity", "--title", "Integrity")

    def tearDown(self):
        shutil.rmtree(self.temp)

    def run_cli(self, *args: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
        result = subprocess.run([sys.executable, str(CLI), *args], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, expected, msg=f"stdout={result.stdout}\nstderr={result.stderr}")
        return result

    def project_state(self) -> dict[str, tuple[bytes, int]]:
        return {
            path.relative_to(self.project).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.project.rglob("*") if path.is_file()
        }

    def make_revision(self) -> None:
        (self.project / "evidence/claims.csv").write_text(
            "claim_id,type,statement,source_ids,locator,period,unit,status,supersedes,limitations\n"
            "E-001,hypothesis,Old hypothesis,,,,,active,,\n",
            encoding="utf-8",
        )
        for name in ("brief.md", "options.md", "strategy.md", "decision-memo.md", "state.md"):
            (self.project / name).write_bytes((f"before {name}\r\n").encode("utf-8"))
        self.run_cli("revise", str(self.project), "--claim", "E-001", "--reason", "Correction")

    def check(self, expected: int = 0) -> dict:
        return json.loads(self.run_cli("check", str(self.project), expected=expected).stdout)

    @staticmethod
    def only_snapshot(result: dict) -> dict:
        items = result["revision_snapshots"]["items"]
        if len(items) != 1:
            raise AssertionError(items)
        return items[0]

    def test_verified_archive_is_not_compared_with_current_documents_and_resume_is_read_only(self):
        self.make_revision()
        (self.project / "brief.md").write_text("current brief after correction\n", encoding="utf-8")
        (self.project / "strategy.md").write_text("current strategy after correction\n", encoding="utf-8")

        before = self.project_state()
        checked = self.check()
        self.assertEqual(self.project_state(), before)
        item = self.only_snapshot(checked)
        self.assertEqual(item["status"], "verified")
        self.assertEqual(item["issues"], [])
        self.assertEqual(
            item["files"],
            ["brief.md", "decision-memo.md", "options.md", "state.md", "strategy.md"],
        )
        self.assertIn("текущие", checked["revision_snapshots"]["scope"])

        resumed = json.loads(self.run_cli("resume", str(self.project)).stdout)
        self.assertEqual(self.project_state(), before)
        self.assertEqual(resumed["structural_check"]["revision_snapshots"], checked["revision_snapshots"])

    def test_modified_missing_file_snapshot_and_manifest_have_distinct_failures(self):
        self.make_revision()
        snapshot = self.project / "revisions/R-001-before"
        archived_brief = snapshot / "brief.md"
        original_brief = archived_brief.read_bytes()
        manifest = self.project / "revisions/R-001-before.manifest.json"
        original_manifest = manifest.read_bytes()

        archived_brief.write_bytes(b"tampered\n")
        before = self.project_state()
        modified = self.check(expected=1)
        self.assertEqual(self.project_state(), before)
        self.assertEqual(self.only_snapshot(modified)["status"], "damaged")
        self.assertEqual(self.only_snapshot(modified)["issues"][0]["code"], "file_modified")
        resumed = json.loads(self.run_cli("resume", str(self.project), expected=1).stdout)
        self.assertEqual(
            resumed["structural_check"]["revision_snapshots"]["items"][0]["issues"][0]["code"],
            "file_modified",
        )

        archived_brief.write_bytes(original_brief)
        archived_brief.unlink()
        missing_file = self.check(expected=1)
        self.assertEqual(self.only_snapshot(missing_file)["issues"][0]["code"], "file_missing")

        archived_brief.write_bytes(original_brief)
        moved_snapshot = snapshot.with_name("R-001-before-temporarily-moved")
        snapshot.rename(moved_snapshot)
        missing_snapshot = self.check(expected=1)
        self.assertEqual(self.only_snapshot(missing_snapshot)["issues"][0]["code"], "snapshot_missing")
        moved_snapshot.rename(snapshot)

        manifest.unlink()
        missing_manifest = self.check(expected=1)
        self.assertEqual(self.only_snapshot(missing_manifest)["issues"][0]["code"], "manifest_missing")
        manifest.write_bytes(original_manifest)
        self.assertEqual(self.only_snapshot(self.check())["status"], "verified")

    def test_legacy_revision_without_durable_inventory_stays_compatible_but_unproven(self):
        self.make_revision()
        log = self.project / "revisions/revision-log.csv"
        with log.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        legacy_fields = REVISION_FIELDS[:-1]
        with log.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=legacy_fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        shutil.rmtree(self.project / "revisions/R-001-before")
        (self.project / "revisions/R-001-before.manifest.json").unlink()

        checked = self.check()
        item = self.only_snapshot(checked)
        self.assertTrue(checked["ok"])
        self.assertEqual(item["status"], "legacy_unverifiable")
        self.assertFalse(item["snapshot_present"])
        self.assertEqual(item["issues"][0]["code"], "legacy_no_manifest_evidence")
        self.assertTrue(any("не доказаны" in warning for warning in checked["warnings"]))

        resumed = json.loads(self.run_cli("resume", str(self.project)).stdout)
        self.assertEqual(
            resumed["structural_check"]["revision_snapshots"]["items"][0]["status"],
            "legacy_unverifiable",
        )

    def test_manifest_cannot_redirect_check_to_an_arbitrary_path(self):
        self.make_revision()
        manifest_path = self.project / "revisions/R-001-before.manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["../../outside.txt"] = {"sha256": "0" * 64, "bytes": 0}
        manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        manifest_path.write_bytes(manifest_bytes)

        log = self.project / "revisions/revision-log.csv"
        with log.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows[0]["snapshot_manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()
        with log.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=REVISION_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

        checked = self.check(expected=1)
        item = self.only_snapshot(checked)
        self.assertEqual(item["status"], "damaged")
        self.assertEqual(item["issues"][0]["code"], "manifest_file_name_invalid")
        self.assertNotIn("../../outside.txt", item["files"])


if __name__ == "__main__":
    unittest.main()
