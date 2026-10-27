from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import jsonschema
import pytest

from qqbot import delivery
from qqbot.bridge import Bridge
from qqbot.config import Config
from qqbot.models import Context
from qqbot.napcat_tools import NapCatTools, json_schema
from qqbot.onebot import DeliveryUnknown, OneBot, Unavailable
from qqbot.store import Store
from qqbot.tool_identity import TaskIdentityContext

REFERENCE_VERSION = json.loads(
    (Path(__file__).resolve().parents[1] / "qqbot/napcat_catalogue.json").read_text()
)["version"]


@pytest.fixture
async def napcat(tmp_path):
    config = Config(
        napcat_url="ws://localhost:1",
        napcat_token="local-secret-token",
        allowed_users=frozenset({11, 12}),
        allowed_groups=frozenset({22, 33}),
        superadmin_user_id=11,
        napcat_tools_enabled=True,
        state_db=tmp_path / "bridge.sqlite3",
        memory_db=tmp_path / "memory.sqlite3",
        workdir=tmp_path / "workspace",
    )
    calls = []

    async def call(action, params, **kwargs):
        calls.append((action, params))
        if action == "get_version_info":
            return {"app_version": REFERENCE_VERSION}
        if action == "get_credentials":
            return {"cookies": "private-cookie-secret-value", "token": 1234567}
        if action == "get_group_info":
            return {"group_id": int(params["group_id"]), "group_name": "测试群"}
        if action == "get_status":
            return {"online": True}
        return {"message_id": 88}

    onebot = SimpleNamespace(
        self_id=777,
        ws=object(),
        requests={},
        call=AsyncMock(side_effect=call),
        upload_file=AsyncMock(return_value="/app/napcat/cache/upload.bin"),
    )
    store = Store(config.state_db)
    bridge = Bridge(
        config, store, onebot, SimpleNamespace(belongs_to=AsyncMock(return_value=False))
    )
    tools = bridge.napcat_tools
    await tools.start()
    async with aiohttp.ClientSession(
        connector=aiohttp.UnixConnector(path=str(tools.socket))
    ) as http:

        async def invoke(job, name="call", args=None, *, call_id="one", session=None, token=True):
            async with http.post(
                "http://localhost/call",
                json={
                    "session_id": session or job["session_id"],
                    "call_id": call_id,
                    "name": name,
                    "arguments": args
                    if args is not None
                    else {"action": "get_status", "params": {}},
                },
                headers={"Authorization": "Bearer " + tools.token} if token else {},
            ) as response:
                return response.status, await response.json()

        yield SimpleNamespace(
            tools=tools,
            bridge=bridge,
            config=config,
            store=store,
            onebot=onebot,
            calls=calls,
            invoke=invoke,
        )
    await tools.close()
    await bridge.memory.close()
    await bridge.knowledge.close()
    store.close()


def running(napcat, *, user=11, group=None):
    id = napcat.store.enqueue(
        Context(777, user, group), "请查询或操作 NapCat", [], config=napcat.config
    )
    napcat.store.update_job(id, session_id="ses_" + id)
    napcat.store.transition_job(id, "preparing")
    napcat.store.transition_job(id, "submitting")
    napcat.store.transition_job(id, "running")
    return napcat.store.job(id)


async def test_real_identity_auth_and_private_admin_boundary(napcat):
    n = napcat
    j = running(n)
    assert (await n.invoke(j, token=False))[0] == 401
    assert (await n.invoke(j, session="spoofed"))[0] == 403
    assert (await n.invoke(j, args={"action": "get_status", "params": {}, "user_id": 11}))[0] == 400
    outsider = running(n, user=12)
    assert (await n.invoke(outsider))[0] == 403
    assert (await n.invoke(outsider, "describe", {"action": "set_group_ban"}))[0] == 200
    assert not n.calls
    assert (await n.invoke(j))[1]["status"] == "confirmed"
    n.bridge.opencode.belongs_to.side_effect = lambda session, root: (
        session == "child" and root == j["session_id"]
    )
    assert (await n.invoke(j, session="child", call_id="child"))[0] == 200
    n.store.update_job(j["id"], cancel_requested=1)
    assert (await n.invoke(j, call_id="cancelled"))[0] == 403


async def test_actual_schema_coercion_and_unregistered_actions(napcat):
    n = napcat
    j = running(n)
    status, result = await n.invoke(
        j, args={"action": "get_group_info", "params": {"group_id": 22}}
    )
    assert status == 200 and result["status"] == "confirmed"
    assert n.calls[-1] == ("get_group_info", {"group_id": "22"})
    assert (await n.invoke(j, args={"action": "get_group_info", "params": {}}, call_id="invalid"))[
        0
    ] == 400
    n.tools.catalogue["actions"]["not_installed_test"] = {
        "available": False,
        "description": "未来接口",
        "payload": {"type": "object"},
    }
    assert (
        await n.invoke(
            j,
            args={"action": "not_installed_test", "params": {}},
            call_id="newer",
        )
    )[0] == 400
    assert not any(c[0] == "not_installed_test" for c in n.calls)
    for d in n.tools.catalogue["actions"].values():
        if d["available"]:
            jsonschema.Draft7Validator.check_schema(
                json_schema(d.get("payload", {"type": "object"}))
            )


async def test_group_scope_blocks_global_reads_private_and_ignored_scope_arguments(napcat):
    n = napcat
    j = running(n, group=22)
    assert (await n.invoke(j, args={"action": "get_group_info", "params": {"group_id": "22"}}))[1][
        "ok"
    ]
    for action, params in [
        ("get_group_info", {"group_id": "33"}),
        ("get_friend_list", {}),
        ("send_private_msg", {"user_id": "11", "message": "你好", "group_id": "22"}),
        ("get_group_list", {"group_id": "22"}),
        ("send_packet", {"cmd": "x", "data": "00", "rsp": True}),
    ]:
        assert (
            await n.invoke(j, args={"action": action, "params": params}, call_id=action + "deny")
        )[0] == 403
    ordinary = running(n, user=12, group=22)
    assert (
        await n.invoke(
            ordinary,
            args={
                "action": "set_group_ban",
                "params": {"group_id": "22", "user_id": "12", "duration": 1},
            },
        )
    )[0] == 403


async def test_call_receipts_prevent_repeated_send_and_changed_parameters(napcat):
    n = napcat
    j = running(n)
    args = {"action": "send_private_msg", "params": {"user_id": "11", "message": "测试消息"}}
    result = (await n.invoke(j, args=args))[1]
    assert result["status"] == "confirmed" and result["data"]["message_id"] == 88
    replay = (await n.invoke(j, args=args))[1]
    assert replay["replayed"] and replay["data"]["message_id"] == 88
    assert len([c for c in n.calls if c[0] == "send_private_msg"]) == 1
    assert (await n.invoke(j, args={**args, "params": {"user_id": "11", "message": "不同内容"}}))[
        0
    ] == 400
    receipt = n.tools.db.execute("select result from calls").fetchone()[0]
    assert "测试消息" not in receipt


async def test_uncertain_effects_block_new_call_ids_and_survive_restart(napcat):
    n = napcat
    j = running(n)
    await n.tools.version()
    n.onebot.call.side_effect = DeliveryUnknown("dropped")
    args = {"action": "send_like", "params": {"user_id": "11", "times": 1}}
    result = (await n.invoke(j, args=args))[1]
    assert result["status"] == "uncertain"
    assert (await n.invoke(j, args=args, call_id="different"))[1]["status"] == "uncertain"
    calls = n.onebot.call.call_count
    n.tools.db.execute("update calls set state='pending'")
    n.tools.db.commit()
    clone = NapCatTools(
        n.config, n.onebot, n.store, TaskIdentityContext(n.config, n.store, n.bridge.opencode)
    )
    try:
        assert clone.db.execute("select state from calls").fetchone()[0] == "uncertain"
    finally:
        await clone.close()
    assert n.onebot.call.call_count == calls


async def test_no_request_sent_can_be_retried_and_version_changes_are_blocked(napcat):
    n = napcat
    j = running(n)
    await n.tools.version()
    n.onebot.call.side_effect = Unavailable("offline")
    assert (await n.invoke(j))[1]["status"] == "not_sent"
    n.onebot.call.side_effect = None
    n.onebot.call.return_value = {"online": True}
    assert (await n.invoke(j))[1]["status"] == "confirmed"
    n.onebot.ws = object()
    n.onebot.call.return_value = {"app_version": "next"}
    assert (await n.invoke(j, call_id="version"))[0] == 400


async def test_cancel_during_version_read_does_not_execute_operation(napcat):
    n = napcat
    j = running(n)

    async def call(action, params, **kw):
        assert action == "get_version_info"
        n.store.update_job(j["id"], cancel_requested=1)
        return {"app_version": REFERENCE_VERSION}

    n.onebot.call.side_effect = call
    assert (
        await n.invoke(j, args={"action": "send_like", "params": {"user_id": "11", "times": 1}})
    )[0] == 403
    assert n.tools.db.execute("select count(*) from calls").fetchone()[0] == 0


async def test_credentials_remain_opaque_and_cannot_cross_root_tasks(napcat):
    n = napcat
    j = running(n)
    result = (
        await n.invoke(j, args={"action": "get_credentials", "params": {"domain": "qun.qq.com"}})
    )[1]
    text = json.dumps(result)
    assert "private-cookie-secret-value" not in text
    ref = result["data"]["cookies"]
    with pytest.raises(PermissionError):
        n.tools.resolve(j["id"], {"message": ref}, action="send_private_msg")
    assert (
        await n.invoke(
            j,
            args={
                "action": "send_private_msg",
                "params": {"user_id": "12", "message": ref},
            },
            call_id="cannot-send-cookie",
        )
    )[0] == 403
    assert not any(action == "send_private_msg" for action, _ in n.calls)
    other = running(n)
    with pytest.raises(PermissionError):
        n.tools.resolve(other["id"], {"message": ref}, action="send_private_msg")
    assert (
        "private-cookie-secret-value"
        not in n.tools.db.execute("select result from calls").fetchone()[0]
    )
    packed = n.tools.pack(j["id"], "send_packet", "raw-private-packet")
    assert "raw-private-packet" not in json.dumps(packed)
    packed = n.tools.pack(
        j["id"], "get_file", {"url": "https://example.com/file?rkey=private-value"}
    )
    assert "private-value" not in json.dumps(packed)
    url_ref = packed["data"]["url"]
    assert n.tools.resolve(j["id"], {"file": url_ref}, action="download_file_stream")[
        "file"
    ].endswith("rkey=private-value")
    with pytest.raises(PermissionError):
        n.tools.resolve(j["id"], {"message": url_ref}, action="send_private_msg")
    packet = n.tools.pack(j["id"], "send_packet", "packet", command="Original.Cmd")["data"]
    assert (
        n.tools.resolve(j["id"], {"data": packet}, action="send_packet", command="Original.Cmd")[
            "data"
        ]
        == "packet"
    )
    with pytest.raises(PermissionError):
        n.tools.resolve(j["id"], {"data": packet}, action="send_packet", command="Other.Cmd")


async def test_upload_only_reads_current_job_input_or_delivery_files(napcat):
    n = napcat
    j = running(n)
    delivery.prepare_directory(n.config, j["id"])
    p = delivery.directory(n.config, j["id"]) / "result.txt"
    p.write_text("demo")
    result = (await n.invoke(j, "upload", {"path": str(p)}))[1]
    assert result["data"]["napcat_path"] == "/app/napcat/cache/upload.bin"
    private = n.config.state_db.parent / "config-secret"
    private.write_text("secret")
    result = (await n.invoke(j, "upload", {"path": str(private)}, call_id="bad"))[1]
    assert result["status"] == "failed"
    assert n.onebot.upload_file.call_count == 1


async def test_stream_download_export_and_malformed_stream_never_leaves_partial_files(napcat):
    n = napcat
    j = running(n)

    def stream_request(action, params, *, queue_size=128):
        raw = b"file content"
        values = [
            {
                "type": "stream",
                "data_type": "file_info",
                "file_size": len(raw),
                "file_name": "demo.txt",
            },
            {
                "type": "stream",
                "data_type": "file_chunk",
                "index": 0,
                "data": base64.b64encode(raw).decode(),
                "size": len(raw),
            },
            {
                "type": "response",
                "data_type": "file_complete",
                "total_chunks": 1,
                "total_bytes": len(raw),
            },
        ]

        async def frames():
            for data in values:
                yield {"retcode": 0, "status": "ok", "data": data}

        class Stream:
            async def __aenter__(self):
                return frames()

            async def __aexit__(self, *exc):
                return False

        return Stream()

    n.onebot.stream_request = stream_request
    result = (
        await n.invoke(j, args={"action": "download_file_stream", "params": {"file_id": "f"}})
    )[1]
    assert result["status"] == "confirmed"
    exported = (
        await n.invoke(j, "export", {"file_ref": result["data"]["file_ref"]}, call_id="export")
    )[1]
    exported_path = Path(exported["data"]["path"])
    assert await asyncio.to_thread(exported_path.read_bytes) == b"file content"
    other = running(n)
    assert (
        await n.invoke(other, "export", {"file_ref": result["data"]["file_ref"]}, call_id="other")
    )[1]["status"] == "failed"

    def bad_stream_request(action, params, *, queue_size=128):
        async def frames():
            yield {
                "retcode": 0,
                "data": {
                    "type": "response",
                    "data_type": "file_complete",
                    "total_bytes": 100,
                    "total_chunks": 1,
                },
            }

        class Stream:
            async def __aenter__(self):
                return frames()

            async def __aexit__(self, *exc):
                return False

        return Stream()

    n.onebot.stream_request = bad_stream_request
    # No file_info means no download artifact may be claimed as a real file.
    result = (
        await n.invoke(
            j,
            args={"action": "download_file_stream", "params": {"file_id": "bad"}},
            call_id="badstream",
        )
    )[1]
    assert not result.get("data", {}).get("file_ref")
    assert len(list((n.tools.root / "artifacts").iterdir())) == 1


async def test_large_results_are_root_bound_and_not_archived(napcat):
    n = napcat
    j = running(n)
    await n.tools.version()
    n.onebot.call.side_effect = None
    n.onebot.call.return_value = {"message": "x" * 20000}
    result = (await n.invoke(j))[1]
    ref = result["result_ref"]
    assert len((await n.invoke(j, "result", {"ref": ref}))[1]["text"]) == 8000
    other = running(n)
    assert (await n.invoke(other, "result", {"ref": ref}))[0] == 403
    assert "x" * 100 not in n.tools.db.execute("select result from calls").fetchone()[0]


def test_reference_covers_local_and_public_api_documents():
    root = Path(__file__).resolve().parents[1]
    catalogue = json.loads((root / "qqbot/napcat_catalogue.json").read_text())
    assert catalogue["version"] == "4.18.41"
    assert sum(a["available"] for a in catalogue["actions"].values()) == 180
    assert len(catalogue["actions"]) == 180
    for action in catalogue["actions"]:
        assert (root / "docs/napcat-api" / ("NapCat-" + action + ".md")).is_file()


@pytest.mark.parametrize("value", [False, 0, "", []])
async def test_onebot_preserves_false_and_empty_scalar_results(value):
    bot = OneBot(None, "ws://test", "test")

    async def send(action, params, request):
        request.future.set_result({"status": "ok", "retcode": 0, "data": value})
        return "test"

    bot._send = send
    result = await bot.call("test", {})
    assert result == value and type(result) is type(value)


async def test_onebot_stream_request_owns_echo_lifecycle():
    class WebSocket:
        closed = False

        async def send_json(self, payload):
            self.payload = payload

    ws = WebSocket()
    bot = OneBot(None, "ws://unused", "unused")
    bot.ws = ws
    async with bot.stream_request("download_file_stream", {}, queue_size=2) as frames:
        assert len(bot.requests) == 1
        request = bot.requests[ws.payload["echo"]]
        frame = {"retcode": 0, "data": {"type": "stream", "data_type": "file_info"}}
        request.queue.put_nowait(frame)
        assert await anext(frames) == frame
    assert not bot.requests


@pytest.mark.parametrize(
    "action,params",
    [
        ("get_group_share_link", {"group_id": "22"}),
        (
            "do_group_album_comment",
            {"group_id": "22", "album_id": "album", "batch_id": "batch", "content": "comment"},
        ),
        ("delete_group_file", {"group_id": "22", "file_id": "file", "bus_id": 102}),
        ("create_flash_task", {"files": "example.txt", "validitySeconds": 7776000}),
    ],
)
async def test_updated_reference_accepts_new_interfaces_and_parameter_forms(napcat, action, params):
    n = napcat
    j = running(n)
    status, result = await n.invoke(j, args={"action": action, "params": params})
    assert status == 200 and result["status"] == "confirmed"
    assert n.calls[-1][0] == action
    assert all(n.calls[-1][1][key] == value for key, value in params.items())
    if action == "get_group_share_link":
        assert n.calls[-1][1]["need_short_url"] is True
        assert n.calls[-1][1]["src_id"] == 73


async def test_updated_group_file_business_id_bounds_are_validated(napcat):
    n = napcat
    j = running(n)
    status, _ = await n.invoke(
        j,
        args={
            "action": "delete_group_file",
            "params": {"group_id": "22", "file_id": "file", "bus_id": 0},
        },
    )
    assert status == 400
    assert not n.calls
