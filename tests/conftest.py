from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from urllib.parse import unquote, urlsplit

import aiohttp
import pytest
from aiohttp import web

from qqbot.bridge import Bridge
from qqbot.config import Config
from qqbot.onebot import OneBot
from qqbot.opencode import OpenCode
from qqbot.store import Store

# 部署环境里的配置变量会盖过测试自己的 monkeypatch，导致校验顺序和断言漂移。
CONFIG_ENV = (
    "ALLOWED_GROUPS",
    "ALLOWED_USERS",
    "EXCLUDED_PREFIXES",
    "GROUP_READONLY_MCP_ACTIONS",
    "IMAGE_GENERATION_ENABLED",
    "IMAGE_MODEL",
    "IMAGE_OPENCODE_CONFIG",
    "IMAGE_PROVIDER",
    "IMAGE_TIMEOUT",
    "KNOWLEDGE_ENABLED",
    "LOG_LEVEL",
    "MEMORY_BASE_URL",
    "MEMORY_DATABASE_URL",
    "MEMORY_DB",
    "MEMORY_DIMENSIONS",
    "MEMORY_EMBEDDING_MODEL",
    "MEMORY_ENABLED",
    "MEMORY_MODEL",
    "MEMORY_OWNER_USER_ID",
    "MEMORY_RERANK_ENABLED",
    "MEMORY_RERANK_MODEL",
    "MEMORY_SEARCH_TIMEOUT",
    "MEMORY_TIMEOUT",
    "NAPCAT_TOKEN",
    "NAPCAT_TOOLS_ENABLED",
    "NAPCAT_WS_URL",
    "OPENCODE_AUTOSTART",
    "OPENCODE_BINARY",
    "OPENCODE_MODEL",
    "OPENCODE_PASSWORD",
    "OPENCODE_SERVICE_FILE",
    "OPENCODE_URL",
    "OPENCODE_USERNAME",
    "OPENCODE_WORKDIR",
    "SILICONFLOW_API_KEY",
    "STATE_DB",
    "SUPERADMIN_USER_ID",
    "TYPING_STATUS_ENABLED",
    "WEBUI_ENABLED",
    "WEBUI_HOST",
    "WEBUI_PORT",
    "WEBUI_PUBLIC_URL",
)


@pytest.fixture(autouse=True)
def clean_config_env(monkeypatch):
    """每个用例都从空配置起步，避免宿主机 .env 泄漏进断言。"""
    for key in CONFIG_ENV:
        monkeypatch.delenv(key, raising=False)
    yield


async def eventually(predicate, timeout=5):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


def quoted_records(prompt):
    file = next(item for item in prompt["files"] if item["name"] == "引用聊天记录.json")
    return json.loads(Path(unquote(urlsplit(file["uri"]).path)).read_text(encoding="utf-8"))


class NapCatMock:
    def __init__(self):
        self.ws = None
        self.actions = []
        self.sent = []
        self.files = {}
        self.messages = {}
        self.forward_messages = {}
        self.uploads = {}
        self.remote_files = {}
        self.media_sent = []
        self.upload_fault = ""
        self.upload_disconnect_once = False
        self.upload_gate = None
        self.media_fail = False
        self.media_no_ack = False
        self.stream_fault = ""
        self.no_send_ack = False
        self.typing_error = False
        self.typing_result = {}
        self.pokes = []
        self.poke_error = False
        self.poke_no_ack = False

    async def handle(self, request):
        if request.headers.get("Authorization") != "Bearer test-token":
            return web.Response(status=401)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.ws = ws
        async for frame in ws:
            data = json.loads(frame.data)
            action, params, echo = data["action"], data["params"], data["echo"]
            self.actions.append(data)
            result = {}
            if action == "get_login_info":
                result = {"user_id": 777}
            elif action == "get_status":
                result = {"online": True}
            elif action == "set_input_status":
                if self.typing_error:
                    await ws.send_json(
                        {"status": "failed", "retcode": 1404, "data": None, "echo": echo}
                    )
                    continue
                result = self.typing_result
            elif action == "send_poke":
                self.pokes.append(params)
                if self.poke_error:
                    await ws.send_json(
                        {"status": "failed", "retcode": 100, "data": None, "echo": echo}
                    )
                    continue
                if self.poke_no_ack:
                    await ws.close()
                    continue
            elif action in {"send_private_msg", "send_group_msg"}:
                images = [
                    segment
                    for segment in params["message"]
                    if segment["type"] in {"image", "video", "record"}
                ]
                if images:
                    if getattr(self, "message_media_fail", False):
                        await ws.send_json(
                            {"status": "failed", "retcode": 100, "data": None, "echo": echo}
                        )
                        continue
                    self.media_sent.append(
                        {
                            **params,
                            "kind": "audio" if images[0]["type"] == "record" else images[0]["type"],
                            "bytes": self.remote_files[images[0]["data"]["file"][7:]],
                        }
                    )
                self.sent.append(params)
                if self.no_send_ack or (images and self.media_no_ack):
                    await ws.close()
                    continue
                result = {"message_id": len(self.sent)}
            elif action == "upload_file_stream":
                if self.upload_gate is not None:
                    await self.upload_gate.wait()
                if self.upload_disconnect_once:
                    self.upload_disconnect_once = False
                    await ws.close()
                    continue
                stream = params["stream_id"]
                if not params.get("is_complete"):
                    state = self.uploads.setdefault(stream, {"chunks": {}, "params": params})
                    state["chunks"][params["chunk_index"]] = base64.b64decode(params["chunk_data"])
                    result = {
                        "type": "stream",
                        "stream_id": stream,
                        "status": "chunk_received",
                        "received_chunks": len(state["chunks"]),
                        "total_chunks": params["total_chunks"],
                    }
                    if self.upload_fault == "count":
                        result["received_chunks"] += 1
                else:
                    state = self.uploads[stream]
                    content = b"".join(
                        state["chunks"][index] for index in range(state["params"]["total_chunks"])
                    )
                    digest = hashlib.sha256(content).hexdigest()
                    assert digest == state["params"]["expected_sha256"]
                    path = "/napcat-cache/" + state["params"]["filename"]
                    self.remote_files[path] = content
                    result = {
                        "type": "response",
                        "stream_id": stream,
                        "status": "file_complete",
                        "file_path": path,
                        "file_size": len(content),
                        "sha256": digest,
                    }
                    if self.upload_fault == "digest":
                        result["sha256"] = "wrong"
            elif action in {"upload_private_file", "upload_group_file"}:
                if self.media_fail:
                    await ws.send_json(
                        {"status": "failed", "retcode": 100, "data": None, "echo": echo}
                    )
                    continue
                self.media_sent.append(
                    {**params, "kind": "file", "bytes": self.remote_files[params["file"]]}
                )
                if self.media_no_ack:
                    await ws.close()
                    continue
                result = {"file_id": "file_" + str(len(self.media_sent))}
            elif action == "get_msg":
                result = self.messages.get(str(params["message_id"]))
                if result is None:
                    await ws.send_json(
                        {"status": "failed", "retcode": 100, "data": None, "echo": echo}
                    )
                    continue
            elif action == "get_forward_msg":
                result = self.forward_messages.get(str(params["message_id"]))
                if result is None:
                    await ws.send_json(
                        {"status": "failed", "retcode": 100, "data": None, "echo": echo}
                    )
                    continue
            elif action == "download_file_stream":
                content = self.files[params["file_id"]]
                packets = [
                    {
                        "type": "stream",
                        "data_type": "file_info",
                        "file_name": "from-napcat",
                        "file_size": len(content),
                    }
                ]
                for index in range(0, len(content), params["chunk_size"]):
                    chunk = content[index : index + params["chunk_size"]]
                    packets.append(
                        {
                            "type": "stream",
                            "data_type": "file_chunk",
                            "index": 9
                            if self.stream_fault == "order"
                            else index // params["chunk_size"],
                            "size": len(chunk),
                            "data": base64.b64encode(chunk).decode(),
                        }
                    )
                if self.stream_fault != "incomplete":
                    packets.append(
                        {
                            "type": "response",
                            "data_type": "file_complete",
                            "total_chunks": len(packets) - 1,
                            "total_bytes": len(content),
                        }
                    )
                for packet in packets:
                    await ws.send_json(
                        {
                            "status": "ok",
                            "retcode": 0,
                            "data": packet,
                            "echo": echo,
                            "stream": "stream-action",
                        }
                    )
                continue
            await ws.send_json({"status": "ok", "retcode": 0, "data": result, "echo": echo})
        return ws

    async def emit(self, event):
        if event.get("post_type") == "message":
            original = dict(event)
            original.pop("post_type", None)
            original.pop("self_id", None)
            original["sender"] = {"user_id": event["user_id"]}
            self.messages[str(event["message_id"])] = original
        await self.ws.send_json(event)

    def texts(self):
        return [
            "".join(s["data"]["text"] for s in p["message"] if s["type"] == "text")
            for p in self.sent
        ]


class OpenCodeMock:
    def __init__(self):
        self.sessions = {}
        self.instructions = {}
        self.messages = {}
        self.prompts = []
        self.inboxes = {}
        self.defer_steers = False
        self.permissions = {}
        self.forms = {}
        self.active_ids = {}
        self.decisions = []
        self.answers = []
        self.tasks = set()
        self.mode = "normal"
        self.gates = {}
        self.lose_prompt_response = False
        self.permission_in_child = False
        self.permission_action = "edit"
        self.permission_resources = ["example.txt"]
        self.permission_metadata = {}
        self.permission_source = None
        self.page_size = 100
        self.interrupted = []
        self.reply_factory = None

    def add_task(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def cleanup(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def handle(self, request):
        if (
            request.headers.get("Authorization")
            != "Basic " + base64.b64encode(b"opencode:pw").decode()
        ):
            return web.Response(status=401)
        path, method = request.path, request.method
        if path == "/api/info":
            return web.json_response({"version": "2.0.22", "pid": 1})
        if path == "/openapi.json":
            return web.json_response(
                {
                    "paths": {
                        p: {}
                        for p in [
                            "/api/session",
                            "/api/session/{sessionID}/prompt",
                            "/api/session/{sessionID}/message",
                            "/api/experimental/session/{sessionID}/wait",
                            "/api/session/{sessionID}/permission/{requestID}/reply",
                            "/api/session/{sessionID}/form/{formID}/reply",
                            "/api/experimental/session/{sessionID}/instructions/entries/{key}",
                        ]
                    }
                }
            )
        if path == "/api/session" and method == "GET":
            items = [
                v
                for v in self.sessions.values()
                if v.get("parentID") == request.query.get("parentID")
            ]
            offset = int(request.query.get("cursor", 0))
            end = offset + self.page_size
            return web.json_response(
                {
                    "data": items[offset:end],
                    "cursor": {"next": str(end) if end < len(items) else None},
                }
            )
        if path == "/api/session" and method == "POST":
            body = await request.json()
            self.sessions[body["id"]] = {**body, "time": {"created": time.time() * 1000}}
            self.messages[body["id"]] = []
            self.instructions[body["id"]] = {}
            return web.json_response({"data": self.sessions[body["id"]]})
        if path == "/api/session/active":
            return web.json_response({"data": self.active_ids})
        if path in {"/api/permission/request", "/api/form"}:
            assert "location[directory]" in request.query
            values = self.permissions if path.endswith("request") else self.forms
            return web.json_response({"data": list(values.values())})
        if path.startswith("/api/experimental/session/") and "/instructions/entries" in path:
            parts = path.strip("/").split("/")
            sid = parts[3]
            if sid not in self.sessions:
                return web.Response(status=404)
            if method == "PUT":
                body = await request.json()
                self.instructions.setdefault(sid, {})[parts[-1]] = body["value"]
                return web.Response(status=204)
            if method == "DELETE":
                self.instructions.setdefault(sid, {}).pop(parts[-1], None)
                return web.Response(status=204)
            return web.json_response(
                {
                    "data": [
                        {"key": k, "value": v} for k, v in self.instructions.get(sid, {}).items()
                    ]
                }
            )
        if path.startswith("/api/experimental/session/") and path.endswith("/wait"):
            # Intentionally early: the bridge must not mistake this for prompt completion.
            return web.Response(status=204)
        parts = path.strip("/").split("/")
        if len(parts) < 3 or parts[:2] != ["api", "session"]:
            return web.Response(status=404)
        sid = parts[2]
        if sid not in self.sessions:
            return web.Response(status=404)
        if len(parts) == 3:
            if method == "PATCH":
                body = await request.json()
                self.sessions[sid].update(body)
                return web.Response(status=204)
            return web.json_response({"data": self.sessions[sid]})
        if parts[3] == "prompt":
            body = await request.json()
            if any(p["id"] == body["id"] for p in self.prompts):
                return web.Response(status=409)
            self.prompts.append({**body, "sessionID": sid})
            busy = sid in self.active_ids
            item = {
                "id": body["id"],
                "type": "user",
                "text": body["text"],
                "time": {"created": time.time() * 1000},
            }
            if busy and self.defer_steers and body.get("delivery") == "steer":
                self.inboxes.setdefault(sid, []).append(item)
            else:
                self.messages[sid].append(item)
                self.active_ids[sid] = {}
                if not busy:
                    self.add_task(self.generate(sid, body))
            if self.lose_prompt_response:
                self.lose_prompt_response = False
                request.transport.close()
            return web.json_response({"data": {"id": body["id"]}})
        if parts[3] == "inbox":
            if method == "GET":
                return web.json_response({"data": self.inboxes.get(sid, [])})
            self.inboxes[sid] = [
                item for item in self.inboxes.get(sid, []) if item["id"] != parts[4]
            ]
            return web.Response(status=204)
        if parts[3] == "message" and len(parts) == 5:
            item = next((m for m in self.messages[sid] if m["id"] == parts[4]), None)
            return web.json_response({"data": item}) if item else web.Response(status=404)
        if parts[3] == "message":
            items = list(reversed(self.messages[sid]))
            offset = int(request.query.get("cursor", 0))
            end = offset + self.page_size
            return web.json_response(
                {
                    "data": items[offset:end],
                    "cursor": {
                        "next": str(end) if end < len(items) else None,
                        "previous": None,
                    },
                }
            )
        if parts[3] == "permission" and parts[-1] == "reply":
            pid = parts[4]
            if pid not in self.permissions:
                return web.Response(status=404)
            body = await request.json()
            self.decisions.append((sid, pid, body["decision"]))
            self.permissions.pop(pid)
            self.gates[pid].set()
            return web.Response(status=204)
        if parts[3] == "form" and method == "POST":
            fid = parts[4]
            if fid not in self.forms:
                return web.Response(status=409)
            body = await request.json()
            self.answers.append(body["answer"])
            self.forms.pop(fid)
            self.gates[fid].set()
            return web.Response(status=204)
        if parts[3] == "form" and method == "DELETE":
            self.forms.pop(parts[4], None)
            if parts[4] in self.gates:
                self.gates[parts[4]].set()
            return web.Response(status=204)
        if parts[3] == "interrupt":
            self.interrupted.append(sid)
            self.finish(sid, outcome="interrupted")
            return web.json_response({"interrupted": True})
        return web.Response(status=404)

    async def generate(self, sid, body):
        mode = self.mode
        if mode == "stalled":
            return
        if mode == "permission":
            owner = sid
            if self.permission_in_child:
                owner = "ses_child_" + body["id"]
                self.sessions[owner] = {
                    "id": owner,
                    "parentID": sid,
                    "location": self.sessions[sid]["location"],
                }
                self.messages[owner] = []
            pid = "per_" + body["id"]
            self.permissions[pid] = {
                "id": pid,
                "sessionID": owner,
                "action": self.permission_action,
                "resources": self.permission_resources,
                "metadata": self.permission_metadata,
            }
            if self.permission_source is not None:
                self.permissions[pid]["source"] = self.permission_source
            self.gates[pid] = asyncio.Event()
            await self.gates[pid].wait()
        if mode == "form":
            fid = "frm_" + body["id"]
            self.forms[fid] = {
                "id": fid,
                "sessionID": sid,
                "title": "选择任务",
                "fields": [
                    {
                        "key": "language",
                        "type": "string",
                        "title": "语言",
                        "options": [{"value": "python", "label": "Python"}],
                    },
                    {"key": "tests", "type": "boolean", "title": "运行测试"},
                    {
                        "key": "targets",
                        "type": "multiselect",
                        "options": [
                            {"value": "a", "label": "A"},
                            {"value": "b", "label": "B"},
                        ],
                    },
                ],
            }
            self.gates[fid] = asyncio.Event()
            await self.gates[fid].wait()
        await asyncio.sleep(0.03)
        if sid in self.active_ids:
            reply = (
                self.reply_factory(sid, body)
                if self.reply_factory
                else "回复：" + body["text"].split("本次要求（包含明确引用的资料）：\n")[-1]
            )
            if asyncio.iscoroutine(reply):
                reply = await reply
            if sid in self.active_ids:
                self.finish(sid, reply, outcome="failed" if mode == "failed" else "succeeded")

    def deliver_steers(self, sid):
        self.messages[sid].extend(self.inboxes.pop(sid, []))
        self.active_ids[sid] = {}

    def finish(self, sid, text="已完成", outcome="succeeded"):
        self.active_ids.pop(sid, None)
        self.messages[sid].extend(
            [
                {
                    "id": "msg_assistant_" + str(len(self.messages[sid])),
                    "type": "assistant",
                    "content": [
                        {"type": "reasoning", "text": "不应该被发送"},
                        {"type": "text", "text": text},
                    ],
                },
                {
                    "id": "msg_idle_" + str(len(self.messages[sid])),
                    "type": "idle",
                    "outcome": outcome,
                },
            ]
        )
        self.sessions[sid]["outcome"] = outcome
        self.sessions[sid].setdefault("time", {})["idle"] = time.time() * 1000


async def start_server(handler, websocket=False):
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"{'ws' if websocket else 'http'}://127.0.0.1:{port}"


@pytest.fixture
def harness(tmp_path):
    @asynccontextmanager
    async def make(**changes):
        napcat, op = NapCatMock(), OpenCodeMock()
        nrunner, nurl = await start_server(napcat.handle, websocket=True)
        orunner, ourl = await start_server(op.handle)
        cfg = Config(
            napcat_url=nurl,
            napcat_token="test-token",
            allowed_users=frozenset({11, 12}),
            allowed_groups=frozenset({22, 23}),
            opencode_url=ourl,
            opencode_password="pw",
            autostart=False,
            workdir=tmp_path / "workspace",
            state_db=tmp_path / "state.sqlite",
            poll_interval=0.02,
            text_typing_min_delay=0.001,
            text_typing_max_delay=0.001,
            execution_timeout=5,
            interaction_timeout=5,
        )
        cfg = replace(cfg, **changes)
        async with aiohttp.ClientSession() as http:
            store = Store(cfg.state_db)
            bot = OneBot(http, nurl, "test-token")
            client = OpenCode(http, cfg)
            bridge = Bridge(cfg, store, bot, client)
            task = asyncio.create_task(bridge.run())
            bridge.task = task
            try:
                await asyncio.wait_for(bot.ready.wait(), 3)
                yield bridge, napcat, op
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                await bot.disconnect()
                await bridge.memory.close()
                store.close()
        await op.cleanup()
        await nrunner.cleanup()
        await orunner.cleanup()

    return make


def message(text="", *, user=11, group=None, at=False, attachments=None, mid=None, reply=None):
    segments = [{"type": "text", "data": {"text": text}}]
    if at:
        segments.insert(0, {"type": "at", "data": {"qq": "777"}})
    if reply is not None:
        segments.insert(0, {"type": "reply", "data": {"id": str(reply)}})
    segments.extend(attachments or [])
    return {
        "post_type": "message",
        "self_id": 777,
        "user_id": user,
        "message_id": mid if mid is not None else time.time_ns(),
        "message_type": "group" if group else "private",
        **({"group_id": group} if group else {}),
        "message": segments,
    }
