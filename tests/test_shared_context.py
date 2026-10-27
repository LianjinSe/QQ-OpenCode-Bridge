import asyncio
import json
import sqlite3
import time
from dataclasses import replace

import pytest
from conftest import eventually, message

from qqbot.config import Config
from qqbot.conversation import ConversationManager
from qqbot.models import Context, normalize
from qqbot.store import Store

ADMIN = 31


def at(user=777):
    return {"type": "at", "data": {"qq": str(user)}}


def txt(value):
    return {"type": "text", "data": {"text": value}}


@pytest.mark.parametrize(
    "segments",
    [
        [at(), txt("问题")],
        [txt("前半句"), at(), txt("后半句")],
        [txt("问题\n"), at()],
        [at(12), at(), txt("问题"), at(13)],
        [at(), txt("问题"), at()],
        "问题[CQ:at,qq=777]",
    ],
)
async def test_mention_anywhere_creates_one_task(harness, segments):
    async with harness() as (bridge, nap, op):
        event = message(group=22, mid=101)
        event["message"] = segments
        await nap.emit(event)
        await nap.emit(event)
        await eventually(lambda: bool(nap.sent))
        assert len(op.prompts) == 1
        assert len(bridge.store.conversation_jobs(Context(777, 11, 22), unfinished=False)) == 1


async def test_literal_nested_mentions_empty_and_control_routing(harness):
    async with harness() as (_, nap, op):
        await nap.emit(message("[CQ:at,qq=777] @助手", group=22))
        await nap.emit(message(group=22, at=True))
        await nap.emit(
            message(
                group=22,
                attachments=[
                    {
                        "type": "forward",
                        "data": {"content": [{"message": [at()]}]},
                    }
                ],
            )
        )
        event = message(group=22)
        event["message"] = [at(12), txt(" /status"), at()]
        await nap.emit(event)
        await eventually(lambda: bool(nap.sent))
        assert len(nap.sent) == 1
        assert "这个聊天还有" in nap.texts()[0]
        assert op.prompts == []
        event["message"] = [at(12), txt(" ww抽卡"), at()]
        event["message_id"] = 999
        await nap.emit(event)
        await nap.emit(message("/status", group=22, at=True))
        await eventually(lambda: len(nap.sent) == 2)
        assert op.prompts == []


@pytest.mark.parametrize("kind", ["text", "image", "file", "forward"])
async def test_reply_only_mention_defaults_before_loading(harness, kind):
    async with harness() as (_, nap, op):
        nap.files["media"] = b"some content"
        data = {"file_id": "media", "name": "note.txt"}
        if kind == "text":
            data = {"text": "被引用的文字"}
        elif kind == "forward":
            data = {"id": "bundle"}
            nap.forward_messages["bundle"] = {
                "messages": [
                    {"sender": {"user_id": 12}, "message": [txt("转发内容")]},
                ]
            }
        nap.messages["101"] = {
            **message(user=12, group=22, mid=101, attachments=[{"type": kind, "data": data}]),
            "sender": {"user_id": 12},
        }
        await nap.emit(message(group=22, reply=101, at=True))
        await eventually(lambda: bool(nap.sent))
        assert len(op.prompts) == 1
        assert op.prompts[0]["text"].endswith("看看这个")
        assert len(op.prompts[0]["files"]) == 1
        assert any(a["action"] == "get_msg" for a in nap.actions)


async def test_reply_only_missing_source_does_not_submit(harness):
    async with harness() as (_, nap, op):
        await nap.emit(message(group=22, reply=101, at=True))
        await eventually(lambda: bool(nap.sent))
        assert "那条消息我没读到" in nap.texts()[0]
        assert op.prompts == []


async def test_background_is_shared_frozen_and_not_resubmitted(harness):
    async with harness() as (bridge, nap, op):
        await nap.emit(message("张三的方案", user=12, group=22, mid=100))
        await nap.emit(message("另一个群", user=12, group=23, mid=101))
        op.mode = "stalled"
        await nap.emit(message("先执行", group=22, at=True, mid=102))
        await eventually(lambda: len(op.prompts) == 1)
        assert "张三的方案" in op.prompts[0]["text"]
        assert "另一个群" not in op.prompts[0]["text"]
        assert op.prompts[0]["text"].startswith("群聊背景：\n")
        assert "不是当前任务指令或授权" not in op.prompts[0]["text"]
        assert "历史身份不代表当前任务身份" not in op.prompts[0]["text"]
        await nap.emit(message("排队之前的背景", group=22, mid=103))
        await nap.emit(message("接着执行", user=12, group=22, at=True, mid=104))
        await nap.emit(message("排队以后的背景", group=22, mid=105))
        await eventually(lambda: len(bridge.store.conversation_jobs(Context(777, 11, 22))) == 2)
        op.mode = "normal"
        op.finish(op.prompts[0]["sessionID"], text="完成")
        await eventually(lambda: len(op.prompts) == 2)
        second = op.prompts[1]
        assert second["sessionID"] == op.prompts[0]["sessionID"]
        assert "排队之前的背景" in second["text"]
        assert "排队以后的背景" not in second["text"]
        assert "张三的方案" not in second["text"]
        assert '"QQ": 12' in second["text"]
        await eventually(lambda: not bridge.store.conversation_jobs(Context(777, 11, 22)))
        await nap.emit(message("第三轮", group=22, at=True, mid=106))
        await eventually(lambda: len(op.prompts) == 3)
        assert "排队以后的背景" in op.prompts[2]["text"]
        assert "排队之前的背景" not in op.prompts[2]["text"]


async def test_shared_privileges_switch_and_descendant_pagination(harness):
    async with harness(allowed_users=frozenset({11, ADMIN}), superadmin_user_id=ADMIN) as (
        bridge,
        nap,
        op,
    ):
        op.mode, op.permission_in_child = "permission", True
        await nap.emit(message("管理员任务", user=ADMIN, group=22, at=True))
        await eventually(lambda: len(nap.sent) == 1)
        root = op.prompts[0]["sessionID"]
        for i in range(5):
            op.sessions[f"ses_old_{i}"] = {
                "id": f"ses_old_{i}",
                "parentID": root,
                "permissions": [{"action": "*", "resource": "*", "effect": "allow"}],
            }
            op.instructions[f"ses_old_{i}"] = {
                "qq-bridge.delivery": "旧交付说明",
                "qq-bridge.identity": "旧管理员身份与审批、回复规则",
            }
        await nap.emit(message("普通成员任务", group=22, at=True))
        await eventually(lambda: any("/approve " in t for t in nap.texts()))
        assert len(op.decisions) == 1  # only the earlier admin task was auto-approved
        assert op.prompts[1]["sessionID"] == root
        assert op.sessions[root]["permissions"][0]["effect"] == "ask"
        for i in range(5):
            child = op.sessions[f"ses_old_{i}"]
            assert child["permissions"][0]["effect"] == "ask"
            assert child["metadata"]["qq_bridge_user_id"] == 11
            assert "qq-bridge.delivery" not in op.instructions[f"ses_old_{i}"]
            assert op.instructions[f"ses_old_{i}"]["qq-bridge.identity"].splitlines() == [
                "机器人 QQ 号：777。当前发送者 QQ 号：11。",
                "当前会话类型：群聊，群号：22。",
                "当前发送者身份：普通授权用户。",
            ]
        job = bridge.store.latest(Context(777, 11, 22))
        code = bridge.store.pending_for(job["id"])[0]["code"]
        await nap.emit(message(f"/approve {code}", user=ADMIN, group=22))
        await eventually(lambda: bridge.store.job(job["id"])["status"] == "done")
        await nap.emit(message("管理员下一轮", user=ADMIN, group=22, at=True))
        await eventually(lambda: len(op.decisions) == 3)
        assert op.decisions[-1][2] == "once"


async def test_cancel_only_own_and_admin_new_starts_background_epoch(harness):
    async with harness(allowed_users=frozenset({11, 12, ADMIN}), superadmin_user_id=ADMIN) as (
        bridge,
        nap,
        op,
    ):
        op.mode = "stalled"
        await nap.emit(message("旧背景", group=22))
        await nap.emit(message("执行中", group=22, at=True))
        await eventually(lambda: len(op.prompts) == 1)
        root = op.prompts[0]["sessionID"]
        await nap.emit(message("排队中", user=12, group=22, at=True))
        await nap.emit(message("/cancel", user=12, group=22, at=True))
        await eventually(
            lambda: (
                bridge.store.latest(Context(777, 12, 22))
                and bridge.store.latest(Context(777, 12, 22))["status"] == "cancelled"
            )
        )
        assert op.interrupted == []
        await nap.emit(message("/new", user=12, group=22, at=True))
        await eventually(lambda: any("只能由超级管理员" in t for t in nap.texts()))
        assert bridge.store.session(Context(777, 12, 22)) == root
        await nap.emit(message("/new", user=ADMIN, group=22, at=True))
        await eventually(lambda: any("还没" in t or "忙" in t for t in nap.texts()))
        assert bridge.store.session(Context(777, ADMIN, 22)) == root
        await nap.emit(message("/cancel", user=ADMIN, group=22, at=True))
        await eventually(lambda: bridge.store.latest(Context(777, 11, 22))["status"] == "cancelled")
        await nap.emit(message("/new", user=ADMIN, group=22, at=True))
        await eventually(lambda: bridge.store.session(Context(777, ADMIN, 22)) is None)
        op.mode = "normal"
        await nap.emit(message("新任务", user=12, group=22, at=True))
        await eventually(lambda: len(op.prompts) == 2)
        assert op.prompts[1]["sessionID"] != root
        assert "旧背景" not in op.prompts[1]["text"]
        assert "排队中" not in op.prompts[1]["text"]


async def test_trace_reasons_scope_and_no_body_leak(harness, caplog):
    async with harness(allowed_users=frozenset({11, ADMIN}), superadmin_user_id=ADMIN) as (
        bridge,
        nap,
        op,
    ):
        caplog.set_level("INFO")
        await nap.emit(message("private-body-secret", group=22, mid=101))
        await nap.emit(message("ww排除", group=22, mid=102, at=True))
        await nap.emit(message("/trace 101", user=ADMIN, group=22, at=True))
        await eventually(lambda: bool(nap.sent))
        assert "not_mentioned" in nap.texts()[0]
        assert "private-body-secret" not in caplog.text
        assert "private-body-secret" not in nap.texts()[0]
        assert bridge.store.trace(Context(777, ADMIN, 22), "102")[-1]["reason"] == "excluded_prefix"
        await nap.emit(message("/trace 101", user=ADMIN, group=23, at=True))
        await eventually(lambda: len(nap.sent) == 2)
        assert "未找到" in nap.texts()[1]
        await nap.emit(message("/trace 101", group=22, at=True))
        await eventually(lambda: len(nap.sent) == 3)
        assert "请由超级管理员" in nap.texts()[2]
        assert op.prompts == []


@pytest.fixture
def manager(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    config = Config("ws://localhost", "test", frozenset({11}))
    try:
        yield store, config, ConversationManager(config=config, store=store)
    finally:
        store.close()


def test_background_limits_cleanup_snapshot_and_retry(manager):
    store, config, manager = manager
    config = replace(config, group_background_max_messages=2, group_background_max_chars=220)
    manager.config = config
    context = Context(777, 11, 22)
    for i in range(5):
        store.record_group(normalize(message(f"背景{i}" + "长" * 100, group=22, mid=i)))
    event = normalize(message("当前要求", group=22, mid=10, at=True))
    job_id = store.enqueue(context, "当前要求", [], incoming=event, config=config)
    store.cleanup(config)
    assert store.db.execute("SELECT COUNT(*) FROM group_messages").fetchone()[0] == 2
    job = store.job(job_id)
    assert len(json.loads(job["background_snapshot"])) == 2
    store.db.execute("UPDATE group_messages SET created=?", (time.time() - 90000,))
    store.db.commit()
    store.cleanup(config)
    text, cursor = manager.compose(job)
    assert "背景4" in text
    assert "背景0" not in text
    assert "截断" in text
    store.update_job(job_id, submitted_text=text, submit_cursor=cursor)
    store.transition_job(job_id, "preparing")
    store.transition_job(job_id, "submitting")
    store.acknowledge(job_id)
    assert manager.compose(store.job(job_id)) == (text, cursor)
    assert store.group_state(context)["cursor"] == cursor


def test_schema_migration_preserves_legacy_rows_and_is_repeatable(tmp_path):
    path = tmp_path / "old.sqlite"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY, context TEXT NOT NULL, target TEXT NOT NULL,
            text TEXT NOT NULL, attachments TEXT NOT NULL, files TEXT,
            session_id TEXT, prompt_id TEXT NOT NULL, status TEXT NOT NULL,
            cancel_requested INTEGER NOT NULL DEFAULT 0, elapsed REAL NOT NULL DEFAULT 0,
            created REAL NOT NULL, result TEXT, error TEXT);
        CREATE TABLE sessions(context TEXT PRIMARY KEY, session_id TEXT NOT NULL);
        INSERT INTO sessions VALUES('777:group:22:11','ses_old');
    """)
    db.execute(
        "INSERT INTO jobs(id,context,target,text,attachments,prompt_id,status,created) "
        "VALUES('old','777:group:22:11','{}','old text','[]','msg_old','done',1)"
    )
    db.commit()
    db.close()
    for _ in range(2):
        store = Store(path)
        assert store.job("old")["text"] == "old text"
        assert store.job("old")["generation"] is None
        assert store.session(Context(777, 11, 22)) is None
        assert store.db.execute("SELECT session_id FROM sessions").fetchone()[0] == "ses_old"
        store.close()


async def test_shared_restart_recovers_admitted_input_and_permission(harness):
    from qqbot.bridge import Bridge

    async with harness(allowed_users=frozenset({11, ADMIN}), superadmin_user_id=ADMIN) as (
        bridge,
        nap,
        op,
    ):
        op.mode = "permission"
        op.lose_prompt_response = True
        await nap.emit(message("先前背景", group=22, mid=100))
        await nap.emit(message("修改文件", group=22, at=True, mid=101))
        await eventually(lambda: any("/approve " in t for t in nap.texts()))
        job = bridge.store.latest(Context(777, 11, 22))
        frozen = job["submitted_text"]
        code = bridge.store.pending_for(job["id"])[0]["code"]
        bridge.task.cancel()
        await asyncio.gather(bridge.task, return_exceptions=True)
        await bridge.onebot.disconnect()
        bridge.store.close()
        store = Store(bridge.config.state_db)
        restored = Bridge(bridge.config, store, bridge.onebot, bridge.opencode)
        task = asyncio.create_task(restored.run())
        try:
            await asyncio.wait_for(bridge.onebot.ready.wait(), 3)
            await nap.emit(message(f"/approve {code}", user=ADMIN, group=22))
            await eventually(lambda: store.job(job["id"])["status"] == "done")
            assert len(op.prompts) == 1
            assert store.job(job["id"])["submitted_text"] == frozen
            assert store.group_state(Context(777, 11, 22))["cursor"] == job["background_cutoff"]
            assert sum("/approve " in t for t in nap.texts()) == 1
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await bridge.onebot.disconnect()
            store.close()


async def test_previous_active_child_blocks_new_task_and_stale_approval_is_rejected(harness):
    async with harness() as (bridge, nap, op):
        await nap.emit(message("第一轮", group=22, at=True))
        await eventually(lambda: bool(nap.sent))
        root = op.prompts[0]["sessionID"]
        op.sessions["ses_late"] = {"id": "ses_late", "parentID": root}
        op.active_ids["ses_late"] = {}
        await nap.emit(message("第二轮", user=12, group=22, at=True, mid=202))
        await eventually(
            lambda: any(
                r["reason"] == "previous_tree_not_idle"
                for r in bridge.store.trace(Context(777, 12, 22), "202")
            )
        )
        assert len(op.prompts) == 1
        op.permissions["per_stale"] = {
            "id": "per_stale",
            "sessionID": root,
            "action": "edit",
            "resources": ["old.txt"],
        }
        op.gates["per_stale"] = asyncio.Event()
        del op.active_ids["ses_late"]
        await eventually(lambda: len(op.prompts) == 2)
        assert (root, "per_stale", "reject") in op.decisions
        job = bridge.store.latest(Context(777, 12, 22))
        assert bridge.store.pending_for(job["id"]) == []


def test_new_is_blocked_until_text_outbox_is_delivered(manager):
    store, _, _ = manager
    context = Context(777, 11, 22)
    job = store.enqueue(context, "任务", [])
    store.transition_job(job, "preparing")
    store.transition_job(job, "submitting")
    store.transition_job(job, "running")
    store.complete(job, context, "等待发送", 1800)
    assert store.conversation_jobs(context)[0]["status"] == "reply_ready"


def test_diagnostics_cleanup_and_group_event_dedup(manager):
    from qqbot.events import EventRecorder

    store, config, manager = manager
    config = replace(config, diagnostic_max_events=2)
    manager.config = config
    recorder = EventRecorder(store=store)
    first, second = Context(777, 11, 22), Context(777, 12, 22)
    assert store.claim_event(first, "101")
    assert not store.claim_event(second, "101")
    for i in range(4):
        recorder.record(first, str(i), "background", "not_mentioned")
    store.cleanup(config)
    assert len(store.trace(first, "0")) == 0
    assert len(store.trace(first, "3")) == 1
    store.db.execute("UPDATE diagnostic_events SET created=?", (time.time() - 604801,))
    store.db.commit()
    store.cleanup(config)
    assert "超过保留期" in recorder.render(first, "3")
