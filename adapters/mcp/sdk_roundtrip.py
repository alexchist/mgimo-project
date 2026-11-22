#!/usr/bin/env python3
"""Real MCP roundtrip: official Python SDK client -> tools/strategist_mcp.py over stdio.

Needs the official SDK in a separate venv (the server itself needs nothing):

    python3 -m venv /tmp/mcp-sdk && /tmp/mcp-sdk/bin/pip install mcp==2.3.0
    /tmp/mcp-sdk/bin/python adapters/mcp/sdk_roundtrip.py --out docs/mcp-recall/roundtrip-sdk.json

The script builds a throwaway workspace with dedicated cards (demo_workspace.py),
starts the server as a subprocess, lists tools and calls them in both SDK connect
modes ('legacy' = initialize handshake, 'auto' = discover probe with fallback).
It exits 1 if any expectation fails. The transcript replaces temp paths with
<workspace> so it can be committed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import demo_workspace  # noqa: E402

try:
    import mcp
    from mcp import Client, StdioServerParameters
except ImportError:  # pragma: no cover - depends on the optional venv
    raise SystemExit("Нужен официальный SDK: pip install mcp==2.3.0 в отдельном venv (см. docstring).")

SERVER = REPO / "tools" / "strategist_mcp.py"

CALLS = [
    ("paraphrase_promise", "precedent_recall",
     {"query": "Можно ли писать клиентам про функцию, которой ещё нет в продукте?"},
     {"ids": ["P-0001"]}),
    ("paraphrase_churn", "precedent_recall",
     {"query": "churn вырос после запуска промо, что мы уже знаем"},
     {"ids": ["P-0002"]}),
    ("irrelevant_everyday", "precedent_recall", {"query": "рецепт борща"}, {"ids": []}),
    ("irrelevant_same_domain", "precedent_recall", {"query": "покрытие 5G в новых регионах"}, {"ids": []}),
    ("retired_hidden_by_default", "precedent_recall",
     {"query": "цифры в презентации не сходятся с выгрузкой"}, {"ids": []}),
    ("retired_shown_as_history", "precedent_recall",
     {"query": "цифры в презентации не сходятся с выгрузкой", "include_retired": True},
     {"ids": ["P-0004"], "retired": True}),
    ("case_search", "case_search", {"query": "обещали живого преподавателя"}, {"contains": ["E-012"]}),
    ("case_resume", "case_resume", {}, {"contract": "strategist.resume/1.0"}),
    ("case_check", "case_check", {}, {"ok": True}),
    ("unknown_argument_refused", "precedent_recall", {"query": "x", "path": "/etc"}, {"is_error": True}),
]


def summarize(name: str, payload: dict | None) -> dict:
    if payload is None:
        return {}
    if name in {"precedent_recall"}:
        return {
            "searched": payload["searched"],
            "items": [{"id": item["id"], "source_ref": item["source_ref"], "band": item["match"]["band"],
                       "score": item["match"]["score"], "source_check": item["source_check"]["state"],
                       "decision_kind": (item.get("source_now") or {}).get("decision_kind"),
                       "retired": item["retired"], "retire_reason": item.get("retire_reason"),
                       "matched_concepts": [c["concept"] for c in item["match"]["matched_concepts"]],
                       "use": item["use"]} for item in payload["items"]],
            "query_analysis": payload["query_analysis"],
        }
    if name == "case_search":
        return {"items": [{"id": item["id"], "kind": item["kind"], "record": item["record"],
                           "band": item["match"]["band"]} for item in payload["items"]]}
    if name == "case_resume":
        return {"contract": payload.get("contract"), "ok": payload.get("ok"),
                "project": payload.get("project"),
                "decisions": [row["record"] for row in payload["observed_facts"]["decisions"]["items"]]}
    if name == "case_check":
        return {"ok": payload.get("ok"), "structural_only": payload.get("structural_only"),
                "counts": payload.get("counts"), "reproduce_with": payload.get("reproduce_with")}
    return {}


def check(expect: dict, result, payload: dict | None) -> list[str]:
    problems = []
    if expect.get("is_error"):
        if not result.is_error:
            problems.append("ожидалась ошибка инструмента")
        return problems
    if result.is_error:
        return [f"неожиданная ошибка: {result.content[0].text if result.content else ''}"]
    if "ids" in expect:
        ids = [item["id"] for item in payload["items"]]
        if expect["ids"] and ids[:1] != expect["ids"][:1]:
            problems.append(f"первым ожидался {expect['ids']}, получено {ids}")
        if not expect["ids"] and ids:
            problems.append(f"ожидался пустой ответ, получено {ids}")
        if expect.get("retired") and not all(item["retired"] for item in payload["items"]):
            problems.append("отозванная карточка не помечена retired")
    if "contains" in expect:
        ids = [item["id"] for item in payload["items"]]
        missing = [value for value in expect["contains"] if value not in ids]
        if missing:
            problems.append(f"нет {missing} в {ids}")
    if "contract" in expect and payload.get("contract") != expect["contract"]:
        problems.append("неверный контракт resume")
    if "ok" in expect and payload.get("ok") is not expect["ok"]:
        problems.append(f"ok={payload.get('ok')}")
    return problems


async def roundtrip(root: Path, mode: str) -> dict:
    params = StdioServerParameters(command=sys.executable,
                                   args=[str(SERVER), "--root", str(root), "--case", demo_workspace.CASE])
    record: dict = {"mode": mode, "calls": []}
    async with Client(params, mode=mode) as client:
        record["negotiated_protocol_version"] = client.protocol_version
        info = client.server_info
        record["server_info"] = {"name": info.name, "version": info.version} if info else None
        listed = await client.list_tools()
        record["tools"] = [{"name": tool.name, "read_only": bool(tool.annotations and tool.annotations.read_only_hint),
                            "arguments": sorted((tool.input_schema or {}).get("properties", {}))}
                           for tool in listed.tools]
        for label, tool, arguments, expect in CALLS:
            result = await client.call_tool(tool, arguments)
            payload = result.structured_content if not result.is_error else None
            problems = check(expect, result, payload)
            record["calls"].append({
                "label": label, "tool": tool, "arguments": arguments, "is_error": bool(result.is_error),
                "error_text": result.content[0].text if result.is_error and result.content else None,
                "summary": summarize(tool, payload), "expectation_problems": problems,
            })
    return record


def literal_find(root: Path, query: str) -> list[str]:
    words = [word.strip("?,.!") for word in query.split()]
    result = subprocess.run([sys.executable, str(REPO / "tools" / "precedent.py"), "find", *words],
                            cwd=root, text=True, capture_output=True, check=True)
    return [item["id"] for item in json.loads(result.stdout)["items"]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", help="куда сохранить JSON-протокол (иначе stdout)")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="strategist-mcp-") as temporary:
        root = Path(temporary) / "workspace"
        built = demo_workspace.build(root)
        transcript = {
            "contract": "strategist.mcp-roundtrip/1",
            "client": {"name": "mcp (official Python SDK)", "version": getattr(mcp, "__version__", None) or _sdk_version()},
            "server": "tools/strategist_mcp.py",
            "workspace": {"case": built["case"], "cards": built["cards"],
                          "note": "временная копия examples/demo; карточки записаны tools/precedent.py remember/retire"},
            "literal_find_same_queries": {label: literal_find(root, arguments["query"])
                                          for label, tool, arguments, _ in CALLS
                                          if tool == "precedent_recall" and label.startswith("paraphrase")},
            "runs": [asyncio.run(roundtrip(root, mode)) for mode in ("legacy", "auto")],
        }
        text = json.dumps(transcript, ensure_ascii=False, indent=1).replace(str(root), "<workspace>")
    problems = [problem for run in transcript["runs"] for call in run["calls"] for problem in call["expectation_problems"]]
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    print(f"roundtrip: {sum(len(run['calls']) for run in transcript['runs'])} вызовов, проблем: {len(problems)}", file=sys.stderr)
    for problem in problems:
        print(f"  - {problem}", file=sys.stderr)
    return 1 if problems else 0


def _sdk_version() -> str | None:
    from importlib.metadata import version
    try:
        return version("mcp")
    except Exception:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
