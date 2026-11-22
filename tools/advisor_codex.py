"""A single text-only turn through Codex app-server, using existing ChatGPT auth."""

import asyncio
import json
import os
from pathlib import Path
import re
import tempfile


TOOL = "codex app-server --stdio"
DISABLED_FEATURES = (
    "apps", "browser_use", "hooks", "image_generation", "mcp_connection_sharing",
    "memories", "multi_agent_v2", "plugins", "remote_plugin", "shell_tool",
    "skill_search", "unified_exec", "view_image",
)
TEXT_ITEMS = {"userMessage", "reasoning", "agentMessage"}


class RouteError(Exception):
    def __init__(self, reason, status="failed"):
        super().__init__(reason)
        self.status = status


async def exchange(process, cwd, instructions, packet, record):
    dispatched = False

    async def send(method, params, ident=None):
        message = {"method": method, "params": params}
        if ident is not None:
            message["id"] = ident
        process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode())
        await process.stdin.drain()

    async def receive():
        raw = await process.stdout.readline()
        if not raw:
            raise RouteError("cli_stream_closed", "outcome_unknown" if dispatched else "failed")
        message = json.loads(raw)
        method = message.get("method")
        item_type = message.get("params", {}).get("item", {}).get("type")
        if method == "model/rerouted":
            raise RouteError("model_rerouted")
        if "id" in message and method:
            raise RouteError("unexpected_server_request", "outcome_unknown" if dispatched else "failed")
        if method in {"item/started", "item/completed"} and item_type not in TEXT_ITEMS:
            raise RouteError("tool_activity", "outcome_unknown" if dispatched else "failed")
        if method == "error":
            raise RouteError("cli_error_notification", "outcome_unknown" if dispatched else "failed")
        if "error" in message:
            code = message["error"].get("code")
            raise RouteError(f"rpc_error_{code}" if type(code) is int else "rpc_error")
        return message

    async def request(method, params, ident):
        await send(method, params, ident)
        while True:
            message = await receive()
            if message.get("id") == ident:
                return message["result"]

    initialized = await request("initialize", {
        "clientInfo": {"name": "strategist-advisor", "version": "1.0"},
    }, 1)
    version = re.search(r"/(\d+\.\d+\.\d+)\b", initialized.get("userAgent", ""))
    if version:
        record["cli_version"] = version[1]
    await send("initialized", {})
    config = (await request("config/read", {"cwd": str(cwd), "includeLayers": False}, 2))["config"]
    # A blank TOML table can merge with existing configuration. Check the
    # effective roster before starting a thread that could initialize a server.
    if any(entry.get("enabled", True) for entry in config.get("mcp_servers", {}).values()):
        raise RouteError("mcp_configured")
    account = await request("account/read", {"refreshToken": False}, 3)
    if (account.get("account") or {}).get("type") != "chatgpt":
        raise RouteError("chatgpt_login_required")
    record["auth_route"] = "chatgpt"

    model, effort = record["requested_model"], record["requested_effort"]
    thread = await request("thread/start", {
        "cwd": str(cwd), "model": model, "modelProvider": "openai",
        "sandbox": "read-only", "approvalPolicy": "never", "ephemeral": True,
        "baseInstructions": instructions,
        "config": {"model_reasoning_effort": effort},
    }, 4)
    record["cli_model"] = thread["model"]
    record["cli_effort"] = thread.get("reasoningEffort")
    record["provider"] = thread["modelProvider"]
    sandbox = thread.get("sandbox") or {}
    if (record["cli_model"] != model or record["cli_effort"] != effort
            or record["provider"] != "openai" or thread.get("approvalPolicy") != "never"
            or sandbox.get("type") != "readOnly" or sandbox.get("networkAccess") not in (None, False)
            or thread.get("instructionSources") or Path(thread["cwd"]) != cwd):
        raise RouteError("thread_config_mismatch")

    dispatched = True
    record["turn_requested"] = True
    await send("turn/start", {
        "threadId": thread["thread"]["id"], "model": model, "effort": effort,
        "input": [{"type": "text", "text": packet}],
    }, 5)
    answer = ""
    turn_id = None
    while True:
        message = await receive()
        params = message.get("params", {})
        if message.get("id") == 5:
            turn_id = message["result"]["turn"]["id"]
        elif message.get("method") == "item/completed":
            item = params["item"]
            if item["type"] == "agentMessage" and item.get("phase") != "commentary":
                answer = item["text"]
        elif message.get("method") == "turn/completed":
            if params["turn"]["id"] != turn_id:
                raise RouteError("turn_id_mismatch", "outcome_unknown")
            if params["turn"]["status"] != "completed" or not answer.strip():
                raise RouteError("no_completed_answer")
            return answer


async def run(binary, instructions, packet, record, timeout):
    command = [binary, "app-server", "--stdio", "-c", 'web_search="disabled"',
               "-c", "project_doc_max_bytes=0"]
    for feature in DISABLED_FEATURES:
        command.extend(["--disable", feature])
    env = os.environ.copy()
    for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_BASE"):
        env.pop(name, None)
    with tempfile.TemporaryDirectory(prefix="strategist-advisor-") as directory:
        process = await asyncio.create_subprocess_exec(
            *command, cwd=directory, env=env, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=1024**2,
        )
        try:
            return await asyncio.wait_for(
                exchange(process, Path(directory).resolve(), instructions, packet, record), timeout,
            )
        except TimeoutError:
            raise RouteError("timeout", "outcome_unknown" if record["turn_requested"] else "failed") from None
        finally:
            # Once a route fails, discard any later response from the child.
            process.stdin.close()
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            await process.wait()
