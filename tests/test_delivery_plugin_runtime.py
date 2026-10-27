"""Exercise the attachment plugin with real OpenCode and a local fake model."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import uuid
from dataclasses import replace
from pathlib import Path

import aiohttp
import pytest
from conftest import start_server
from test_delivery_tools import delivery as delivery
from test_delivery_tools import running
from test_memory_plugin_runtime import OPENCODE, response_stream

from qqbot.models import Context
from qqbot.opencode import ApiError, OpenCode

PLUGIN = Path(__file__).resolve().parents[1] / "deploy/opencode-delivery"


@pytest.mark.skipif(OPENCODE is None, reason="requires installed OpenCode v2")
@pytest.mark.parametrize("group", [None, 22])
async def test_native_attachment_tool_stages_files_with_real_task_identity(
    delivery, tmp_path, group
):
    kb = delivery
    calls = []

    async def provider(request):
        body = await request.json()
        names = {t.get("name") for t in body.get("tools", [])}
        if "qq_send_files" in names:
            assert "qq_delivery_context" in names
            calls.append(body)
            if len(calls) == 1:
                return response_stream(
                    {
                        "id": "fc_delivery_context",
                        "type": "function_call",
                        "call_id": "delivery_context_call",
                        "name": "qq_delivery_context",
                        "arguments": "{}",
                        "status": "completed",
                    }
                )
            if len(calls) == 2:
                return response_stream(
                    {
                        "id": "fc_knowledge",
                        "type": "function_call",
                        "call_id": "knowledge_call",
                        "name": "qq_send_files",
                        "arguments": json.dumps({"files": [{"path": "report.txt"}]}),
                        "status": "completed",
                    }
                )
        text = "附件已经准备好，等待交付。"
        return response_stream(
            {
                "id": "msg_source",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            },
            text=text,
        )

    provider_runner, provider_url = await start_server(provider)
    workdir = tmp_path / "workspace"
    workdir.mkdir(exist_ok=True)
    config_dir = tmp_path / "config/opencode"
    config_dir.mkdir(parents=True)
    (config_dir / "opencode.json").write_text(
        json.dumps(
            {
                "model": "fake/echo",
                "plugins": [
                    {
                        "package": str(PLUGIN),
                        "options": {
                            "socketPath": str(kb.tools.socket),
                            "tokenPath": str(kb.tools.token_path),
                        },
                    }
                ],
                "providers": {
                    "fake": {
                        "name": "local test",
                        "package": "@opencode/ai/providers/openai/responses",
                        "settings": {"baseURL": provider_url + "/v1", "apiKey": "synthetic-test"},
                        "models": {
                            "echo": {
                                "name": "echo",
                                "limit": {"context": 32768, "output": 2048},
                                "capabilities": {
                                    "tools": True,
                                    "input": ["text"],
                                    "output": ["text"],
                                },
                            }
                        },
                    }
                },
            }
        )
    )
    env = os.environ.copy()
    for kind in ("CONFIG", "DATA", "STATE", "CACHE"):
        env["XDG_" + kind + "_HOME"] = str(tmp_path / kind.lower())
    for key in (
        "OPENCODE_CONFIG",
        "OPENCODE_CONFIG_CONTENT",
        "OPENCODE_SERVER_PASSWORD",
        "SILICONFLOW_API_KEY",
        "MEMORY_DATABASE_URL",
    ):
        env.pop(key, None)
    password = uuid.uuid4().hex
    env.update(
        OPENCODE_PASSWORD=password,
        OPENCODE_CONFIG_DIR=str(config_dir),
        OPENCODE_DISABLE_MODELS_FETCH="1",
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = await asyncio.create_subprocess_exec(
        OPENCODE,
        "serve",
        "--stdio",
        "--hostname",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warn",
        cwd=workdir,
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        cfg = replace(
            kb.config,
            workdir=workdir,
            opencode_url=f"http://127.0.0.1:{port}",
            opencode_password=password,
            model="fake/echo",
        )
        async with aiohttp.ClientSession() as http:
            api = OpenCode(http, cfg)
            api.discover()
            for _ in range(100):
                try:
                    await api.request("GET", "/api/info", unwrap=False)
                    break
                except (aiohttp.ClientError, OSError):
                    await asyncio.sleep(0.1)
                except ApiError as exc:
                    if exc.status != 503:
                        raise
                    await asyncio.sleep(0.1)
            context = Context(777, 11 if group is None else 12, group)
            current = running(kb, user=context.user_id, group=group)
            await api.create_session(current["session_id"], context)
            await api.sync_context(current["session_id"], context)
            await api.prompt(current["session_id"], current["prompt_id"], "请把报告发给我", [])
            async with asyncio.timeout(30):
                await api.wait(current["session_id"])
            assert len(calls) == 3
            context_outputs = [
                i for i in calls[1].get("input", []) if i.get("type") == "function_call_output"
            ]
            context_result = json.loads(context_outputs[-1]["output"])
            assert context_result["available"] is True
            assert context_result["output_dir"].endswith(current["id"])
            outputs = [
                i for i in calls[2].get("input", []) if i.get("type") == "function_call_output"
            ]
            result = json.loads(outputs[-1]["output"])
            assert result["ok"] is True
            assert result["status"] == "queued"
            artifacts = kb.tools.artifacts(current["id"])
            assert len(artifacts) == 1 and artifacts[0]["name"] == "report.txt"
            assert kb.store.db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0
    finally:
        process.terminate()
        try:
            async with asyncio.timeout(10):
                await process.wait()
        except TimeoutError:
            process.kill()
            await process.wait()
        await provider_runner.cleanup()
