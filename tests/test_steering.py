import asyncio
import threading

import pytest
from conftest import eventually, message

from qqbot import delivery_tools
from qqbot.bridge import Bridge
from qqbot.delivery import directory
from qqbot.models import Context
from qqbot.store import Store


async def test_private_steers_share_execution_progress_and_one_delivery(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("先查看文档"))
        await eventually(lambda: len(op.prompts) == 1)
        root = bridge.store.latest(Context(777, 11))
        sid = root["session_id"]
        op.messages[sid].append(
            {
                "id": "msg_progress",
                "type": "assistant",
                "finish": "stop",
                "content": [{"type": "text", "text": "正在查看"}],
            }
        )
        await eventually(lambda: "正在查看" in nap.texts())
        supplement = message("保留原来的接口", mid=1001)
        await nap.emit(supplement)
        await nap.emit(supplement)
        await nap.emit(message("也检查一下测试"))
        await eventually(lambda: len(op.prompts) == 3)
        assert [p["delivery"] for p in op.prompts] == ["steer"] * 3
        assert {p["sessionID"] for p in op.prompts} == {sid}
        assert len({p["id"] for p in op.prompts}) == 3
        assert op.sessions[sid]["metadata"]["qq_bridge_job_id"] == root["id"]
        assert op.interrupted == []
        assert len(bridge.store.conversation_jobs(Context(777, 11))) == 1
        op.finish(sid, "检查完成，已保留接口。")
        await eventually(lambda: bridge.store.job(root["id"])["status"] == "done")
        assert nap.texts().count("正在查看") == 1
        assert nap.texts().count("检查完成，已保留接口。") == 1
        assert [job["status"] for job in bridge.store.steers(root["id"])] == ["done", "done"]
        assert (
            bridge.store.db.execute("SELECT COUNT(*) FROM outbox WHERE kind='poke'").fetchone()[0]
            == 1
        )


async def test_groups_still_queue_and_other_private_chats_cannot_steer(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("群里的长任务", group=22, at=True))
        await eventually(lambda: len(op.prompts) == 1)
        root = bridge.store.latest(Context(777, 11, 22))
        await nap.emit(message("群里的下一件事", group=22, at=True))
        await nap.emit(message("其他私聊的第一条", user=12))
        await nap.emit(message("其他私聊的第二条", user=12))
        await eventually(lambda: len(bridge.store.conversation_jobs(Context(777, 12))) == 2)
        assert len(op.prompts) == 1 and op.prompts[0]["delivery"] == "queue"
        assert bridge.store.steers(root["id"]) == []
        assert len(bridge.store.conversation_jobs(Context(777, 11, 22))) == 2
        await eventually(lambda: any("排好队" in text for text in nap.texts()))
        op.mode = "normal"
        op.finish(root["session_id"])
        await eventually(lambda: len(op.prompts) == 4)
        assert [p["delivery"] for p in op.prompts] == ["queue", "queue", "steer", "steer"]


async def test_steer_in_inbox_prevents_completion_at_the_previous_idle(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        op.defer_steers = True
        await nap.emit(message("原任务"))
        await eventually(lambda: len(op.prompts) == 1)
        root = bridge.store.latest(Context(777, 11))
        sid = root["session_id"]
        await nap.emit(message("新补充"))
        await eventually(lambda: len(op.prompts) == 2)
        op.finish(sid, "原回复")
        await asyncio.sleep(0.1)
        assert bridge.store.job(root["id"])["status"] == "running"
        assert (
            bridge.store.db.execute("SELECT COUNT(*) FROM outbox WHERE kind='poke'").fetchone()[0]
            == 0
        )
        op.deliver_steers(sid)
        op.finish(sid, "结合补充后的回复")
        await eventually(lambda: bridge.store.job(root["id"])["status"] == "done")
        assert nap.texts().count("结合补充后的回复") == 1


async def test_steer_lost_admission_and_restart_keep_ids_and_frozen_text(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("原任务"))
        await eventually(lambda: len(op.prompts) == 1)
        root = bridge.store.latest(Context(777, 11))
        op.lose_prompt_response = True
        await nap.emit(message("断线时补充的要求"))
        await eventually(lambda: len(op.prompts) == 2)
        child = bridge.store.steers(root["id"])[0]
        assert child["submitted_text"] == "断线时补充的要求"
        bridge.task.cancel()
        await asyncio.gather(bridge.task, return_exceptions=True)
        await bridge.onebot.disconnect()
        bridge.store.close()
        store = Store(bridge.config.state_db)
        restored = Bridge(bridge.config, store, bridge.onebot, bridge.opencode)
        task = asyncio.create_task(restored.run())
        try:
            await eventually(lambda: store.job(child["id"])["status"] == "steered")
            assert len(op.prompts) == 2
            assert op.prompts[1]["id"] == child["prompt_id"]
            assert store.job(child["id"])["submitted_text"] == child["submitted_text"]
            op.finish(root["session_id"], "重启后一起处理完成")
            await eventually(lambda: store.job(root["id"])["status"] == "done")
            assert nap.texts().count("重启后一起处理完成") == 1
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await bridge.onebot.disconnect()
            store.close()


async def test_steer_arriving_during_attachment_preparation_is_not_lost(harness, monkeypatch):
    started, release = threading.Event(), threading.Event()
    original = delivery_tools.snapshot_files

    def snapshot(*args, **kwargs):
        if not started.is_set():
            started.set()
            assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(delivery_tools, "snapshot_files", snapshot)
    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("原任务"))
        await eventually(lambda: len(op.prompts) == 1)
        root = bridge.store.latest(Context(777, 11))
        (directory(bridge.config, root["id"]) / "report.txt").write_bytes(b"report")
        pending = asyncio.create_task(
            bridge.delivery_tools.submit(
                root["session_id"], "preparing", {"files": [{"path": "report.txt"}]}
            )
        )
        try:
            await eventually(started.is_set)
            await nap.emit(message("最后补充的要求"))
            await eventually(lambda: bool(bridge.store.steers(root["id"])))
        finally:
            release.set()
        assert (await pending)["status"] == "queued"
        await eventually(lambda: len(op.prompts) == 2)
        op.finish(root["session_id"], "回复：最后补充的要求")
        await eventually(lambda: bridge.store.job(root["id"])["status"] == "done")
        assert len(op.prompts) == 2
        assert op.prompts[-1]["text"] == "最后补充的要求"
        assert nap.texts().count("回复：最后补充的要求") == 1
        assert len(nap.media_sent) == 1


async def test_cancel_clears_admitted_steers_that_are_still_in_the_inbox(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        op.defer_steers = True
        await nap.emit(message("原任务"))
        await eventually(lambda: len(op.prompts) == 1)
        root = bridge.store.latest(Context(777, 11))
        await nap.emit(message("补充"))
        await eventually(lambda: len(op.prompts) == 2)
        assert op.inboxes[root["session_id"]]
        await nap.emit(message("/cancel"))
        await eventually(lambda: bridge.store.job(root["id"])["status"] == "cancelled")
        assert op.inboxes[root["session_id"]] == []
        assert bridge.store.steers(root["id"])[0]["status"] == "cancelled"


async def test_pending_steers_respect_the_existing_queue_limit(harness, monkeypatch):
    async with harness(max_queued_per_context=2) as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("原任务"))
        await eventually(lambda: len(op.prompts) == 1)
        root = bridge.store.latest(Context(777, 11))
        release = asyncio.Event()

        async def pause_submission(job_id):
            await release.wait()

        monkeypatch.setattr(bridge.runner, "submit_steers", pause_submission)
        await nap.emit(message("第一条补充"))
        await nap.emit(message("超限的补充"))
        await eventually(lambda: any("这条还没排进去" in text for text in nap.texts()))
        assert len(bridge.store.steers(root["id"])) == 1
        assert len(op.prompts) == 1


async def test_quoted_steer_attachment_and_failed_attachment_do_not_abort_parent(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("原任务"))
        await eventually(lambda: len(op.prompts) == 1)
        root = bridge.store.latest(Context(777, 11))
        nap.files["extra"] = b"extra context"
        await nap.emit(
            message(
                mid=2001,
                attachments=[{"type": "file", "data": {"file_id": "extra", "name": "extra.txt"}}],
            )
        )
        await nap.emit(message("加上这个文件", reply=2001))
        await eventually(lambda: len(op.prompts) == 2)
        assert op.prompts[-1]["files"][0]["name"].endswith("extra.txt")
        assert op.prompts[-1]["text"] == "加上这个文件"
        assert op.prompts[-1]["delivery"] == "steer"
        nap.stream_fault = "order"
        await nap.emit(
            message("坏附件", attachments=[{"type": "image", "data": {"file": "extra"}}])
        )
        await eventually(
            lambda: any(job["status"] == "failed" for job in bridge.store.steers(root["id"]))
        )
        assert bridge.store.job(root["id"])["status"] == "running"
        assert op.interrupted == [] and len(op.prompts) == 2
        op.finish(root["session_id"])
        await eventually(lambda: bridge.store.job(root["id"])["status"] == "done")


@pytest.mark.parametrize("other_context", [Context(777, 12), Context(777, 11, 22)])
def test_store_rejects_steering_from_another_context(tmp_path, other_context):
    store = Store(tmp_path / "state.sqlite")
    try:
        parent = store.enqueue(Context(777, 11), "原任务", [])
        for status in ("preparing", "submitting", "running"):
            store.transition_job(parent, status)
        with pytest.raises(ValueError, match="同一私聊"):
            store.enqueue(other_context, "不能插入", [], steer_parent_id=parent)
        assert store.steers(parent) == []
    finally:
        store.close()
