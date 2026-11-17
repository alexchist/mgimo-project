from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "tools" / "strategist.py"
FIXTURES = ROOT / "evals" / "cases"
SPEC = importlib.util.spec_from_file_location("strategist_tool", CLI)
TOOL = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(TOOL)


class StrategistCLITest(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="strategist-test-"))
        self.project = self.temp / "проект с пробелом"
        self.run_cli("init", str(self.project), "--slug", "test", "--title", "Тест")

    def tearDown(self):
        shutil.rmtree(self.temp)

    def run_cli(self, *args: str, expected: int = 0):
        result = subprocess.run([sys.executable, str(CLI), *args], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, expected, msg=f"stdout={result.stdout}\nstderr={result.stderr}")
        return result

    def test_mixed_format_ingest_has_precise_locators_and_gaps(self):
        files = [
            FIXTURES / "retention/input/brief.pdf",
            FIXTURES / "new-service/input/research-notes.docx",
            FIXTURES / "retention/input/retention.csv",
            FIXTURES / "retention/input/events.xlsx",
            FIXTURES / "retention/input/research-site.html",
        ]
        for path in files:
            self.run_cli("ingest", str(self.project), str(path), "--permission", "synthetic", "--synthetic")
        index = json.loads((self.project / "sources/index.json").read_text(encoding="utf-8"))
        self.assertEqual([item["kind"] for item in index], ["pdf", "docx", "csv", "xlsx", "html"])
        extracts = "\n".join((self.project / item["extract_path"]).read_text(encoding="utf-8") for item in index)
        for locator in ["page:1,line:", "paragraph:1", "row:2,column:cohort", "definitions!A1", "h1[1]"]:
            self.assertIn(locator, extracts)
        self.assertIn("cached value", extracts)
        self.assertIn("prompt-injection test", extracts)
        check = json.loads(self.run_cli("check", str(self.project)).stdout)
        self.assertTrue(check["ok"])
        self.assertGreaterEqual(len(check["warnings"]), 2)
        self.assertEqual(check["completion"]["artifact_stage"], "scaffold")
        self.assertTrue(check["structural_only"])

    def test_init_sets_created_at_and_missing_canonical_files_fail(self):
        metadata = json.loads((self.project / "project.json").read_text(encoding="utf-8"))
        self.assertTrue(metadata["created_at"])
        self.assertEqual(metadata["schema_version"], "1.1")
        self.assertEqual(metadata["artifact_stage"], "scaffold")
        self.assertTrue((self.project / "decision-memo.md").is_file())
        self.assertEqual(
            (self.project / "decision-memo.md").read_bytes(),
            (ROOT / "templates/project/decision-memo.md").read_bytes(),
        )
        (self.project / "sources/index.json").unlink()
        (self.project / "evidence/claims.csv").unlink()
        (self.project / "decision-memo.md").unlink()
        result = json.loads(self.run_cli("check", str(self.project), expected=1).stdout)
        self.assertTrue(any("sources/index.json" in error for error in result["errors"]))
        self.assertTrue(any("evidence/claims.csv" in error for error in result["errors"]))
        self.assertTrue(any("decision-memo.md" in error for error in result["errors"]))
        shutil.copy2(ROOT / "templates/project/sources/index.json", self.project / "sources/index.json")
        shutil.copy2(ROOT / "templates/project/evidence/claims.csv", self.project / "evidence/claims.csv")
        metadata["schema_version"] = "1.0"
        (self.project / "project.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        legacy_check = json.loads(self.run_cli("check", str(self.project)).stdout)
        self.assertTrue(legacy_check["ok"])

    def test_unknown_schema_versions_are_not_reported_as_valid(self):
        path = self.project / "project.json"
        metadata = json.loads(path.read_text(encoding="utf-8"))
        for value in ["1.2", "1.1.0", "unknown", 1.1, None, [], {}]:
            with self.subTest(schema=value):
                metadata["schema_version"] = value
                path.write_text(json.dumps(metadata), encoding="utf-8")
                result = json.loads(self.run_cli("check", str(self.project), expected=1).stdout)
                self.assertTrue(any("schema_version" in error for error in result["errors"]))

    def test_markdown_ingest_preserves_original_and_line_locators(self):
        for suffix in [".md", ".markdown"]:
            source = self.temp / ("source" + suffix)
            source.write_text("# Заголовок\n\nЦена 4800 RUB\n[ссылка](https://example.com)\n", encoding="utf-8")
            self.run_cli("ingest", str(self.project), str(source), "--permission", "synthetic", "--synthetic")
            entry = json.loads((self.project / "sources/index.json").read_text(encoding="utf-8"))[-1]
            self.assertEqual((self.project / entry["stored_path"]).read_bytes(), source.read_bytes())
            extract = (self.project / entry["extract_path"]).read_text(encoding="utf-8")
            self.assertIn("line:3", extract)
            self.assertIn("4800 RUB", extract)
            self.assertIn("https://example.com", extract)
            self.assertTrue(json.loads(self.run_cli("check", str(self.project)).stdout)["ok"])

    def test_csv_multiline_short_rows_and_shared_dialect(self):
        multiline = self.temp / "multiline.csv"
        multiline.write_text('a,b\n"first\nsecond",2\n', encoding="utf-8")
        self.run_cli("ingest", str(self.project), str(multiline), "--permission", "synthetic", "--synthetic")
        extract = (self.project / "sources/extracts/S-001.md").read_text(encoding="utf-8")
        self.assertIn("first second", extract)
        self.assertIn("lines:2-3", extract)
        short = self.temp / "short.csv"
        short.write_text("a,b\n1\n", encoding="utf-8")
        profile = self.project / "analysis/short.json"
        self.run_cli("profile", str(short), "--output", str(profile))
        data = json.loads(profile.read_text(encoding="utf-8"))
        self.assertEqual(data["columns"]["b"]["missing"], 1)
        semicolon = self.temp / "retention-semicolon.csv"
        semicolon.write_text("cohort;period;active_users;cohort_size\nx;4;2;4\n", encoding="utf-8")
        output = self.project / "analysis/semicolon.csv"
        self.run_cli("retention", str(semicolon), "--output", str(output))
        self.assertIn("0.500000", output.read_text(encoding="utf-8"))

    def test_csv_schema_rejects_ambiguous_headers_extra_cells_and_empty_retention(self):
        duplicate = self.temp / "duplicate.csv"
        duplicate.write_text("a,a\n1,2\n", encoding="utf-8")
        for command in [
            ("ingest", str(self.project), str(duplicate)),
            ("profile", str(duplicate), "--output", str(self.project / "analysis/duplicate.json")),
        ]:
            result = self.run_cli(*command, expected=2)
            self.assertIn("повторяющиеся заголовки", result.stderr)

        empty = self.temp / "empty-header.csv"
        empty.write_text("a,\n1,2\n", encoding="utf-8")
        result = self.run_cli("profile", str(empty), "--output", str(self.project / "analysis/empty.json"), expected=2)
        self.assertIn("пустые заголовки", result.stderr)

        extra = self.temp / "extra.csv"
        extra.write_text("cohort,period,active_users,cohort_size\nx,4,2,4,unexpected\n", encoding="utf-8")
        extract_result = self.run_cli("ingest", str(self.project), str(extra), "--permission", "synthetic", "--synthetic")
        self.assertIn("лишние", extract_result.stdout)
        for command in [
            ("profile", str(extra), "--output", str(self.project / "analysis/extra.json")),
            ("retention", str(extra), "--output", str(self.project / "analysis/extra-retention.csv")),
        ]:
            result = self.run_cli(*command, expected=2)
            self.assertIn("лишние ячейки", result.stderr)

        header_only = self.temp / "header-only.csv"
        header_only.write_text("cohort,period,active_users,cohort_size\n", encoding="utf-8")
        result = self.run_cli("retention", str(header_only), "--output", str(self.project / "analysis/empty-retention.csv"), expected=1)
        self.assertIn("не содержит строк данных", result.stderr)
        self.assertFalse((self.project / "analysis/empty-retention.csv").exists())

    def test_html_div_plain_text_and_query_redaction_boundaries(self):
        page = self.temp / "page.html"
        page.write_text("<div>Important number 42</div><p>Other</p>", encoding="utf-8")
        self.run_cli("ingest", str(self.project), str(page), "--permission", "synthetic", "--synthetic")
        extract = (self.project / "sources/extracts/S-001.md").read_text(encoding="utf-8")
        self.assertIn("Important number 42", extract)
        self.assertIn("статический HTML", extract)
        records, gaps = TOOL.extract_plain_bytes(b"<h1>not html</h1>\nvalue")
        self.assertEqual(records[0], ("line:1", "<h1>not html</h1>"))
        self.assertTrue(any("разметка, ссылки и вложенные media не интерпретировались" in gap for gap in gaps))
        sanitized, redacted = TOOL.sanitized_url("https://example.com/a?lang=ru&token=secret&page=2#x")
        self.assertEqual(sanitized, "https://example.com/a?lang=ru&page=2")
        self.assertEqual(redacted, ["token"])
        windows = self.run_cli("ingest", str(self.project), r"C:\missing\file.csv", expected=2)
        self.assertIn("Файл не найден", windows.stderr)
        self.assertNotIn("HTTPS", windows.stderr)

    def test_retention_is_reproducible(self):
        output = self.project / "analysis/retention.csv"
        self.run_cli("retention", str(FIXTURES / "retention/input/retention.csv"), "--output", str(output))
        with output.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[1]["retention_rate"], "0.400000")
        self.assertEqual(rows[-1]["retention_rate"], "0.110000")
        self.assertTrue(output.with_suffix(".csv.method.md").is_file())
        with output.with_suffix(".csv.cohort-summary.csv").open(encoding="utf-8", newline="") as handle:
            summary = list(csv.DictReader(handle))
        self.assertEqual(summary[1]["retention_rate"], "0.340000")
        self.assertEqual(summary[3]["retention_rate"], "0.170000")

    def test_revision_marks_impact_but_preserves_decision(self):
        claims = self.project / "evidence/claims.csv"
        claims.write_text("claim_id,type,statement,source_ids,locator,period,unit,status,supersedes,limitations\nE-001,hypothesis,Причина X,,,2026,,active,,\n", encoding="utf-8")
        conclusions = self.project / "evidence/conclusions.csv"
        conclusions.write_text("conclusion_id,statement,evidence_ids,alternative_explanations,change_condition,status,review_needed\nC-001,Вывод,E-001,Причина Y,Новый факт,active,no\n", encoding="utf-8")
        decisions = self.project / "decisions/decisions.csv"
        original = "decision_id,recorded_at,decider,decision_kind,status,chosen_option,conclusion_ids,rejected_options,revisit_on,revisit_if,notes\nD-001,2026-01-01T00:00:00+00:00,Тестовый сценарий,simulated,simulated,O-2,C-001,O-1,,,не согласие владельца\n"
        decisions.write_text(original, encoding="utf-8")
        commitments = self.project / "commitments.csv"
        commitments.write_text("commitment_id,decision_id,description,owner,status,due_on,metric,review_condition,confirmed_by,confirmed_at\nK-001,D-001,Проверить,,proposed,,,,,\n", encoding="utf-8")
        documents = ("brief.md", "options.md", "strategy.md", "decision-memo.md", "state.md")
        before = {}
        for name in documents:
            before[name] = ("Старая версия " + name + "\r\n").encode("utf-8")
            (self.project / name).write_bytes(before[name])
        result = json.loads(self.run_cli("revise", str(self.project), "--claim", "E-001", "--reason", "Новые данные", "--new-statement", "Причина Y", "--type", "hypothesis").stdout)
        for name in documents:
            self.assertEqual((self.project / "revisions/R-001-before" / name).read_bytes(), before[name])
            (self.project / name).write_text("Новая версия", encoding="utf-8")
        self.run_cli("revise", str(self.project), "--claim", "E-002", "--reason", "Ещё данные")
        for name in documents:
            self.assertEqual((self.project / "revisions/R-001-before" / name).read_bytes(), before[name])
            self.assertEqual((self.project / "revisions/R-002-before" / name).read_text(encoding="utf-8"), "Новая версия")
        self.assertEqual(result["affected_decisions"], ["D-001"])
        self.assertEqual(result["affected_commitments"], ["K-001"])
        self.assertEqual(decisions.read_text(encoding="utf-8"), original)
        self.assertIn(",yes\n", conclusions.read_text(encoding="utf-8"))
        self.assertIn("Код не менял", (self.project / "revisions/R-001.md").read_text(encoding="utf-8"))

    def test_revision_snapshot_rollback_and_retry_preserve_bytes(self):
        claims = self.project / "evidence/claims.csv"
        original = b"claim_id,type,statement,source_ids,locator,period,unit,status,supersedes,limitations\nE-001,hypothesis,Old,,,,,active,,\n"
        claims.write_bytes(original)
        old_memo = b"old memo\r\n"
        (self.project / "decision-memo.md").write_bytes(old_memo)
        args = SimpleNamespace(project=str(self.project), claim="E-001", allow_nonactive=False,
                               status="retracted", new_statement="", reason="test")
        write = TOOL.atomic_bytes
        def interrupted(path, data):
            if path == claims:
                raise OSError("simulated interruption after snapshots")
            write(path, data)
        with patch.object(TOOL, "atomic_bytes", side_effect=interrupted):
            with self.assertRaises(OSError):
                TOOL.command_revise(args)
        snapshot = self.project / "revisions/R-001-before/decision-memo.md"
        self.assertEqual(snapshot.read_bytes(), old_memo)
        self.assertEqual(claims.read_bytes(), original)
        self.run_cli("revision-recover", str(self.project), "--revision", "R-001", "--mode", "rollback")
        self.assertFalse(snapshot.exists())
        orphan = snapshot.parent / "temporary-left-by-hard-stop"
        orphan.write_bytes(b"unrelated temporary bytes")
        self.run_cli("revise", str(self.project), "--claim", "E-001", "--reason", "retry")
        self.assertEqual(orphan.read_bytes(), b"unrelated temporary bytes")
        self.assertEqual(snapshot.read_bytes(), old_memo)
        self.assertEqual((self.project / "decision-memo.md").read_bytes(), old_memo)

    def test_fact_revision_requires_explicit_evidence_reuse(self):
        source = FIXTURES / "positioning/input/message-test.csv"
        self.run_cli("ingest", str(self.project), str(source), "--permission", "synthetic", "--synthetic")
        claims = self.project / "evidence/claims.csv"
        claims.write_text("claim_id,type,statement,source_ids,locator,period,unit,status,supersedes,limitations\nE-001,fact,Старый факт,S-001,\"S-001#row:2,column:variant\",2026,,active,,\n", encoding="utf-8")
        failure = self.run_cli("revise", str(self.project), "--claim", "E-001", "--reason", "Уточнение", "--new-statement", "Новый факт", expected=1)
        self.assertIn("явные новые citations", failure.stderr)
        result = self.run_cli("revise", str(self.project), "--claim", "E-001", "--reason", "Уточнение", "--new-statement", "Новый факт", "--reuse-evidence", "--reuse-reason", "Тот же фрагмент уточняет формулировку")
        self.assertIn("R-001", result.stdout)
        self.assertIn("Evidence reused", claims.read_text(encoding="utf-8"))

    def test_interrupted_operation_becomes_unknown_and_is_not_finished_twice(self):
        operation = self.run_cli("operation", str(self.project), "start", "--tool", "web", "--inputs", "https://example.com").stdout.strip()
        recovery = json.loads(self.run_cli("recover", str(self.project)).stdout)
        self.assertEqual(recovery["marked_outcome_unknown"], [operation])
        self.run_cli("operation", str(self.project), "finish", "--id", operation, expected=1)
        resolution = self.run_cli("operation", str(self.project), "resolve", "--id", operation, "--resolution", "confirmed_succeeded", "--cost-status", "not_applicable", "--notes", "Артефакт проверен").stdout.strip()
        self.assertNotEqual(resolution, operation)
        with (self.project / "runs/operations.csv").open(encoding="utf-8", newline="") as handle:
            operations = list(csv.DictReader(handle))
        self.assertEqual(operations[0]["status"], "outcome_unknown")
        self.assertEqual(operations[1]["related_operation_id"], operation)
        check = json.loads(self.run_cli("check", str(self.project)).stdout)
        self.assertTrue(any("исторически неизвестен" in warning for warning in check["warnings"]))
        self.assertTrue(any("стоимость неизвестна" in warning for warning in check["warnings"]))

    def test_hash_change_is_detected(self):
        source = FIXTURES / "positioning/input/message-test.csv"
        self.run_cli("ingest", str(self.project), str(source), "--permission", "synthetic", "--synthetic")
        index = json.loads((self.project / "sources/index.json").read_text(encoding="utf-8"))
        stored = self.project / index[0]["stored_path"]
        stored.write_text(stored.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        result = json.loads(self.run_cli("check", str(self.project), expected=1).stdout)
        self.assertFalse(result["ok"])
        self.assertTrue(any("hash не совпадает" in error for error in result["errors"]))

    def test_extract_hash_and_source_qualified_locator_are_checked(self):
        source = FIXTURES / "positioning/input/message-test.csv"
        self.run_cli("ingest", str(self.project), str(source), "--permission", "synthetic", "--synthetic")
        claims = self.project / "evidence/claims.csv"
        claims.write_text("claim_id,type,statement,source_ids,locator,period,unit,status,supersedes,limitations\nE-001,fact,Test,S-001,\"S-001#row:999,column:variant\",2026,,active,,\n", encoding="utf-8")
        result = json.loads(self.run_cli("check", str(self.project), expected=1).stdout)
        self.assertTrue(any("locator" in error and "отсутствует" in error for error in result["errors"]))
        claims.write_text("claim_id,type,statement,source_ids,locator,period,unit,status,supersedes,limitations\nE-001,fact,Test,S-001,\"S-001#row:2,column:variant\",2026,,active,,\n", encoding="utf-8")
        self.assertTrue(json.loads(self.run_cli("check", str(self.project)).stdout)["ok"])
        extract = self.project / "sources/extracts/S-001.md"
        extract.write_text(extract.read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
        result = json.loads(self.run_cli("check", str(self.project), expected=1).stdout)
        self.assertTrue(any("hash извлечения" in error for error in result["errors"]))

    def test_failed_ingest_is_logged_without_orphan_source(self):
        broken = self.temp / "broken.docx"
        broken.write_bytes(b"not a zip")
        self.run_cli("ingest", str(self.project), str(broken), expected=2)
        self.assertEqual(list((self.project / "sources/originals").glob("S-*")), [])
        self.assertEqual(list((self.project / "sources/extracts").glob("S-*")), [])
        with (self.project / "runs/ingest-failures.csv").open(encoding="utf-8", newline="") as handle:
            failures = list(csv.DictReader(handle))
        self.assertEqual(failures[0]["source_id"], "S-001")
        check = json.loads(self.run_cli("check", str(self.project)).stdout)
        self.assertTrue(check["ok"])
        self.assertEqual(check["counts"]["ingest_failures"], 1)

    def test_pending_ingest_and_revision_are_detectable_and_recoverable(self):
        staging = self.project / "sources/.staging"
        staging.mkdir(parents=True, exist_ok=True)
        stage_source = staging / "S-001.source"
        stage_extract = staging / "S-001.extract.md"
        stage_source.write_text("value", encoding="utf-8")
        stage_extract.write_text("# Извлечение S-001\n\n## Фрагменты\n\n- `line:1` — value\n", encoding="utf-8")
        entry = {"source_id": "S-001", "kind": "txt", "title": "value", "origin": "synthetic",
                 "stored_path": "sources/originals/S-001__value.txt", "extract_path": "sources/extracts/S-001.md",
                 "sha256": TOOL.sha256(stage_source), "extract_sha256": TOOL.sha256(stage_extract),
                 "retrieved_at": "2026-01-01T00:00:00+00:00", "permission": "synthetic", "synthetic": True,
                 "record_count": 1, "gaps": [], "status": "active"}
        manifest = {"source_id": "S-001", "created_at": "2026-01-01T00:00:00+00:00", "entry": entry,
                    "stage_source": "sources/.staging/S-001.source", "stage_extract": "sources/.staging/S-001.extract.md",
                    "final_source": entry["stored_path"], "final_extract": entry["extract_path"]}
        (staging / "S-001.pending.json").write_text(json.dumps(manifest), encoding="utf-8")
        result = json.loads(self.run_cli("check", str(self.project), expected=1).stdout)
        self.assertTrue(any("Незавершённый ingest" in error for error in result["errors"]))
        stage_source.write_text("human edit", encoding="utf-8")
        rejected = self.run_cli("ingest-recover", str(self.project), "--source-id", "S-001", "--mode", "complete", expected=1)
        self.assertIn("изменён после pending manifest", rejected.stderr)
        self.assertTrue((staging / "S-001.pending.json").exists())
        self.assertEqual(json.loads((self.project / "sources/index.json").read_text(encoding="utf-8")), [])
        stage_source.write_text("value", encoding="utf-8")
        self.run_cli("ingest-recover", str(self.project), "--source-id", "S-001", "--mode", "complete")
        self.assertTrue(json.loads(self.run_cli("check", str(self.project)).stdout)["ok"])

        state = self.project / "state.md"
        brief = self.project / "brief.md"
        state_before = state.read_text(encoding="utf-8")
        brief_before = brief.read_text(encoding="utf-8")
        state_after = "revision state\n"
        brief_after = "revision brief\n"
        pending_revision = self.project / "revisions/.pending-R-001.json"
        pending_revision.write_text(json.dumps({"revision_id": "R-001", "files": {
            "state.md": {"existed": True, "before": state_before, "after": state_after},
            "brief.md": {"existed": True, "before": brief_before, "after": brief_after},
        }}), encoding="utf-8")
        state.write_text(state_after, encoding="utf-8")
        brief.write_text("human edit\n", encoding="utf-8")
        result = json.loads(self.run_cli("check", str(self.project), expected=1).stdout)
        self.assertTrue(any("Незавершённый revision" in error for error in result["errors"]))
        rejected = self.run_cli("revision-recover", str(self.project), "--revision", "R-001", "--mode", "rollback", expected=1)
        self.assertIn("изменён после pending revision", rejected.stderr)
        self.assertEqual(state.read_text(encoding="utf-8"), state_after)
        self.assertEqual(brief.read_text(encoding="utf-8"), "human edit\n")
        self.assertTrue(pending_revision.exists())
        brief.write_text(brief_after, encoding="utf-8")
        self.run_cli("revision-recover", str(self.project), "--revision", "R-001", "--mode", "rollback")
        self.assertEqual(state.read_text(encoding="utf-8"), state_before)
        self.assertEqual(brief.read_text(encoding="utf-8"), brief_before)

        exact_after = b"exact\r\nbytes\r\n"
        pending_revision_2 = self.project / "revisions/.pending-R-002.json"
        pending_revision_2.write_text(json.dumps({"revision_id": "R-002", "encoding": "base64-bytes", "files": {
            "state.md": {"existed": True,
                         "before_b64": TOOL.base64.b64encode(state.read_bytes()).decode("ascii"),
                         "after_b64": TOOL.base64.b64encode(exact_after).decode("ascii")},
        }}), encoding="utf-8")
        self.run_cli("revision-recover", str(self.project), "--revision", "R-002", "--mode", "complete")
        self.assertEqual(state.read_bytes(), exact_after)

        stage_source_2 = staging / "S-002.source"
        stage_extract_2 = staging / "S-002.extract.md"
        stage_source_2.write_text("second", encoding="utf-8")
        stage_extract_2.write_text("second extract", encoding="utf-8")
        entry_2 = {**entry, "source_id": "S-002", "stored_path": "sources/originals/S-002__value.txt",
                   "extract_path": "sources/extracts/S-002.md", "sha256": TOOL.sha256(stage_source_2),
                   "extract_sha256": TOOL.sha256(stage_extract_2)}
        manifest_2 = {"source_id": "S-002", "entry": entry_2,
                      "stage_source": "sources/.staging/S-002.source", "stage_extract": "sources/.staging/S-002.extract.md",
                      "final_source": entry_2["stored_path"], "final_extract": entry_2["extract_path"]}
        pending_2 = staging / "S-002.pending.json"
        pending_2.write_text(json.dumps(manifest_2), encoding="utf-8")
        stage_extract_2.write_text("human edit", encoding="utf-8")
        rejected = self.run_cli("ingest-recover", str(self.project), "--source-id", "S-002", "--mode", "discard", expected=1)
        self.assertIn("изменён после pending manifest", rejected.stderr)
        self.assertTrue(stage_source_2.exists())
        self.assertTrue(stage_extract_2.exists())
        self.assertTrue(pending_2.exists())
        stage_extract_2.write_text("second extract", encoding="utf-8")
        self.run_cli("ingest-recover", str(self.project), "--source-id", "S-002", "--mode", "discard")
        self.assertFalse(stage_source_2.exists())
        self.assertFalse(stage_extract_2.exists())
        self.assertFalse(pending_2.exists())

    def test_decision_commitment_and_duplicate_conclusion_integrity(self):
        conclusions = self.project / "evidence/conclusions.csv"
        conclusions.write_text("conclusion_id,statement,evidence_ids,alternative_explanations,change_condition,status,review_needed\nC-001,A,,,,active,no\nC-001,B,,,,active,no\n", encoding="utf-8")
        decisions = self.project / "decisions/decisions.csv"
        decisions.write_text("decision_id,recorded_at,decider,decision_kind,status,chosen_option,conclusion_ids,rejected_options,revisit_on,revisit_if,notes\nD-001,2026-01-01T00:00:00+00:00,Human,human,accepted,,,,,,\nD-002,2026-01-01T00:00:00+00:00,Test,simulated,simulated,O-2,C-001,,,,\n", encoding="utf-8")
        commitments = self.project / "commitments.csv"
        commitments.write_text("commitment_id,decision_id,description,owner,status,due_on,metric,review_condition,confirmed_by,confirmed_at\nK-001,D-002,Do,Owner,confirmed,,,,Human,2026-01-01\n", encoding="utf-8")
        result = json.loads(self.run_cli("check", str(self.project), expected=1).stdout)
        self.assertTrue(any("повторяющиеся conclusion_id" in error for error in result["errors"]))
        self.assertTrue(any("accepted human decision требует chosen_option" in error for error in result["errors"]))
        self.assertTrue(any("accepted human decision" in error and "обязательство" in error for error in result["errors"]))

    def test_url_policy_refuses_non_https_and_unapproved_hosts(self):
        result = self.run_cli("ingest", str(self.project), "http://127.0.0.1/x", expected=2)
        self.assertIn("HTTPS", result.stderr)
        result = self.run_cli("ingest", str(self.project), "https://example.com/", expected=2)
        self.assertIn("source-policy.json", result.stderr)


if __name__ == "__main__":
    unittest.main()
