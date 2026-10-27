import asyncio
import io
import json
import runpy
import wave
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import pytest

from qqbot.bridge import Bridge
from qqbot.config import Config
from qqbot.delivery import directory, prepare_directory, read_snapshot
from qqbot.models import Context
from qqbot.policy import group_operation_allowed, permissions_for
from qqbot.store import Store


@pytest.fixture
async def delivery(tmp_path):
    config = Config(
        napcat_url="ws://localhost:1",
        napcat_token="test",
        allowed_users=frozenset({11, 12}),
        allowed_groups=frozenset({22}),
        superadmin_user_id=11,
        workdir=tmp_path / "workspace",
        state_db=tmp_path / "state.sqlite",
    )
    store = Store(config.state_db)
    bridge = Bridge(
        config,
        store,
        SimpleNamespace(self_id=777),
        SimpleNamespace(belongs_to=AsyncMock(return_value=False)),
    )
    tools = bridge.delivery_tools
    await tools.start()
    async with aiohttp.ClientSession(
        connector=aiohttp.UnixConnector(path=str(tools.socket))
    ) as http:

        async def invoke(
            job, files=None, *, call_id="one", session=None, token=True, arguments=None
        ):
            async with http.post(
                "http://localhost/call",
                json={
                    "session_id": session or job["session_id"],
                    "call_id": call_id,
                    "name": "send_files",
                    "arguments": arguments if arguments is not None else {"files": files},
                },
                headers={"Authorization": "Bearer " + tools.token} if token else {},
            ) as response:
                return response.status, await response.json()

        async def context(session, *, token=True):
            async with http.post(
                "http://localhost/context",
                json={"session_id": session},
                headers={"Authorization": "Bearer " + tools.token} if token else {},
            ) as response:
                return response.status, await response.json()

        yield SimpleNamespace(
            config=config, store=store, bridge=bridge, tools=tools, invoke=invoke, context=context
        )
    await tools.close()
    store.close()


def running(env, *, user=11, group=None):
    id = env.store.enqueue(Context(777, user, group), "请发送附件", [], config=env.config)
    env.store.update_job(id, session_id="ses_" + id)
    env.store.transition_job(id, "preparing")
    env.store.transition_job(id, "submitting")
    env.store.transition_job(id, "running")
    prepare_directory(env.config, id)
    (directory(env.config, id) / "report.txt").write_bytes(b"report")
    return env.store.job(id)


async def test_auth_real_identity_and_no_model_supplied_target(delivery):
    env = delivery
    job = running(env, user=12, group=22)
    files = [{"path": "report.txt"}]
    assert (await env.invoke(job, files, token=False))[0] == 401
    assert (await env.invoke(job, files, session="another-session"))[0] == 403
    assert (await env.invoke(job, arguments={"files": files, "user_id": 11}))[0] == 400
    code, result = await env.invoke(job, files)
    assert code == 200 and result["status"] == "queued"
    assert result["files"] == [{"name": "report.txt", "kind": "file", "size": 6}]
    assert env.store.db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0
    assert env.tools.socket.stat().st_mode & 0o777 == 0o600
    assert env.tools.token_path.stat().st_mode & 0o777 == 0o600
    assert group_operation_allowed(env.config, {"action": "qq_send_files"}, None)
    assert any(
        r["action"] == "qq_send_files" and r["effect"] == "allow"
        for r in permissions_for(env.config, Context(777, 12, 22))
    )


async def test_context_only_exposes_current_root_or_child_task_directories(delivery):
    env = delivery
    job = running(env, user=12, group=22)
    assert (await env.context(job["session_id"], token=False))[0] == 401
    assert (await env.context("another-session"))[0] == 403
    code, context = await env.context(job["session_id"])
    assert code == 200 and context["available"] is True
    assert context["output_dir"] == str(directory(env.config, job["id"]))
    assert context["input_dir"] == str(env.config.workdir / ".qq-attachments" / job["id"])
    assert context["steer_input_dirs"] == []
    assert context["max_files"] == env.config.max_attachments
    assert context["max_bytes"] == env.config.max_attachment_bytes
    assert context["immediate"] is False
    assert context["image_generation_enabled"] is False
    assert "token" not in json.dumps(context)
    assert group_operation_allowed(env.config, {"action": "qq_delivery_context"}, None)
    assert any(
        r["action"] == "qq_delivery_context" and r["effect"] == "allow"
        for r in permissions_for(env.config, Context(777, 12, 22))
    )
    env.bridge.opencode.belongs_to.return_value = True
    assert (await env.context("child-session"))[1] == context
    assert env.tools.artifacts(job["id"]) == []
    assert env.store.db.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0
    env.store.cancel_job(job["id"])
    assert (await env.context(job["session_id"]))[0] == 403


async def test_snapshots_idempotency_dedup_and_restart(delivery):
    env = delivery
    job = running(env)
    files = [{"path": "report.txt"}]
    first = (await env.invoke(job, files))[1]
    original = directory(env.config, job["id"]) / "report.txt"
    original.write_bytes(b"changed")
    assert (await env.invoke(job, files))[1]["replayed"]
    assert read_snapshot(env.tools.artifacts(job["id"])[0], env.config, job["id"]) == b"report"
    assert (await env.invoke(job, [{"path": "other.txt"}]))[0] == 400
    original.write_bytes(b"report")
    duplicate = (await env.invoke(job, files, call_id="another-call"))[1]
    assert duplicate["deduplicated"] and duplicate["total_files"] == 1
    await env.tools.close()
    await env.tools.start()
    original.unlink()
    replay = (await env.invoke(job, files))[1]
    assert replay["request_id"] == first["request_id"] and replay["replayed"]
    assert len(env.tools.artifacts(job["id"])) == 1


@pytest.mark.parametrize("fault", ["other-job", "outside", "symlink", "empty", "wrong-kind"])
async def test_file_access_and_media_validation(delivery, tmp_path, fault):
    env = delivery
    job = running(env)
    file = directory(env.config, job["id"]) / "report.txt"
    item = {"path": str(file)}
    if fault == "other-job":
        item["path"] = str(directory(env.config, "previous-job") / "report.txt")
    elif fault == "outside":
        outside = tmp_path / "private.env"
        outside.write_bytes(b"private")
        item["path"] = str(outside)
    elif fault == "symlink":
        alias = file.with_name("alias.txt")
        alias.symlink_to(file)
        item["path"] = str(alias)
    elif fault == "empty":
        file.write_bytes(b"")
    else:
        item["kind"] = "video"
    assert (await env.invoke(job, [item]))[0] == 400
    assert env.tools.artifacts(job["id"]) == []


@pytest.mark.parametrize("count,bytes_limit", [(1, 100), (10, 6)], ids=["count", "bytes"])
async def test_task_limits_apply_across_calls_and_duplicates_do_not_consume_them(
    delivery, count, bytes_limit
):
    env = delivery
    env.tools.config = replace(env.config, max_attachments=count, max_attachment_bytes=bytes_limit)
    job = running(env)
    assert (await env.invoke(job, [{"path": "report.txt"}]))[0] == 200
    assert (await env.invoke(job, [{"path": "report.txt"}], call_id="duplicate"))[0] == 200
    (directory(env.config, job["id"]) / "another.txt").write_bytes(b"x")
    assert (await env.invoke(job, [{"path": "another.txt"}], call_id="extra"))[0] == 400
    assert len(env.tools.artifacts(job["id"])) == 1


async def test_child_session_and_only_admitted_steer_inputs(delivery):
    env = delivery
    job = running(env, user=12)
    env.bridge.opencode.belongs_to.side_effect = lambda child, parent: (
        child == "child" and parent == job["session_id"]
    )
    assert (await env.invoke(job, [{"path": "report.txt"}], session="child"))[0] == 200
    context = Context(777, 12)
    steer_id = env.store.enqueue(
        context, "补充附件", [], config=env.config, steer_parent_id=job["id"]
    )
    steer = env.store.job(steer_id)
    assert steer["steer_parent_id"] == job["id"]
    input_file = env.config.workdir / ".qq-attachments" / steer_id / "input.txt"
    input_file.parent.mkdir(parents=True)
    input_file.write_bytes(b"input")
    files = [{"path": str(input_file)}]
    assert (await env.context("child"))[1]["steer_input_dirs"] == []
    assert (await env.invoke(job, files, call_id="unsubmitted"))[0] == 400
    env.store.update_job(steer_id, session_id=job["session_id"])
    env.store.acknowledge(steer_id)
    assert (await env.context("child"))[1]["steer_input_dirs"] == [str(input_file.parent)]
    assert (await env.invoke(job, files, call_id="submitted"))[0] == 200


async def test_cancel_during_snapshot_never_registers_files(delivery, monkeypatch):
    import qqbot.delivery_tools as module

    env = delivery
    job = running(env)
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(function, *args, **kwargs):
        entered.set()
        await release.wait()
        return function(*args, **kwargs)

    monkeypatch.setattr(module.asyncio, "to_thread", delayed)
    pending = asyncio.create_task(env.invoke(job, [{"path": "report.txt"}]))
    await entered.wait()
    env.store.cancel_job(job["id"])
    release.set()
    assert (await pending)[0] == 403
    assert env.tools.artifacts(job["id"]) == []


@pytest.mark.parametrize("state", ["done", "cancelled", "queued"])
async def test_inactive_tasks_cannot_submit(delivery, state):
    job = running(delivery) if state != "queued" else None
    if job is None:
        id = delivery.store.enqueue(Context(777, 11), "请发送附件", [], config=delivery.config)
        delivery.store.update_job(id, session_id="ses_" + id)
        job = delivery.store.job(id)
    elif state == "cancelled":
        delivery.store.update_job(job["id"], status="cancelling")
        delivery.store.update_job(job["id"], status="cancelled")
    else:
        delivery.store.update_job(job["id"], status=state)
    assert (await delivery.invoke(job, [{"path": "report.txt"}]))[0] == 403
    assert (await delivery.context(job["session_id"]))[0] == 403


async def test_batch_preparation_is_atomic_and_force_file_is_supported(delivery):
    job = running(delivery)
    assert (await delivery.invoke(job, [{"path": "report.txt"}, {"path": "missing.txt"}]))[0] == 400
    assert delivery.tools.artifacts(job["id"]) == []
    path = directory(delivery.config, job["id"]) / "image.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\nimage")
    result = (await delivery.invoke(job, [{"path": str(path), "kind": "file"}], call_id="as-file"))[
        1
    ]
    assert result["files"][0]["kind"] == "file"


def wave_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 80)
    return output.getvalue()


MEDIA = [
    ("picture.png", b"\x89PNG\r\n\x1a\nimage", "image"),
    ("clip.mp4", b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp42", "video"),
    ("recording.wav", wave_bytes(), "audio"),
    ("paper.txt", b"document", "file"),
]


@pytest.mark.parametrize("name,data,kind", MEDIA, ids=["image", "video", "audio", "document"])
@pytest.mark.parametrize("group", [None, 22])
async def test_each_media_type_uses_native_tool_and_correct_chat(harness, name, data, kind, group):
    from conftest import eventually, message

    async with harness() as (bridge, nap, op):

        async def reply(sid, body):
            job = bridge.store.latest(Context(777, 11, group))
            path = directory(bridge.config, job["id"]) / name
            path.write_bytes(data)
            result = await bridge.delivery_tools.submit(
                sid, "media", {"files": [{"path": str(path)}]}
            )
            assert result["status"] == "queued" and result["files"][0]["kind"] == kind
            return "准备好啦"

        op.reply_factory = reply
        await nap.emit(message("把附件发给我", group=group, at=group is not None))
        await eventually(
            lambda: (
                (job := bridge.store.latest(Context(777, 11, group))) and job["status"] == "done"
            )
        )
        assert len(nap.media_sent) == 1
        sent = nap.media_sent[0]
        assert sent["kind"] == kind and sent["bytes"] == data
        assert sent["user_id" if group is None else "group_id"] == ("11" if group is None else "22")
        assert any("准备好啦" in text for text in nap.texts())
        media_index = next(
            i
            for i, action in enumerate(nap.actions)
            if action["action"] in {"upload_private_file", "upload_group_file"}
            or any(
                s["type"] in {"image", "video", "record"}
                for s in action["params"].get("message", [])
            )
        )
        text_index = next(
            i
            for i, action in enumerate(nap.actions)
            if any(
                s["type"] == "text" and "准备好啦" in s["data"]["text"]
                for s in action["params"].get("message", [])
            )
        )
        assert media_index < text_index
        assert all("<qq-delivery" not in text for text in nap.texts())


@pytest.mark.parametrize("name,data,kind", MEDIA[1:3], ids=["video", "audio"])
async def test_uncertain_media_send_blocks_completion_and_is_not_retried(harness, name, data, kind):
    from conftest import eventually, message

    async with harness() as (bridge, nap, op):
        nap.media_no_ack = True

        async def reply(sid, body):
            job = bridge.store.latest(Context(777, 11))
            (directory(bridge.config, job["id"]) / name).write_bytes(data)
            await bridge.delivery_tools.submit(sid, "uncertain", {"files": [{"path": name}]})
            return "全部处理完成"

        op.reply_factory = reply
        await nap.emit(message("发送这个媒体"))
        await eventually(
            lambda: (
                (job := bridge.store.latest(Context(777, 11))) and job["status"] == "send_uncertain"
            )
        )
        assert len(nap.media_sent) == 1 and nap.media_sent[0]["kind"] == kind
        assert not any("全部处理完成" in text or "放上来啦" in text for text in nap.texts())
        assert nap.pokes == []


async def test_restart_preserves_submitted_snapshots_before_turn_completion(harness):
    from conftest import eventually, message

    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("准备附件"))
        await eventually(lambda: bool(op.prompts))
        sid = op.prompts[0]["sessionID"]
        job = bridge.store.latest(Context(777, 11))
        path = directory(bridge.config, job["id"]) / "report.txt"
        path.write_bytes(b"original report")
        await bridge.delivery_tools.submit(sid, "durable", {"files": [{"path": str(path)}]})
        assert nap.media_sent == []
        path.unlink()
        bridge.task.cancel()
        await asyncio.gather(bridge.task, return_exceptions=True)
        await bridge.onebot.disconnect()
        bridge.store.close()
        store = Store(bridge.config.state_db)
        restored = Bridge(bridge.config, store, bridge.onebot, bridge.opencode)
        task = asyncio.create_task(restored.run())
        try:
            await eventually(lambda: restored.delivery_tools.runner is not None)
            op.finish(sid, "文件已准备好")
            await eventually(lambda: store.job(job["id"])["status"] == "done")
            assert len(nap.media_sent) == 1
            assert nap.media_sent[0]["bytes"] == b"original report"
            assert len(op.prompts) == 1
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await bridge.onebot.disconnect()
            store.close()


async def test_queued_attachments_are_not_sent_after_cancel(harness):
    from conftest import eventually, message

    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("稍后发附件"))
        await eventually(lambda: bool(op.prompts))
        sid = op.prompts[0]["sessionID"]
        job = bridge.store.latest(Context(777, 11))
        (directory(bridge.config, job["id"]) / "report.txt").write_bytes(b"report")
        await bridge.delivery_tools.submit(sid, "cancelled", {"files": [{"path": "report.txt"}]})
        await nap.emit(message("/cancel"))
        await eventually(lambda: bridge.store.job(job["id"])["status"] == "cancelled")
        assert nap.media_sent == [] and nap.pokes == []


async def test_old_text_manifest_never_drives_attachment_sending(harness):
    from conftest import eventually, message

    from qqbot.delivery import marker

    async with harness() as (bridge, nap, op):

        def reply(sid, body):
            job = bridge.store.latest(Context(777, 11))
            (directory(bridge.config, job["id"]) / "report.txt").write_bytes(b"report")
            return (
                "普通正文\n"
                + marker(job["id"])
                + '\n{"files":[{"path":"report.txt"}]}\n</qq-delivery>'
            )

        op.reply_factory = reply
        await nap.emit(message("普通聊天"))
        await eventually(
            lambda: (job := bridge.store.latest(Context(777, 11))) and job["status"] == "done"
        )
        assert nap.media_sent == [] and nap.texts() == ["普通正文"]


def test_installer_preserves_providers_and_other_plugins(tmp_path):
    installer = runpy.run_path(
        str(Path(__file__).parents[1] / "deploy/provision_delivery_tools.py")
    )
    workdir = tmp_path / "workspace"
    workdir.mkdir()
    config = Config(
        napcat_url="ws://localhost:1",
        napcat_token="test",
        allowed_users=frozenset({11}),
        workdir=workdir,
        state_db=tmp_path / "state.sqlite",
    )
    original = {
        "providers": {"existing": {"settings": {"apiKey": "synthetic-test"}}},
        "plugins": ["another-plugin", {"package": "memory-plugin", "options": {"keep": True}}],
    }
    path = workdir / "opencode.json"
    path.write_text(json.dumps(original))
    installer["install"](config)
    installer["install"](config)
    current = json.loads(path.read_text())
    assert current["providers"] == original["providers"]
    assert current["plugins"][:2] == original["plugins"]
    assert len(current["plugins"]) == 3
    assert path.stat().st_mode & 0o777 == 0o600


async def test_immediate_mode_queues_media_before_turn_ends(tmp_path):
    """即时模式下，附件在提交时就进入发送队列，不必等任务结束。"""
    config = Config(
        napcat_url="ws://localhost:1",
        napcat_token="test",
        allowed_users=frozenset({11}),
        allowed_groups=frozenset(),
        superadmin_user_id=11,
        workdir=tmp_path / "workspace",
        state_db=tmp_path / "state.sqlite",
        delivery_immediate=True,
    )
    store = Store(config.state_db)
    bridge = Bridge(
        config,
        store,
        SimpleNamespace(self_id=777),
        SimpleNamespace(belongs_to=AsyncMock(return_value=False)),
    )
    tools = bridge.delivery_tools
    await tools.start()
    try:
        job = running(SimpleNamespace(config=config, store=store), user=11)
        async with aiohttp.ClientSession(
            connector=aiohttp.UnixConnector(path=str(tools.socket))
        ) as http:
            async with http.post(
                "http://localhost/call",
                json={
                    "session_id": job["session_id"],
                    "call_id": "immediate",
                    "name": "send_files",
                    "arguments": {"files": [{"path": "report.txt"}]},
                },
                headers={"Authorization": "Bearer " + tools.token},
            ) as response:
                result = await response.json()
        assert result["status"] == "queued"
        rows = store.db.execute(
            "SELECT dedupe_key,kind,status FROM outbox WHERE job_id=?", (job["id"],)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["kind"] == "file"
        assert rows[0]["dedupe_key"].startswith("immediate:")
        # 任务还没结束，附件已经可发。
        assert store.job(job["id"])["status"] == "running"
    finally:
        await tools.close()
        store.close()


@pytest.mark.parametrize("group", [None, 22])
@pytest.mark.parametrize("batch_sizes", [(1, 1, 1, 1), (2, 1)])
async def test_immediate_multiple_submissions_all_arrive_once(harness, group, batch_sizes):
    from conftest import eventually, message

    async with harness(delivery_immediate=True) as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("把本轮图片发给我", group=group, at=group is not None))
        await eventually(lambda: bool(op.prompts))
        sid = op.prompts[0]["sessionID"]
        job = bridge.store.latest(Context(777, 11, group))
        expected, calls = [], []
        for batch_index, size in enumerate(batch_sizes):
            files = []
            for _ in range(size):
                index = len(expected)
                data = b"\x89PNG\r\n\x1a\n" + bytes([index])
                path = directory(bridge.config, job["id"]) / f"code-{index}.png"
                path.write_bytes(data)
                expected.append(data)
                files.append({"path": str(path)})
            arguments = {"files": files}
            call_id = f"batch-{batch_index}"
            receipt = await bridge.delivery_tools.submit(sid, call_id, arguments)
            assert receipt["status"] == "queued"
            assert receipt["total_files"] == len(expected)
            calls.append((call_id, arguments))
            await eventually(lambda: len(nap.media_sent) == len(expected))
            assert bridge.store.job(job["id"])["status"] == "running"

        replay = await bridge.delivery_tools.submit(sid, *calls[0])
        assert replay["replayed"] is True
        duplicate = await bridge.delivery_tools.submit(sid, "duplicate", calls[0][1])
        assert duplicate["deduplicated"] is True
        op.finish(sid, "图片已准备好")
        await eventually(lambda: bridge.store.job(job["id"])["status"] == "done")
        await eventually(lambda: len(nap.pokes) == 1)
        assert [item["bytes"] for item in nap.media_sent] == expected
        assert all(item["kind"] == "image" for item in nap.media_sent)
        target, value = ("user_id", "11") if group is None else ("group_id", "22")
        assert all(item[target] == value for item in nap.media_sent)
        rows = bridge.store.db.execute(
            "SELECT dedupe_key,status FROM outbox WHERE job_id=? AND kind='image'",
            (job["id"],),
        ).fetchall()
        assert len({row["dedupe_key"] for row in rows}) == len(expected)
        assert all(row["status"] == "sent" for row in rows)


async def test_immediate_mode_marks_media_sent_before_turn_ends(tmp_path):
    """附件先于任务结束发出时，完成阶段按已发送收尾，不重复插入。"""
    config = Config(
        napcat_url="ws://localhost:1",
        napcat_token="test",
        allowed_users=frozenset({11}),
        allowed_groups=frozenset(),
        superadmin_user_id=11,
        workdir=tmp_path / "workspace",
        state_db=tmp_path / "state.sqlite",
        delivery_immediate=True,
    )
    store = Store(config.state_db)
    bridge = Bridge(
        config,
        store,
        SimpleNamespace(self_id=777),
        SimpleNamespace(belongs_to=AsyncMock(return_value=False)),
    )
    tools = bridge.delivery_tools
    await tools.start()
    try:
        env = SimpleNamespace(config=config, store=store)
        job = running(env, user=11)
        async with aiohttp.ClientSession(
            connector=aiohttp.UnixConnector(path=str(tools.socket))
        ) as http:
            async with http.post(
                "http://localhost/call",
                json={
                    "session_id": job["session_id"],
                    "call_id": "immediate-done",
                    "name": "send_files",
                    "arguments": {"files": [{"path": "report.txt"}]},
                },
                headers={"Authorization": "Bearer " + tools.token},
            ) as response:
                assert (await response.json())["status"] == "queued"
        row = store.db.execute("SELECT * FROM outbox WHERE job_id=?", (job["id"],)).fetchone()
        # 模拟发送端确认：上传并发送成功。
        store.update_outbox(row["id"], "sent")
        artifacts = tools.artifacts(job["id"])
        with store.db:
            store.db.execute("UPDATE jobs SET status='reply_ready' WHERE id=?", (job["id"],))
        store.complete(job["id"], Context(777, 11), "好的", 1800, artifacts=artifacts)
        remaining = store.db.execute(
            "SELECT count(*) FROM outbox WHERE job_id=? AND dedupe_key LIKE 'result:%:media:%'",
            (job["id"],),
        ).fetchone()[0]
        assert remaining == 0
        kinds = [
            row[0]
            for row in store.db.execute(
                "SELECT kind FROM outbox WHERE job_id=? ORDER BY id", (job["id"],)
            )
        ]
        # 只有正文一条文本，附件没有重复插入。
        assert kinds.count("file") == 1
        assert kinds.count("text") == 1
    finally:
        await tools.close()
        store.close()


async def test_immediate_mode_blocks_unfinished_media_on_failure(tmp_path):
    """任务失败时，即时模式中还没发出去的附件不再补发。"""
    config = Config(
        napcat_url="ws://localhost:1",
        napcat_token="test",
        allowed_users=frozenset({11}),
        allowed_groups=frozenset(),
        superadmin_user_id=11,
        workdir=tmp_path / "workspace",
        state_db=tmp_path / "state.sqlite",
        delivery_immediate=True,
    )
    store = Store(config.state_db)
    bridge = Bridge(
        config,
        store,
        SimpleNamespace(self_id=777),
        SimpleNamespace(belongs_to=AsyncMock(return_value=False)),
    )
    tools = bridge.delivery_tools
    await tools.start()
    try:
        env = SimpleNamespace(config=config, store=store)
        job = running(env, user=11)
        async with aiohttp.ClientSession(
            connector=aiohttp.UnixConnector(path=str(tools.socket))
        ) as http:
            async with http.post(
                "http://localhost/call",
                json={
                    "session_id": job["session_id"],
                    "call_id": "immediate-failed",
                    "name": "send_files",
                    "arguments": {"files": [{"path": "report.txt"}]},
                },
                headers={"Authorization": "Bearer " + tools.token},
            ) as response:
                assert (await response.json())["status"] == "queued"
        # 发送端还没取走，任务就失败了。
        with store.db:
            store.db.execute(
                "UPDATE jobs SET status='reply_ready',error=? WHERE id=?",
                ("OpenCode 任务失败", job["id"]),
            )
        store.finish_delivery(job["id"])
        status = store.db.execute(
            "SELECT status FROM outbox WHERE job_id=? AND kind='file'", (job["id"],)
        ).fetchone()[0]
        assert status == "blocked"
        assert store.job(job["id"])["status"] == "failed"
    finally:
        await tools.close()
        store.close()
