import contextlib
from hashlib import sha256
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import advisor


FAKE_CODEX = r'''
import json
import os
from pathlib import Path
import sys
import time

assert Path.cwd().is_dir() and not list(Path.cwd().iterdir())
assert sys.argv[1:3] == ["app-server", "--stdio"]
assert "OPENAI_API_KEY" not in os.environ
for name in ("shell_tool", "unified_exec", "hooks", "plugins"):
    assert ["--disable", name] in [sys.argv[i:i+2] for i in range(len(sys.argv))]
scenario = os.environ.get("ADVISOR_TEST_CLI", "ok")

def emit(message):
    print(json.dumps(message), flush=True)

for line in sys.stdin:
    m = json.loads(line)
    method, p = m["method"], m["params"]
    if method == "initialized":
        continue
    if method == "initialize":
        result = {"userAgent": "codex/0.170.0 (test)"}
    elif method == "config/read":
        assert p == {"cwd": str(Path.cwd()), "includeLayers": False}
        servers = {"dummy": {}} if scenario == "mcp" else {"dummy": {"enabled": False}}
        result = {"config": {"mcp_servers": servers, "test_secret": "must-not-leak"}}
    elif method == "account/read":
        assert p == {"refreshToken": False}
        result = {"account": {"type": "apiKey" if scenario == "api" else "chatgpt"}}
    elif method == "thread/start":
        assert p["sandbox"] == "read-only" and p["approvalPolicy"] == "never" and p["ephemeral"]
        model = p["model"]
        assert model == os.environ.get("ADVISOR_EXPECTED_MODEL", "test-model")
        assert p["config"]["model_reasoning_effort"] == os.environ.get("ADVISOR_EXPECTED_EFFORT", "low")
        assert "Синтетический респондент" in p["baseInstructions"] or "Критик предложения" in p["baseInstructions"]
        result = {"model": "other" if scenario == "mismatch" else model, "modelProvider": "openai",
                  "reasoningEffort": p["config"]["model_reasoning_effort"],
                  "cwd": str(Path.cwd()), "approvalPolicy": "never", "instructionSources": [],
                  "sandbox": {"type": "readOnly", "networkAccess": False}, "thread": {"id": "test-thread"}}
    elif method == "turn/start":
        assert p["model"] == model and len(p["input"]) == 1 and p["input"][0]["type"] == "text"
        assert p["effort"] == os.environ.get("ADVISOR_EXPECTED_EFFORT", "low")
        packet = json.loads(p["input"][0]["text"])
        assert packet["context"] == "Test context.\n"
        if scenario == "timeout":
            time.sleep(10)
        turn = {"id": "test-turn", "status": "completed"}
        emit({"id": m["id"], "result": {"turn": turn}})
        if scenario == "rerouted":
            emit({"method": "model/rerouted", "params": {"toModel": "other"}})
        if scenario == "tool":
            emit({"method": "item/started", "params": {"item": {"type": "commandExecution"}}})
        count = len(packet["previous_turns"])
        if count:
            assert packet["previous_turns"][-1]["answer"] == f"Fixture answer {count - 1}"
        emit({"method": "item/completed", "params": {"item": {"type": "agentMessage", "text": f"Fixture answer {count}"}}})
        emit({"method": "turn/completed", "params": {"turn": turn}})
        continue
    else:
        raise AssertionError(method)
    emit({"id": m["id"], "result": result})
'''


class AdvisorTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        cli = self.folder / "codex"
        cli.write_text(f"#!{sys.executable}\n" + FAKE_CODEX, encoding="utf-8")
        cli.chmod(0o700)
        self.addCleanup(patch.stopall)
        patch("advisor.shutil.which", return_value=str(cli)).start()
        patch.dict("os.environ", {"OPENAI_API_KEY": "test-credential"}).start()
        self.context = self.folder / "context.md"
        self.context.write_text("Test context.\n", encoding="utf-8")
        self.question = self.folder / "question.txt"
        self.question.write_text("Fixture question\n", encoding="utf-8")

    def run_advisor(self, name, *extra, role="respondent", explicit=True):
        route = ["--model", "test-model", "--effort", "low"] if explicit else []
        with contextlib.redirect_stdout(io.StringIO()) as terminal:
            result = advisor.main([
                "run", "--via", "codex", *route, "--role", role,
                "--context", str(self.context), "--question", str(self.question),
                "--out", str(self.folder / name), *extra,
            ])
        self.assertNotIn("must-not-leak", terminal.getvalue())
        return result

    def test_multiturn_history_and_no_overwrite(self):
        self.assertEqual(self.run_advisor("first.json"), 0)
        first = self.folder / "first.json"
        self.question.write_text("Follow up about the previous answer\n", encoding="utf-8")
        self.assertEqual(self.run_advisor("second.json", "--previous", str(first)), 0)
        record = json.loads((self.folder / "second.json").read_bytes())
        self.assertEqual("test-model", record["cli_model"])
        self.assertEqual("0.170.0", record["cli_version"])
        self.assertEqual("unknown", record["cost_status"])
        self.assertIsNone(record["cost_amount"])
        self.assertEqual(sha256(first.read_bytes()).hexdigest(), record["previous_sha256"])
        self.assertEqual(["Fixture answer 0", "Fixture answer 1"], [turn["answer"] for turn in record["turns"]])
        original = first.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_advisor("first.json")
        self.assertEqual(original, first.read_bytes())

    def test_critic_cannot_inherit_respondent_history(self):
        self.assertEqual(self.run_advisor("first.json"), 0)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_advisor("critique.json", "--previous", str(self.folder / "first.json"), role="critic")
        self.assertFalse((self.folder / "critique.json").exists())
        self.assertEqual(self.run_advisor("critique.json", role="critic"), 0)

    def test_failures_record_no_usable_answer(self):
        cases = (
            ("mcp", "mcp_configured", "failed", False),
            ("api", "chatgpt_login_required", "failed", False),
            ("mismatch", "thread_config_mismatch", "failed", False),
            ("rerouted", "model_rerouted", "failed", True),
            ("tool", "tool_activity", "outcome_unknown", True),
            ("timeout", "timeout", "outcome_unknown", True),
        )
        for scenario, reason, status, requested in cases:
            with self.subTest(scenario=scenario), patch.dict("os.environ", {"ADVISOR_TEST_CLI": scenario}):
                name = scenario + ".json"
                self.assertEqual(self.run_advisor(name, "--timeout", "1"), 1)
                record = json.loads((self.folder / name).read_bytes())
                self.assertEqual((reason, status, requested), (record["reason"], record["status"], record["turn_requested"]))
                self.assertEqual([], record["turns"])

    def test_missing_cli_has_a_receipt(self):
        with patch("advisor.shutil.which", return_value=None):
            self.assertEqual(self.run_advisor("missing.json"), 1)
        self.assertEqual("codex_not_found", json.loads((self.folder / "missing.json").read_bytes())["reason"])

    def test_profile_selects_model_and_effort_for_the_actual_rpc(self):
        profile = self.folder / "models.json"
        profile.write_text(json.dumps({
            "respondent": {"model": "smaller-model", "effort": "low"},
            "critic": {"model": "critic-model", "effort": "medium"},
        }), encoding="utf-8")
        jobs = (
            ("respondent", "smaller-model", "low", "profile", []),
            ("critic", "critic-model", "medium", "profile", []),
            ("critic", "manual-critic", "medium", "flag", ["--model", "manual-critic"]),
        )
        for index, (role, model, effort, source, flags) in enumerate(jobs):
            with self.subTest(role=role, model=model), patch.dict("os.environ", {
                "ADVISOR_EXPECTED_MODEL": model, "ADVISOR_EXPECTED_EFFORT": effort,
            }):
                name = f"profile-{index}.json"
                self.assertEqual(self.run_advisor(name, "--profile", str(profile), *flags, role=role, explicit=False), 0)
                record = json.loads((self.folder / name).read_bytes())
                self.assertEqual((model, effort), (record["cli_model"], record["cli_effort"]))
                self.assertEqual(record["selection"], {
                    "model": source, "effort": "profile", "profile_sha256": sha256(profile.read_bytes()).hexdigest(),
                })

    def test_no_model_is_inferred_without_an_explicit_profile_or_flags(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_advisor("missing-selection.json", explicit=False)
        self.assertFalse((self.folder / "missing-selection.json").exists())

    def test_vision_route_uses_attachment_handoff_without_dispatch(self):
        with contextlib.redirect_stdout(io.StringIO()) as terminal, patch("advisor.asyncio.run") as dispatch:
            self.assertEqual(advisor.main(["route", "vision"]), 0)
        dispatch.assert_not_called()
        data = json.loads(terminal.getvalue())
        self.assertEqual("tools/media_vision.py", data["tool"])
        self.assertEqual("skills/media-ux/SKILL.md", data["skill"])
        self.assertIn("вложение", data["input"])
        self.assertIn("--image", data["fallback"])


if __name__ == "__main__":
    unittest.main()
