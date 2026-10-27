import asyncio
import json
import sqlite3
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import eventually, message

from qqbot import delivery_tools as bridge_module
from qqbot.bridge import Bridge
from qqbot.config import Config
from qqbot.delivery import (
    DELIVERY_ENTRY_KEY,
    DeliveryError,
    directory,
    marker,
    prepare_directory,
    read_snapshot,
    snapshot_reply,
)
from qqbot.models import Context
from qqbot.store import Store

IMAGE = b"\x89PNG\r\n\x1a\nimage"


def receipt(job_id, files, caption="处理完成"):
    return f"{caption}\n{marker(job_id)}\n{json.dumps({'files': files})}\n</qq-delivery>"


def config(tmp_path, **changes):
    cfg = Config(
        napcat_url="ws://localhost:3001",
        napcat_token="test",
        allowed_users=frozenset({11}),
        workdir=tmp_path / "workspace",
        state_db=tmp_path / "state.sqlite",
    )
    return replace(cfg, **changes)


def model_deliveries(bridge, op, files, transform=None):
    async def reply(sid, body):
        job_id = bridge.store.db.execute(
            "SELECT id FROM jobs WHERE prompt_id=?", (body["id"],)
        ).fetchone()[0]
        root = directory(bridge.config, job_id)
        manifest = []
        for name, data in files:
            (root / name).write_bytes(data)
            manifest.append({"path": name, "name": name})
        if transform:
            manifest = transform(job_id, manifest, root)
        try:
            await bridge.delivery_tools.submit(sid, "files-" + body["id"], {"files": manifest})
        except (DeliveryError, PermissionError):
            return "这次的附件没能准备好发回来，文件还没交付。可以让我检查后重新发一次呀。"
        return "处理完成"

    op.reply_factory = reply


@pytest.mark.parametrize("group", [None, 22])
@pytest.mark.parametrize(
    "name,data,kind", [("photo.png", IMAGE, "image"), ("报告.txt", b"edited report", "file")]
)
async def test_media_returns_to_the_original_chat_and_confirmation_follows_delivery(
    harness, group, name, data, kind
):
    async with harness() as (bridge, nap, op):
        model_deliveries(bridge, op, [(name, data)])
        await nap.emit(message("编辑后发给我", group=group, at=group is not None))
        context = Context(777, 11, group)
        await eventually(lambda: bridge.store.latest(context) is not None)
        await eventually(lambda: bridge.store.latest(context)["status"] == "done")
        assert len(nap.media_sent) == 1
        media = nap.media_sent[0]
        assert media["kind"] == kind
        assert media["bytes"] == data
        key, target = ("user_id", "11") if group is None else ("group_id", "22")
        assert media[key] == target
        if kind == "file":
            assert media["name"] == name
            assert media["file"].startswith("/napcat-cache/")
            expected = "upload_private_file" if group is None else "upload_group_file"
            assert any(action["action"] == expected for action in nap.actions)
        else:
            assert media["message"][0]["type"] == "image"
            assert not any(
                action["action"] in {"upload_private_file", "upload_group_file"}
                for action in nap.actions
            )
        assert nap.sent[-1]["message"][-1] == {"type": "text", "data": {"text": "处理完成"}}
        assert not any("<qq-delivery" in value for value in nap.texts())
        assert nap.sent[-1]["message"][-1]["type"] == "text"
        sid = op.prompts[0]["sessionID"]
        assert DELIVERY_ENTRY_KEY not in op.instructions[sid]
        if group is not None:
            assert op.sessions[sid]["permissions"][0]["effect"] == "ask"


async def test_large_file_uses_multiple_verified_chunks(harness):
    async with harness() as (bridge, nap, op):
        content = b"A" * (65536 + 17)
        model_deliveries(bridge, op, [("report.bin", content)])
        await nap.emit(message("把报告发给我"))
        await eventually(lambda: bool(nap.media_sent))
        assert nap.media_sent[0]["bytes"] == content
        chunks = [
            action
            for action in nap.actions
            if action["action"] == "upload_file_stream" and "chunk_data" in action["params"]
        ]
        assert len(chunks) == 2
        assert [action["params"]["chunk_index"] for action in chunks] == [0, 1]


@pytest.mark.parametrize("fault", ["count", "digest", "native"])
async def test_upload_or_file_send_failure_blocks_successful_confirmation(harness, fault):
    async with harness() as (bridge, nap, op):
        nap.upload_fault = fault if fault != "native" else ""
        nap.media_fail = fault == "native"
        model_deliveries(bridge, op, [("report.txt", b"edited")])
        await nap.emit(message("编辑后发给我"))
        await eventually(lambda: any("没能发成功" in value for value in nap.texts()))
        assert bridge.store.latest(Context(777, 11))["status"] == "send_failed"
        assert not any("处理完成" in value or "放上来啦" in value for value in nap.texts())
        assert nap.media_sent == []


async def test_lost_native_send_ack_is_not_retried(harness):
    async with harness() as (bridge, nap, op):
        nap.media_no_ack = True
        model_deliveries(bridge, op, [("report.txt", b"edited")])
        await nap.emit(message("编辑后发给我"))
        await eventually(
            lambda: any("发送结果还没确认" in value for value in nap.texts()), timeout=8
        )
        assert bridge.store.latest(Context(777, 11))["status"] == "send_uncertain"
        await nap.emit(message("/status"))
        await eventually(lambda: any("这个聊天还有" in value for value in nap.texts()))
        assert len(nap.media_sent) == 1
        assert sum(action["action"] == "upload_private_file" for action in nap.actions) == 1
        assert not any("放上来啦" in value for value in nap.texts())
        assert len(op.prompts) == 1


async def test_cache_upload_disconnect_can_retry_without_duplicate_qq_delivery(harness):
    async with harness() as (bridge, nap, op):
        nap.upload_disconnect_once = True
        model_deliveries(bridge, op, [("report.txt", b"edited")])
        await nap.emit(message("编辑后发给我"))
        await eventually(lambda: "处理完成" in nap.texts(), timeout=8)
        assert len(nap.media_sent) == 1
        assert sum(action["action"] == "upload_private_file" for action in nap.actions) == 1
        assert len(op.prompts) == 1


async def test_partial_delivery_does_not_claim_the_whole_batch_was_sent(harness):
    async with harness() as (bridge, nap, op):
        nap.media_fail = True
        model_deliveries(bridge, op, [("photo.png", IMAGE), ("report.txt", b"edited")])
        await nap.emit(message("图片和报告都发给我"))
        await eventually(lambda: any("完整结果还没交付" in value for value in nap.texts()))
        assert [item["kind"] for item in nap.media_sent] == ["image"]
        assert not any("放上来啦" in value for value in nap.texts())


async def test_cancel_during_cache_upload_blocks_the_qq_send(harness):
    async with harness() as (bridge, nap, op):
        nap.upload_gate = asyncio.Event()
        model_deliveries(bridge, op, [("report.txt", b"edited")])
        await nap.emit(message("编辑后发给我"))
        await eventually(
            lambda: any(action["action"] == "upload_file_stream" for action in nap.actions)
        )
        context = Context(777, 11)
        assert bridge.store.latest(context)["status"] == "delivering"
        await nap.emit(message("/cancel"))
        await eventually(lambda: bridge.store.latest(context)["status"] == "cancelled")
        nap.upload_gate.set()
        await eventually(lambda: bool(nap.sent))
        assert nap.media_sent == []
        assert not any("放上来啦" in value for value in nap.texts())
        assert bridge.store.latest(context)["status"] == "cancelled"


async def test_cancel_during_snapshot_does_not_reopen_the_completed_task(harness, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = bridge_module.snapshot_files

    def delayed(*args, **kwargs):
        entered.set()
        release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(bridge_module, "snapshot_files", delayed)
    async with harness() as (bridge, nap, op):
        model_deliveries(bridge, op, [("report.txt", b"edited")])
        try:
            await nap.emit(message("编辑后发给我"))
            await eventually(entered.is_set)
            await nap.emit(message("/cancel"))
            await eventually(
                lambda: bool(bridge.store.latest(Context(777, 11))["cancel_requested"])
            )
        finally:
            release.set()
        await eventually(lambda: bridge.store.latest(Context(777, 11))["status"] == "cancelled")
        assert nap.media_sent == []
        assert not any(action["action"] == "upload_file_stream" for action in nap.actions)


async def test_cancel_during_text_typing_delay_blocks_the_unsent_result(harness, monkeypatch):
    async with harness() as (bridge, nap, op):
        entered = asyncio.Event()

        def delay(text):
            if text == "延迟中的结果":
                entered.set()
                return 0.2
            return 0.001

        monkeypatch.setattr(bridge.output, "text_delay", delay)
        op.reply_factory = lambda sid, body: "延迟中的结果"
        await nap.emit(message("处理任务"))
        await asyncio.wait_for(entered.wait(), 3)
        job = bridge.store.latest(Context(777, 11))
        assert bridge.store.next_outbox(777)["status"] == "ready"
        assert nap.sent == []
        await nap.emit(message("/cancel"))
        await eventually(lambda: bridge.store.job(job["id"])["status"] == "cancelled")
        await eventually(lambda: any("已请求取消" in text for text in nap.texts()))
        assert "延迟中的结果" not in nap.texts()
        assert nap.pokes == []


async def test_restart_during_text_typing_delay_preserves_the_unsent_result(harness, monkeypatch):
    async with harness() as (bridge, nap, op):
        entered = asyncio.Event()

        def delay(text):
            entered.set()
            return 10

        monkeypatch.setattr(bridge.output, "text_delay", delay)
        op.reply_factory = lambda sid, body: "重启后只发送一次"
        await nap.emit(message("处理任务"))
        await asyncio.wait_for(entered.wait(), 3)
        job = bridge.store.latest(Context(777, 11))
        assert bridge.store.next_outbox(777)["status"] == "ready"
        bridge.task.cancel()
        await asyncio.gather(bridge.task, return_exceptions=True)
        await bridge.onebot.disconnect()
        bridge.store.close()
        store = Store(bridge.config.state_db)
        restored = Bridge(bridge.config, store, bridge.onebot, bridge.opencode)
        task = asyncio.create_task(restored.run())
        try:
            await eventually(lambda: store.job(job["id"])["status"] == "done")
            assert nap.texts() == ["重启后只发送一次"]
            assert len(op.prompts) == 1
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await bridge.onebot.disconnect()
            store.close()


async def test_failed_execution_never_delivers_its_partial_files(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "failed"
        model_deliveries(bridge, op, [("report.txt", b"partial")])
        await nap.emit(message("编辑后发给我"))
        await eventually(lambda: bool(nap.sent))
        assert nap.media_sent == []
        assert not any(action["action"] == "upload_file_stream" for action in nap.actions)


@pytest.mark.parametrize("fault", ["missing", "stale", "outside", "symlink"])
async def test_invalid_manifest_never_sends_internal_protocol_or_files(harness, fault):
    async with harness() as (bridge, nap, op):

        def invalid(job_id, files, root):
            if fault == "missing":
                files[0]["path"] = "missing.txt"
            elif fault == "stale":
                files[0]["path"] = str(root.parent / "previous-job" / "report.txt")
            elif fault == "outside":
                files[0]["path"] = str(root.parent / "another-job" / "private.txt")
            else:
                (root / "alias.txt").symlink_to(root / "report.txt")
                files[0]["path"] = "alias.txt"
            return files

        model_deliveries(bridge, op, [("report.txt", b"edited")], invalid)
        await nap.emit(message("编辑后发给我"))
        await eventually(lambda: any("没能准备好" in value for value in nap.texts()))
        assert nap.media_sent == []
        assert not any("<qq-delivery" in value or "处理完成" in value for value in nap.texts())


def test_snapshot_freezes_content_and_ignores_requested_type_or_recipient(tmp_path):
    cfg = config(tmp_path)
    prepare_directory(cfg, "job")
    source = directory(cfg, "job") / "fake.png"
    source.write_bytes(b"plain text")
    text, media = snapshot_reply(
        receipt("job", [{"path": "fake.png", "kind": "image", "user_id": 12}]), cfg, "job"
    )
    source.write_bytes(b"changed later")
    assert text == "处理完成"
    assert media[0]["kind"] == "file"
    assert read_snapshot(media[0], cfg, "job") == b"plain text"
    Path(media[0]["path"]).write_bytes(b"tampered")
    with pytest.raises(DeliveryError, match="发生变化"):
        read_snapshot(media[0], cfg, "job")


def test_current_input_attachment_can_be_returned_after_editing(tmp_path):
    cfg = config(tmp_path)
    root = cfg.workdir.resolve() / ".qq-attachments" / "job"
    root.mkdir(parents=True)
    file = root / "received.docx"
    file.write_bytes(b"edited document")
    _, media = snapshot_reply(
        receipt("job", [{"path": str(file), "name": "修改后的文档.docx"}]), cfg, "job"
    )
    assert read_snapshot(media[0], cfg, "job") == b"edited document"
    assert media[0]["name"] == "修改后的文档.docx"
    with pytest.raises(DeliveryError):
        snapshot_reply(receipt("other-job", [{"path": str(file)}]), cfg, "other-job")


@pytest.mark.parametrize("with_empty_manifest", [False, True])
@pytest.mark.parametrize("fault", ["empty", "size", "count", "bad-json", "duplicate", "stale"])
def test_invalid_or_oversized_delivery_is_rejected_as_a_batch(tmp_path, fault, with_empty_manifest):
    cfg = config(tmp_path, max_attachment_bytes=4, max_attachments=1)
    prepare_directory(cfg, "job")
    root = directory(cfg, "job")
    (root / "result.txt").write_bytes(
        b"" if fault == "empty" else b"12345" if fault == "size" else b"OK"
    )
    body = receipt("job", [{"path": "result.txt"}])
    if fault == "count":
        body = receipt("job", [{"path": "result.txt"}, {"path": "second.txt"}])
    elif fault == "bad-json":
        body = marker("job") + "\ninvalid\n</qq-delivery>"
    elif fault == "duplicate":
        body += "\n" + body
    elif fault == "stale":
        body = receipt("previous-job", [{"path": "result.txt"}])
    if with_empty_manifest:
        body = receipt("previous-job", [], caption="") + "\n" + body
    with pytest.raises(DeliveryError):
        snapshot_reply(body, cfg, "job")


@pytest.mark.parametrize("state", ["uploading", "sending", "failed"])
def test_restart_retries_only_cache_uploads_and_blocks_unconfirmed_success(tmp_path, state):
    cfg = config(tmp_path)
    context = Context(777, 11)
    store = Store(cfg.state_db)
    job_id = store.enqueue(context, "回传", [])
    store.transition_job(job_id, "preparing")
    store.transition_job(job_id, "submitting")
    store.transition_job(job_id, "running")
    prepare_directory(cfg, job_id)
    (directory(cfg, job_id) / "report.txt").write_bytes(b"edited")
    _, artifacts = snapshot_reply(receipt(job_id, [{"path": "report.txt"}]), cfg, job_id)
    store.complete(job_id, context, "确认发送成功", 1800, artifacts=artifacts)
    item = store.next_outbox(777)
    assert item["kind"] == "file"
    store.update_outbox(item["id"], state)
    store.close()
    restored = Store(cfg.state_db)
    try:
        if state == "uploading":
            assert restored.next_outbox(777)["kind"] == "file"
            assert restored.next_outbox(777)["status"] == "ready"
            assert restored.failed_media() == []
        else:
            assert restored.next_outbox(777) is None
            assert restored.job(job_id)["status"] == (
                "send_uncertain" if state == "sending" else "send_failed"
            )
            assert len(restored.failed_media()) == 1
    finally:
        restored.close()


def test_legacy_text_outbox_migrates_without_losing_messages(tmp_path):
    path = tmp_path / "old.sqlite"
    context = Context(777, 11)
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE outbox (
            id INTEGER PRIMARY KEY, dedupe_key TEXT NOT NULL UNIQUE, job_id TEXT,
            target TEXT NOT NULL, text TEXT NOT NULL, first_chunk INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'ready', message_id TEXT, created REAL NOT NULL)""")
        db.execute(
            "INSERT INTO outbox (dedupe_key,target,text,first_chunk,created) VALUES (?,?,?,1,1)",
            ("old", json.dumps(context.to_dict()), "保留原回复"),
        )
    store = Store(path)
    try:
        item = store.next_outbox(777)
        assert item["text"] == "保留原回复"
        assert item["kind"] == "text"
        assert json.loads(item["payload"]) == {}
    finally:
        store.close()


@pytest.mark.parametrize(
    "openings",
    [
        [marker("job")],
        [marker("previous-job")],
        ["<qq-delivery>"],
        [marker("job"), marker("previous-job")],
    ],
)
def test_empty_manifest_is_treated_as_plain_text(tmp_path, openings):
    """空文件列表不该拦住整条回复，剥掉标记后当普通文字发送。"""
    cfg = config(tmp_path)
    body = "正常的一段话\n" + "\n".join(
        opening + '\n{"files": []}\n</qq-delivery>' for opening in openings
    )
    text, media = snapshot_reply(body, cfg, "job")
    assert text == "正常的一段话"
    assert media == []
    assert "<qq-delivery" not in text
    assert not cfg.workdir.exists()
    assert not (cfg.state_db.parent / ".qq-outbound").exists()


def test_empty_manifests_do_not_block_valid_file_delivery(tmp_path):
    cfg = config(tmp_path)
    prepare_directory(cfg, "job")
    (directory(cfg, "job") / "result.txt").write_bytes(b"result")
    body = "\n".join(
        [
            receipt("previous-job", [], caption=""),
            receipt("job", [{"path": "result.txt"}]),
            receipt("job", [], caption=""),
        ]
    )
    text, media = snapshot_reply(body, cfg, "job")
    assert text == "处理完成"
    assert len(media) == 1
    assert read_snapshot(media[0], cfg, "job") == b"result"


@pytest.mark.parametrize("manifest", [{}, {"files": None}, {"files": {}}, {"files": "[]"}, []])
def test_only_explicit_empty_file_lists_are_ignored(tmp_path, manifest):
    cfg = config(tmp_path)
    body = marker("job") + "\n" + json.dumps(manifest) + "\n</qq-delivery>"
    with pytest.raises(DeliveryError, match="回传文件数量无效或超限"):
        snapshot_reply(body, cfg, "job")


async def test_stale_empty_manifest_preserves_the_delivered_reply(harness):
    async with harness() as (bridge, nap, op):
        caption = "这是本轮的正常回复。"
        op.reply_factory = lambda sid, body: receipt("previous-job", [], caption=caption)
        await nap.emit(message("普通聊天"))
        await eventually(
            lambda: (job := bridge.store.latest(Context(777, 11))) and job["status"] == "done"
        )
        job = bridge.store.latest(Context(777, 11))
        assert job["error"] is None
        assert job["result"] == caption
        assert nap.texts() == [caption]
        assert nap.media_sent == []
        assert not any(action["action"] == "upload_file_stream" for action in nap.actions)
