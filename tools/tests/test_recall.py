from __future__ import annotations

import csv
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "adapters" / "mcp"))

import case_scope  # noqa: E402
import demo_workspace  # noqa: E402
import recall  # noqa: E402


class StemAndSenseTest(unittest.TestCase):
    def test_inflections_share_a_stem(self) -> None:
        for forms in (("удержание", "удержания", "удержанием"), ("когорта", "когорты", "когорте"),
                      ("уходят", "уходить"), ("окупаемость", "окупаемости"), ("pricing", "prices")):
            self.assertEqual(len({recall.stem(form) for form in forms}), 1, forms)

    def test_paraphrase_without_shared_words_is_found(self) -> None:
        cards = [("A", "Отток подписчиков вырос после смены маркетинга"), ("B", "Рецепт пирога")]
        _, matches = recall.rank("почему уходят клиенты после рекламной кампании", cards)
        self.assertEqual([m.doc_id for m in matches], ["A"])

    def test_phrase_fixes_word_sense(self) -> None:
        # "уходил в минус" is economics; it must not be read as churn.
        _, matches = recall.rank("почему уходят клиенты", [("E", "Пилот уходил в минус при договорной цене")])
        self.assertEqual(matches, [])

    def test_broad_concept_alone_gives_no_result(self) -> None:
        cards = [("T", "Участник узнаёт об исчерпании интернета в пакете связи слишком поздно")]
        _, matches = recall.rank("покрытие 5G в новых регионах", cards)
        self.assertEqual(matches, [])

    def test_query_limits(self) -> None:
        with self.assertRaises(ValueError):
            recall.validate_query(" ")
        with self.assertRaises(ValueError):
            recall.validate_query("x" * (recall.MAX_QUERY_CHARS + 1))
        for bad in (0, recall.MAX_LIMIT + 1, True, "3"):
            with self.assertRaises(ValueError):
                recall.validate_limit(bad)


class EvaluationRegressionTest(unittest.TestCase):
    """Frozen numbers of docs/mcp-recall/eval; a lexicon change must update the README too."""

    def test_eval_sets(self) -> None:
        report = recall.evaluate(ROOT / "docs" / "mcp-recall" / "eval")
        dev = report["sets"]["queries-dev"]["systems"]
        seen = report["sets"]["queries-seen"]["systems"]
        self.assertEqual(dev["recall"]["recall_at_3"], 1.0)
        self.assertEqual(dev["recall"]["negative_queries_clean"], dev["recall"]["negative_queries"])
        self.assertGreaterEqual(seen["recall"]["recall_at_3"], 0.8)
        self.assertEqual(seen["recall"]["negative_queries_clean"], seen["recall"]["negative_queries"])
        self.assertLessEqual(seen["recall"]["queries_with_false_positive"], 1)
        self.assertEqual(seen["recall"]["strong_items_wrong"], 0)
        # Baselines stay visible: literal all-words finds nothing, any-word shows many wrong cards.
        self.assertEqual(seen["literal_all_words"]["recall_at_3"], 0.0)
        self.assertGreater(seen["literal_any_word"]["queries_with_false_positive"], 5)


class PrecedentRecallTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="recall-test-"))
        self.root = self.temp / "workspace"
        demo_workspace.build(self.root)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp)

    def ids(self, result: dict) -> list[str]:
        return [item["id"] for item in result["items"]]

    def test_found_irrelevant_and_retired(self) -> None:
        found = recall.recall_precedents(self.root, "Можно ли писать клиентам про функцию, которой ещё нет в продукте?")
        self.assertEqual(self.ids(found), ["P-0001"])
        item = found["items"][0]
        self.assertEqual(item["match"]["band"], "strong")
        self.assertEqual(item["source_check"]["state"], "matches")
        self.assertEqual(item["source_now"]["decision_kind"], "simulated")
        self.assertEqual(item["links"]["registry_row"], "projects/lesson-demo/decisions/decisions.csv#decision_id=D-001")
        self.assertIn("переносимость", item["use"])

        self.assertEqual(self.ids(recall.recall_precedents(self.root, "рецепт борща")), [])

        query = "цифры в презентации не сходятся с выгрузкой"
        hidden = recall.recall_precedents(self.root, query)
        self.assertEqual(self.ids(hidden), [])
        self.assertEqual(hidden["searched"]["retired_excluded"], 1)
        history = recall.recall_precedents(self.root, query, include_retired=True)
        self.assertEqual(self.ids(history), ["P-0004"])
        self.assertEqual(history["items"][0]["match"]["band"], "retired_history")
        self.assertTrue(history["items"][0]["retire_reason"])

    def test_changed_source_is_flagged(self) -> None:
        path = self.root / "projects" / "lesson-demo" / "decisions" / "decisions.csv"
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields, rows = reader.fieldnames, list(reader)
        rows[0]["revisit_if"] = "Изменено после запоминания"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        item = recall.recall_precedents(self.root, "обещание клиенту про функцию из roadmap")["items"][0]
        self.assertEqual(item["id"], "P-0001")
        self.assertEqual(item["source_check"]["state"], "changed")
        self.assertIn("перепровер", item["use"])

    def test_case_search_reads_registries_only(self) -> None:
        case, _ = case_scope.select_case(self.root, "projects/lesson-demo")
        result = recall.search_case(case, "обещали живого преподавателя")
        self.assertIn("E-012", self.ids(result))
        self.assertTrue(all(item["record"].split("#")[0].endswith(".csv") for item in result["items"]))


class CaseScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="scope-test-"))
        case = self.temp / "projects" / "one"
        (case / "evidence").mkdir(parents=True)
        (case / "project.json").write_text("{}", encoding="utf-8")
        (case / "evidence" / "claims.csv").write_text("claim_id,statement\nE-001,Синтетика\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp)

    def test_only_named_cases_are_selected(self) -> None:
        case, name = case_scope.select_case(self.temp, "projects/one")
        self.assertEqual(name, "projects/one")
        for bad in ("/projects/one", "projects/../projects/one", "projects", "tools/one", "projects/missing", ""):
            with self.assertRaises(case_scope.ScopeError, msg=bad):
                case_scope.select_case(self.temp, bad)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlinks_in_case_are_refused(self) -> None:
        case = self.temp / "projects" / "one"
        os.symlink(case / "evidence" / "claims.csv", case / "evidence" / "alias.csv")
        with self.assertRaises(case_scope.ScopeError):
            case_scope.scan_case(case)
        os.symlink(case, self.temp / "projects" / "linked")
        with self.assertRaises(case_scope.ScopeError):
            case_scope.select_case(self.temp, "projects/linked")


if __name__ == "__main__":
    unittest.main()
