"""Exercise native OpenCode tool calls with a local fake model, never a paid API."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import uuid
from dataclasses import replace

import aiohttp
import pytest
from aiohttp import web
from conftest import start_server
from test_memory import memory as memory
from test_memory_tools import PLUGIN, running_job
from test_memory_tools import service as service

from qqbot.models import Context
from qqbot.opencode import ApiError, OpenCode

OPENCODE = os.environ.get("QQBOT_OPENCODE_TEST_BINARY") or shutil.which("opencode")


def response_stream(output, *, text=None):
    response = {
        "id": "resp_" + uuid.uuid4().hex,
        "object": "response",
        "status": "completed",
        "model": "echo",
        "output": [output],
        "usage": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
    }
    events = [
        {
            "type": "response.created",
            "response": {**response, "status": "in_progress", "output": []},
        },
        {"type": "response.output_item.added", "output_index": 0, "item": output},
    ]
    if text is None:
        events.append(
            {
                "type": "response.function_call_arguments.done",
                "output_index": 0,
                "item_id": output["id"],
                "arguments": output["arguments"],
            }
        )
    else:
        events += [
            {
                "type": "response.content_part.added",
                "output_index": 0,
                "content_index": 0,
                "item_id": output["id"],
                "part": {"type": "output_text", "text": "", "annotations": []},
            },
            {
                "type": "response.output_text.delta",
                "output_index": 0,
                "content_index": 0,
                "item_id": output["id"],
                "delta": text,
            },
            {
                "type": "response.output_text.done",
                "output_index": 0,
                "content_index": 0,
                "item_id": output["id"],
                "text": text,
            },
        ]
    events += [
        {"type": "response.output_item.done", "output_index": 0, "item": output},
        {"type": "response.completed", "response": response},
    ]
    return web.Response(
        text="".join(
            "data: " + json.dumps({**event, "sequence_number": index}) + "\n\n"
            for index, event in enumerate(events)
        ),
        content_type="text/event-stream",
    )


@pytest.mark.skipif(OPENCODE is None, reason="requires installed OpenCode v2")
async def test_real_native_plugin_writes_and_retrieves_existing_mem0_service(service, tmp_path):
    memory, _ = service
    calls = []

    async def provider(request):
        body = await request.json()
        names = {tool.get("name") for tool in body.get("tools", [])}
        if "memory_search" in names:
            calls.append(body)
            if len(calls) <= 3:
                if len(calls) == 1:
                    name, arguments = "memory_evidence", {"query": "茶"}
                elif len(calls) == 2:
                    previous = [
                        item
                        for item in body.get("input", [])
                        if item.get("type") == "function_call_output"
                    ][-1]
                    proof_result = json.loads(previous["output"])
                    proof = next(row for row in proof_result["evidence"] if row["kind"] == "user")
                    name, arguments = (
                        "memory_remember",
                        {
                            "content": "喜欢喝茶",
                            "evidence": "我喜欢喝茶",
                            "evidence_ids": [proof["id"]],
                        },
                    )
                else:
                    name, arguments = "memory_search", {"query": "茶"}
                return response_stream(
                    {
                        "id": "fc_" + str(len(calls)),
                        "type": "function_call",
                        "call_id": "call_" + str(len(calls)),
                        "name": name,
                        "arguments": json.dumps(arguments),
                        "status": "completed",
                    }
                )
        text = "记住啦"
        return response_stream(
            {
                "id": "msg_fake",
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
    config = {
        "model": "fake/echo",
        "plugins": [
            {
                "package": str(PLUGIN.parent),
                "options": {
                    "socketPath": str(memory.tools.socket),
                    "tokenPath": str(memory.tools.token_path),
                },
            }
        ],
        "providers": {
            "fake": {
                "name": "local test model",
                "package": "@opencode/ai/providers/openai/responses",
                "settings": {"baseURL": provider_url + "/v1", "apiKey": "synthetic-test"},
                "models": {
                    "echo": {
                        "name": "echo",
                        "limit": {"context": 32768, "output": 2048},
                        "capabilities": {"tools": True, "input": ["text"], "output": ["text"]},
                    }
                },
            }
        },
    }
    (config_dir / "opencode.json").write_text(json.dumps(config))
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
            memory.config,
            workdir=workdir,
            opencode_url=f"http://127.0.0.1:{port}",
            opencode_password=password,
            model="fake/echo",
        )
        memory.config = cfg
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
            job, _ = running_job(memory, "请记住，我喜欢喝茶")
            await api.create_session(job["session_id"], Context(777, 11))
            await api.sync_context(job["session_id"], Context(777, 11))
            await api.prompt(job["session_id"], job["prompt_id"], job["text"], [])
            async with asyncio.timeout(30):
                await api.wait(job["session_id"])
            _, messages = await api.turn(job["session_id"], job["prompt_id"])
            assert len(calls) == 4, [(m.get("type"), m.get("error")) for m in messages]
            assert "remembered" in json.dumps(calls[2]), [
                item
                for item in calls[2].get("input", [])
                if item.get("type") == "function_call_output"
            ]
            assert "memories" in json.dumps(calls[3])
            assert len(memory.store.entries("qq:777:11")) == 1
            assert memory.store.entries("qq:777:11")[0]["backend_id"] in memory.backend.rows
            assert memory.replies == []
    finally:
        process.terminate()
        try:
            async with asyncio.timeout(10):
                await process.wait()
        except TimeoutError:
            process.kill()
            await process.wait()
        await provider_runner.cleanup()
