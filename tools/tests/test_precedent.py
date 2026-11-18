from __future__ import annotations

import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "tools" / "precedent.py"

CONCLUSION_FIELDS = (
    "conclusion_id",
    "statement",
    "evidence_ids",
    "alternative_explanations",
    "change_condition",
    "status",
    "review_needed",
)
CLAIM_FIELDS = (
    "claim_id",
    "type",
    "statement",
    "source_ids",
    "locator",
    "period",
    "unit",
    "status",
    "supersedes",
    "limitations",
)
DECISION_FIELDS = (
    "decision_id",
    "recorded_at",
    "decider",
    "decision_kind",
    "status",
    "chosen_option",
    "conclusion_ids",
    "rejected_options",
    "revisit_on",
    "revisit_if",
    "notes",
)


class PrecedentConsumerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="precedent-consumer-"))
        (self.temp / "projects").mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp)

    def run_cli(self, *args: str, expected: int = 0, cwd: Path | None = None):
        result = subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=cwd or self.temp,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, expected, msg=f"stdout={result.stdout}\nstderr={result.stderr}")
        return result

    def write_csv(self, path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def make_case(
        self,
        name: str,
        *,
        claim_status: str = "active",
        conclusion_status: str = "active",
        review_needed: str = "no",
    ) -> Path:
        case = self.temp / "projects" / name
        self.write_csv(
            case / "evidence" / "claims.csv",
            CLAIM_FIELDS,
            [
                {
                    "claim_id": "E-001",
                    "type": "fact",
                    "statement": f"RAW SECRET evidence for {name}",
                    "source_ids": "S-001",
                    "locator": "S-001#row:2",
                    "status": claim_status,
                }
            ],
        )
        self.write_csv(
            case / "evidence" / "conclusions.csv",
            CONCLUSION_FIELDS,
            [
                {
                    "conclusion_id": "C-001",
                    "statement": f"RAW SECRET conclusion for {name}",
                    "evidence_ids": "E-001",
                    "status": conclusion_status,
                    "review_needed": review_needed,
                }
            ],
        )
        self.write_csv(
            case / "decisions" / "decisions.csv",
            DECISION_FIELDS,
            [
                {
                    "decision_id": "D-001",
                    "recorded_at": "2026-11-17T13:18:14+00:00",
                    "decider": "scenario-test",
                    "decision_kind": "simulated",
                    "status": "simulated",
                    "chosen_option": "O-002",
                    "conclusion_ids": "C-001",
                    "notes": "RAW SECRET decision payload",
                },
                {
                    "decision_id": "D-002",
                    "recorded_at": "2026-11-17T14:00:00+00:00",
                    "decider": "strategist-agent",
                    "decision_kind": "agent_recommendation",
                    "status": "recommended",
                    "chosen_option": "O-003",
                    "conclusion_ids": "C-001",
                    "notes": "not owner approval",
                },
            ],
        )
        return case

    def parse(self, result: subprocess.CompletedProcess[str]) -> dict:
        return json.loads(result.stdout)

    def test_two_cases_persist_across_processes_without_copying_raw_rows(self):
        alpha = self.make_case("alpha")
        beta = self.make_case("beta")
        alpha_source = (alpha / "evidence" / "conclusions.csv").read_bytes()
        beta_source = (beta / "decisions" / "decisions.csv").read_bytes()

        first = self.parse(
            self.run_cli(
                "remember",
                "alpha",
                "--ref",
                "C-001",
                "--topic",
                "удержание",
                "--note",
                "Проверять знаменатель до выбора механики",
                "--when",
                "Когда меняется состав привлечения",
            )
        )
        simulated = self.parse(
            self.run_cli(
                "remember",
                "projects/beta",
                "--ref",
                "D-001",
                "--topic",
                "тестовое решение",
                "--note",
                "Использовать только как гипотезу",
                "--when",
                "До человеческого выбора",
            )
        )
        recommended = self.parse(
            self.run_cli(
                "remember",
                "beta",
                "--ref",
                "D-002",
                "--topic",
                "рекомендация агента",
                "--note",
                "Не считать назначением",
                "--when",
                "Пока владелец не подтвердил",
            )
        )

        self.assertEqual(first["source_ref"], "projects/alpha#C-001")
        self.assertEqual(first["source_at_remember"]["kind_label"], "вывод")
        self.assertEqual(simulated["source_at_remember"]["decision_kind"], "simulated")
        self.assertEqual(simulated["source_at_remember"]["status"], "simulated")
        self.assertEqual(recommended["source_at_remember"]["decision_kind"], "agent_recommendation")
        self.assertEqual(recommended["source_at_remember"]["status"], "recommended")
        self.assertNotIn("accepted", json.dumps([simulated, recommended]))

        # A fresh CLI process can find precedents from both project cases.
        found = self.parse(self.run_cli("find"))
        self.assertEqual([item["id"] for item in found["items"]], ["P-0001", "P-0002", "P-0003"])
        self.assertEqual({item["source_check"]["state"] for item in found["items"]}, {"matches"})
        filtered = self.parse(self.run_cli("find", "знаменатель"))
        self.assertEqual([item["id"] for item in filtered["items"]], ["P-0001"])

        # Remember is read-only for source registries and stores no raw row text.
        self.assertEqual((alpha / "evidence" / "conclusions.csv").read_bytes(), alpha_source)
        self.assertEqual((beta / "decisions" / "decisions.csv").read_bytes(), beta_source)
        memory = (self.temp / ".portfolio" / "precedents.json").read_text(encoding="utf-8")
        self.assertNotIn("RAW SECRET", memory)
        self.assertIn("sha256:", memory)

    def test_decision_dependency_change_and_unavailable_source_are_distinct(self):
        case = self.make_case("dependent")
        self.run_cli(
            "remember",
            "dependent",
            "--ref",
            "D-001",
            "--topic",
            "основание решения",
            "--note",
            "Перепроверять цепочку",
            "--when",
            "При отзыве evidence",
        )
        decision_before = (case / "decisions" / "decisions.csv").read_bytes()

        claims_path = case / "evidence" / "claims.csv"
        with claims_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        rows[0]["status"] = "superseded"
        self.write_csv(claims_path, CLAIM_FIELDS, rows)
        changed = self.parse(self.run_cli("find"))["items"][0]
        self.assertEqual(changed["source_check"]["state"], "changed")
        self.assertIn("требуется перепроверка", changed["source_check"]["label"])
        self.assertEqual((case / "decisions" / "decisions.csv").read_bytes(), decision_before)
        self.assertEqual(changed["source_now"]["decision_kind"], "simulated")

        claims_path.unlink()
        unavailable = self.parse(self.run_cli("find"))["items"][0]
        self.assertEqual(unavailable["source_check"]["state"], "unavailable")
        self.assertIsNone(unavailable["source_now"])

    def test_absence_retirement_and_history(self):
        self.assertEqual(self.parse(self.run_cli("find"))["items"], [])
        self.assertFalse((self.temp / ".portfolio").exists())
        self.make_case("retire-me")
        remembered = self.parse(
            self.run_cli(
                "remember",
                "retire-me",
                "--ref",
                "C-001",
                "--topic",
                "старый урок",
                "--note",
                "Больше не применять",
                "--when",
                "После смены продукта",
            )
        )
        retired = self.parse(
            self.run_cli("retire", remembered["id"], "--reason", "изменилась модель продукта")
        )
        self.assertTrue(retired["retired"])
        self.assertEqual(self.parse(self.run_cli("find"))["items"], [])
        history = self.parse(self.run_cli("find", "--include-retired"))["items"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["retire_reason"], "изменилась модель продукта")
        by_reason = self.parse(self.run_cli("find", "модель", "--include-retired"))["items"]
        self.assertEqual([item["id"] for item in by_reason], [remembered["id"]])

    def test_path_containment_rejects_escape_and_symlinks(self):
        outside = self.temp.parent / f"{self.temp.name}-outside"
        outside.mkdir()
        self.addCleanup(lambda: shutil.rmtree(outside, ignore_errors=True))
        outside_case = outside / "case"
        outside_case.mkdir()

        escaped = self.run_cli(
            "remember",
            "../" + outside.name + "/case",
            "--ref",
            "C-001",
            "--topic",
            "x",
            "--note",
            "x",
            "--when",
            "x",
            expected=2,
        )
        self.assertIn("под projects", escaped.stderr)

        (self.temp / "projects" / "linked").symlink_to(outside_case, target_is_directory=True)
        linked = self.run_cli(
            "remember",
            "linked",
            "--ref",
            "C-001",
            "--topic",
            "x",
            "--note",
            "x",
            "--when",
            "x",
            expected=2,
        )
        self.assertIn("символические ссылки запрещены", linked.stderr)

        case = self.make_case("registry-link")
        external_registry = outside / "conclusions.csv"
        shutil.copy2(case / "evidence" / "conclusions.csv", external_registry)
        (case / "evidence" / "conclusions.csv").unlink()
        (case / "evidence" / "conclusions.csv").symlink_to(external_registry)
        registry_link = self.run_cli(
            "remember",
            "registry-link",
            "--ref",
            "C-001",
            "--topic",
            "x",
            "--note",
            "x",
            "--when",
            "x",
            expected=2,
        )
        self.assertIn("символические ссылки запрещены", registry_link.stderr)
        self.assertFalse((self.temp / ".portfolio").exists())

        external_portfolio = outside / "portfolio"
        external_portfolio.mkdir()
        (self.temp / ".portfolio").symlink_to(external_portfolio, target_is_directory=True)
        portfolio_link = self.run_cli("find", expected=2)
        self.assertIn("символические ссылки запрещены", portfolio_link.stderr)

    def test_help_discloses_local_scope_and_no_os_boundary(self):
        help_result = self.run_cli("--help")
        self.assertIn(".portfolio/", help_result.stdout)
        self.assertIn("НЕ граница доступа ОС", help_result.stdout)


if __name__ == "__main__":
    unittest.main()
