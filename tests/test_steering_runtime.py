"""Verify native steering with an isolated OpenCode and a local, free fake model."""

import asyncio
import json
import os
import socket
import uuid

import aiohttp
import pytest
from conftest import start_server
from test_memory_plugin_runtime import OPENCODE, response_stream

from qqbot.config import Config
from qqbot.models import Context
from qqbot.opencode import ApiError, OpenCode, final_reply


@pytest.mark.skipif(OPENCODE is None, reason="requires installed OpenCode v2")
async def test_native_steer_is_seen_on_next_model_step_without_interrupt(tmp_path):
    calls = []
    started, release = asyncio.Event(), asyncio.Event()

    async def provider(request):
        calls.append(await request.json())
        if len(calls) == 1:
            started.set()
            await release.wait()
        text = "初稿" if len(calls) == 1 else "已根据补充改为中文"
        return response_stream(
            {
                "id": "msg_" + uuid.uuid4().hex,
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
                "providers": {
                    "fake": {
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
        config = Config(
            napcat_url="ws://127.0.0.1:1",
            napcat_token="synthetic-test",
            allowed_users=frozenset({11}),
            workdir=workdir,
            model="fake/echo",
            autostart=False,
            opencode_url=f"http://127.0.0.1:{port}",
            opencode_password=password,
        )
        async with aiohttp.ClientSession() as http:
            api = OpenCode(http, config)
            api.discover()
            async with asyncio.timeout(15):
                while True:
                    try:
                        await api.request("GET", "/api/info", unwrap=False)
                        break
                    except (aiohttp.ClientError, OSError):
                        await asyncio.sleep(0.1)
                    except ApiError as exc:
                        if exc.status != 503:
                            raise
                        await asyncio.sleep(0.1)
            sid = "ses_" + uuid.uuid4().hex
            first, second = ("msg_" + uuid.uuid4().hex for _ in range(2))
            await api.create_session(sid, Context(777, 11))
            await api.prompt(sid, first, "写一段介绍", [], delivery="steer")
            await asyncio.wait_for(started.wait(), 15)
            await api.prompt(sid, second, "补充：请用中文", [], delivery="steer")
            assert sid in await api.active()
            assert await api.admitted(sid, second)
            release.set()
            async with asyncio.timeout(30):
                await api.wait(sid)
            _, messages = await api.turn(sid, first)
            assert len(calls) == 2
            assert "补充：请用中文" in json.dumps(calls[1], ensure_ascii=False)
            assert final_reply(messages, "succeeded") == "已根据补充改为中文"
            assert sum(item["type"] == "idle" for item in messages) == 1
            assert not any(item.get("error") for item in messages)
    finally:
        release.set()
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 10)
        except TimeoutError:
            process.kill()
            await process.wait()
        await provider_runner.cleanup()
