"""Verify document tools in an independent OpenCode instance using a local fake model."""

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
from test_memory_plugin_runtime import OPENCODE, response_stream
from test_napcat_tools import napcat as napcat
from test_napcat_tools import running

from qqbot.models import Context
from qqbot.opencode import ApiError, OpenCode

PLUGIN = Path(__file__).resolve().parents[1] / "deploy/opencode-napcat"


@pytest.mark.skipif(OPENCODE is None, reason="requires installed OpenCode v2")
async def test_native_napcat_tool_executes_with_real_task_identity(napcat, tmp_path):
    kb = napcat
    calls = []

    async def provider(request):
        body = await request.json()
        names = {t.get("name") for t in body.get("tools", [])}
        if "napcat_call" in names:
            calls.append(body)
            if len(calls) == 1:
                return response_stream(
                    {
                        "id": "fc_knowledge",
                        "type": "function_call",
                        "call_id": "knowledge_call",
                        "name": "napcat_call",
                        "arguments": json.dumps(
                            {"action": "send_like", "params": {"user_id": "11", "times": 1}}
                        ),
                        "status": "completed",
                    }
                )
        text = "已取得 NapCat 确认。"
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
    workdir.mkdir()
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
            current = running(kb)
            await api.create_session(current["session_id"], Context(777, 11))
            await api.sync_context(current["session_id"], Context(777, 11))
            await api.prompt(current["session_id"], current["prompt_id"], "请给我点一个赞", [])
            async with asyncio.timeout(30):
                await api.wait(current["session_id"])
            assert len(calls) == 2
            outputs = [
                i for i in calls[1].get("input", []) if i.get("type") == "function_call_output"
            ]
            result = json.loads(outputs[-1]["output"])
            assert result["ok"] is True
            assert result["status"] == "confirmed"
            assert ("send_like", {"user_id": "11", "times": 1}) in kb.calls
            assert len([c for c in kb.calls if c[0] == "send_like"]) == 1
    finally:
        process.terminate()
        try:
            async with asyncio.timeout(10):
                await process.wait()
        except TimeoutError:
            process.kill()
            await process.wait()
        await provider_runner.cleanup()
