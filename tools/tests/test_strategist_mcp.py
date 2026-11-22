"""Stdlib JSON-RPC client against tools/strategist_mcp.py as a real subprocess.

The official-SDK roundtrip lives in adapters/mcp/sdk_roundtrip.py (optional venv).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "tools" / "strategist_mcp.py"
sys.path.insert(0, str(ROOT / "adapters" / "mcp"))

import demo_workspace  # noqa: E402

ALLOWED_ARGUMENTS = {"query", "include_retired", "include_inactive", "limit"}


class Session:
    def __init__(self, *args: str) -> None:
        self.process = subprocess.Popen([sys.executable, str(SERVER), *args], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.next_id = 0

    def send_raw(self, data: bytes) -> dict:
        self.process.stdin.write(data)
        self.process.stdin.flush()
        return json.loads(self.process.stdout.readline())

    def request(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        message = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            message["params"] = params
        response = self.send_raw((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        assert response["id"] == self.next_id, response
        return response

    def notify(self, method: str) -> None:
        self.process.stdin.write((json.dumps({"jsonrpc": "2.0", "method": method}) + "\n").encode())
        self.process.stdin.flush()

    def initialize(self, version: str = "2025-06-18") -> dict:
        response = self.request("initialize", {"protocolVersion": version, "capabilities": {},
                                               "clientInfo": {"name": "unittest", "version": "0"}})
        self.notify("notifications/initialized")
        return response["result"]

    def call(self, name: str, arguments: dict | None = None) -> dict:
        return self.request("tools/call", {"name": name, "arguments": arguments or {}})["result"]

    def close(self) -> int:
        self.process.stdin.close()
        code = self.process.wait(timeout=10)
        self.process.stdout.close()
        self.process.stderr.close()
        return code


class StrategistMcpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = Path(tempfile.mkdtemp(prefix="strategist-mcp-test-"))
        cls.root = cls.temp / "workspace"
        demo_workspace.build(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.temp)

    def open(self, *, case: bool = True) -> Session:
        args = ["--root", str(self.root)] + (["--case", demo_workspace.CASE] if case else [])
        session = Session(*args)
        self.addCleanup(session.close)
        return session

    def test_handshake_and_read_only_tool_surface(self) -> None:
        session = self.open()
        result = session.initialize("2025-06-18")
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["capabilities"], {"tools": {"listChanged": False}})
        self.assertEqual(session.initialize("1999-01-01")["protocolVersion"], "2025-11-25")
        tools = session.request("tools/list")["result"]["tools"]
        self.assertEqual([tool["name"] for tool in tools], ["precedent_recall", "case_resume", "case_check", "case_search"])
        for tool in tools:
            self.assertTrue(tool["annotations"]["readOnlyHint"])
            self.assertFalse(tool["annotations"]["destructiveHint"])
            self.assertFalse(tool["annotations"]["openWorldHint"])
            self.assertFalse(tool["inputSchema"]["additionalProperties"])
            self.assertLessEqual(set(tool["inputSchema"]["properties"]), ALLOWED_ARGUMENTS)
        self.assertEqual(session.request("ping")["result"], {})

    def test_without_case_only_portfolio_tool(self) -> None:
        session = self.open(case=False)
        session.initialize()
        names = [tool["name"] for tool in session.request("tools/list")["result"]["tools"]]
        self.assertEqual(names, ["precedent_recall"])
        self.assertEqual(session.request("tools/call", {"name": "case_resume", "arguments": {}})["error"]["code"], -32602)

    def test_recall_found_irrelevant_retired(self) -> None:
        session = self.open()
        session.initialize()
        found = session.call("precedent_recall", {"query": "Можно ли писать клиентам про функцию, которой ещё нет в продукте?"})
        self.assertFalse(found["isError"])
        payload = found["structuredContent"]
        self.assertEqual(json.loads(found["content"][0]["text"]), payload)
        self.assertEqual([item["id"] for item in payload["items"]], ["P-0001"])
        self.assertEqual(payload["items"][0]["source_ref"], "projects/lesson-demo#D-001")
        self.assertFalse(payload["method"]["embeddings"])
        self.assertEqual(session.call("precedent_recall", {"query": "рецепт борща"})["structuredContent"]["items"], [])
        query = {"query": "цифры в презентации не сходятся с выгрузкой"}
        self.assertEqual(session.call("precedent_recall", query)["structuredContent"]["items"], [])
        history = session.call("precedent_recall", {**query, "include_retired": True})["structuredContent"]["items"]
        self.assertEqual([(item["id"], item["retired"]) for item in history], [("P-0004", True)])

    def test_case_tools_reuse_cli_and_hide_absolute_paths(self) -> None:
        session = self.open()
        session.initialize()
        resume = session.call("case_resume")
        self.assertFalse(resume["isError"])
        self.assertEqual(resume["structuredContent"]["contract"], "strategist.resume/1.0")
        check = session.call("case_check")
        self.assertTrue(check["structuredContent"]["ok"])
        self.assertTrue(check["structuredContent"]["structural_only"])
        search = session.call("case_search", {"query": "обещали живого преподавателя", "limit": 3})
        self.assertIn("E-012", [item["id"] for item in search["structuredContent"]["items"]])
        for result in (resume, check, search):
            self.assertNotIn(str(self.temp), result["content"][0]["text"])

    def test_argument_and_protocol_errors(self) -> None:
        session = self.open()
        session.initialize()
        self.assertTrue(session.call("precedent_recall", {"query": "x", "path": "evidence"})["isError"])
        self.assertTrue(session.call("precedent_recall", {"query": 5})["isError"])
        self.assertTrue(session.call("precedent_recall", {"query": "x", "limit": 99})["isError"])
        self.assertTrue(session.call("precedent_recall", {})["isError"])
        self.assertEqual(session.request("tools/call", {"name": "run_shell", "arguments": {}})["error"]["code"], -32602)
        self.assertEqual(session.request("resources/list")["result"], {"resources": []})
        self.assertEqual(session.request("no/such")["error"]["code"], -32601)
        self.assertEqual(session.send_raw(b"{not json\n")["error"]["code"], -32700)
        self.assertEqual(session.send_raw(b"[]\n")["error"]["code"], -32600)
        oversized = b'{"jsonrpc":"2.0","id":99,"method":"ping","params":{"x":"' + b"a" * (1024 * 1024 + 10) + b'"}}\n'
        self.assertEqual(session.send_raw(oversized)["error"]["code"], -32600)
        self.assertEqual(session.request("ping")["result"], {})  # the session survives

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlink_inside_case_stops_case_tools(self) -> None:
        temp = Path(tempfile.mkdtemp(prefix="strategist-mcp-link-"))
        self.addCleanup(shutil.rmtree, temp)
        root = temp / "workspace"
        demo_workspace.build(root)
        case = root / demo_workspace.CASE
        os.symlink(case / "brief.md", case / "brief-alias.md")  # synthetic file inside the same case
        session = Session("--root", str(root), "--case", demo_workspace.CASE)
        self.addCleanup(session.close)
        session.initialize()
        for name in ("case_resume", "case_check"):
            result = session.call(name)
            self.assertTrue(result["isError"])
            self.assertIn("символическая ссылка", result["content"][0]["text"])
        self.assertTrue(session.call("case_search", {"query": "обещание"})["isError"])

    def test_case_marker_rechecked_between_calls(self) -> None:
        session = self.open()
        session.initialize()
        marker = self.root / demo_workspace.CASE / 'project.json'
        saved = marker.with_name('project.on-hold')
        marker.rename(saved)
        try:
            self.assertTrue(session.call('case_search', {'query': 'обещание'})['isError'])
        finally:
            saved.rename(marker)
        self.assertFalse(session.call('case_search', {'query': 'обещание'})['isError'])

    def test_bad_case_selection_refuses_to_start(self) -> None:
        for case in ("../workspace", "/etc", "projects", "tools"):
            result = subprocess.run([sys.executable, str(SERVER), "--root", str(self.root), "--case", case],
                                    input=b"", capture_output=True)
            self.assertEqual(result.returncode, 2, case)
            self.assertEqual(result.stdout, b"")


if __name__ == "__main__":
    unittest.main()
