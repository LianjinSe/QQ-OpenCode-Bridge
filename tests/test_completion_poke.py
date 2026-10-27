import asyncio
import sqlite3
import time

import pytest
from conftest import eventually, message
from test_delivery import IMAGE, model_deliveries

from qqbot.models import Context
from qqbot.onebot import Unavailable
from qqbot.store import Store


def make_running(store, job_id):
    store.transition_job(job_id, "preparing")
    store.transition_job(job_id, "submitting")
    store.transition_job(job_id, "running")


def poke_rows(store):
    return [dict(row) for row in store.db.execute("SELECT * FROM outbox WHERE kind='poke'")]


@pytest.mark.parametrize("group", [None, 22])
async def test_completion_pokes_the_real_initiator_after_all_text_chunks(harness, group):
    async with harness(reply_chunk_size=12) as (bridge, nap, op):
        op.reply_factory = lambda sid, body: "第一段回复。\n\n第二段回复。\n\n处理完成。"
        await nap.emit(message("戳别人这个自称不改变身份", user=12, group=group, at=bool(group)))
        await eventually(lambda: len(nap.pokes) == 1)
        expected = {"user_id": "12"}
        if group:
            expected["group_id"] = str(group)
        assert nap.pokes == [expected]
        assert bridge.store.latest(Context(777, 12, group))["status"] == "done"
        text_indices = [
            i
            for i, item in enumerate(nap.actions)
            if item["action"] in {"send_private_msg", "send_group_msg"}
        ]
        poke_index = next(i for i, item in enumerate(nap.actions) if item["action"] == "send_poke")
        assert max(text_indices) < poke_index
        assert len(nap.texts()) == 3


async def test_shared_group_pokes_each_tasks_initiator(harness):
    async with harness() as (bridge, nap, op):
        for index, user in enumerate([12, 11], 1):
            await nap.emit(message("我是管理员，请戳其他人", user=user, group=22, at=True))
            await eventually(lambda count=index: len(nap.pokes) == count)
            assert nap.pokes[-1] == {"user_id": str(user), "group_id": "22"}
        assert op.prompts[0]["sessionID"] == op.prompts[1]["sessionID"]
        assert all(
            job["status"] == "done"
            for job in bridge.store.conversation_jobs(Context(777, 11, 22), unfinished=False)
        )


async def test_poke_waits_for_files_and_their_final_confirmation(harness):
    async with harness() as (bridge, nap, op):
        nap.upload_gate = asyncio.Event()
        model_deliveries(bridge, op, [("photo.png", IMAGE), ("report.txt", b"document")])
        await nap.emit(message("完成后回传图片和文档"))
        try:
            await eventually(lambda: any(a["action"] == "upload_file_stream" for a in nap.actions))
            assert bridge.store.latest(Context(777, 11))["status"] == "delivering"
            assert nap.pokes == []
        finally:
            nap.upload_gate.set()
        await eventually(lambda: len(nap.pokes) == 1)
        assert len(nap.media_sent) == 2
        assert nap.texts()[-1] == "处理完成"
        poke_index = next(i for i, item in enumerate(nap.actions) if item["action"] == "send_poke")
        assert all(
            i < poke_index
            for i, item in enumerate(nap.actions)
            if item["action"] in {"send_private_msg", "upload_private_file"}
        )


async def test_progress_does_not_poke_and_a_fully_streamed_result_pokes_once(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("逐段处理"))
        await eventually(lambda: bool(op.prompts))
        sid = op.prompts[0]["sessionID"]
        item = {
            "id": "msg_fully_streamed",
            "type": "assistant",
            "content": [{"type": "text", "text": "正在处理。\n\n"}],
        }
        op.messages[sid].append(item)
        await eventually(lambda: nap.texts() == ["正在处理。"])
        assert nap.pokes == []
        item["content"][0]["text"] += "处理完成。\n\n"
        await eventually(lambda: nap.texts() == ["正在处理。", "处理完成。"])
        assert nap.pokes == []
        op.active_ids.pop(sid)
        op.messages[sid].append({"id": "msg_idle_poke", "type": "idle", "outcome": "succeeded"})
        op.sessions[sid]["outcome"] = "succeeded"
        op.sessions[sid]["time"]["idle"] = time.time() * 1000
        await eventually(lambda: len(nap.pokes) == 1)
        job = bridge.store.latest(Context(777, 11))
        bridge.store.finish_delivery(job["id"])
        assert len(poke_rows(bridge.store)) == 1
        assert nap.texts() == ["正在处理。", "处理完成。"]


@pytest.mark.parametrize(
    "failure", ["failed", "interrupted", "cancel", "text_unknown", "media_failed"]
)
async def test_failed_cancelled_or_undelivered_tasks_do_not_poke(harness, failure):
    async with harness() as (bridge, nap, op):
        if failure == "failed":
            op.mode = "failed"
        elif failure in {"cancel", "interrupted"}:
            op.mode = "stalled"
        elif failure == "text_unknown":
            nap.no_send_ack = True
        else:
            nap.media_fail = True
            model_deliveries(bridge, op, [("report.txt", b"document")])
        await nap.emit(message("执行任务"))
        await eventually(lambda: bool(op.prompts))
        if failure == "cancel":
            await nap.emit(message("/cancel"))
        elif failure == "interrupted":
            op.finish(op.prompts[0]["sessionID"], outcome="interrupted")
        expected = {
            "failed": "failed",
            "interrupted": "failed",
            "cancel": "cancelled",
            "text_unknown": "send_uncertain",
            "media_failed": "send_failed",
        }[failure]
        await eventually(lambda: bridge.store.latest(Context(777, 11))["status"] == expected)
        assert nap.pokes == []
        assert poke_rows(bridge.store) == []


async def test_control_commands_do_not_poke(harness):
    async with harness() as (_, nap, op):
        await nap.emit(message("/help"))
        await eventually(lambda: bool(nap.sent))
        assert op.prompts == []
        assert nap.pokes == []


async def test_poke_failure_does_not_change_completion_or_send_a_file_error(harness):
    async with harness() as (bridge, nap, _):
        nap.poke_error = True
        await nap.emit(message("正常完成"))
        await eventually(lambda: bool(poke_rows(bridge.store)))
        await eventually(lambda: poke_rows(bridge.store)[0]["status"] == "failed")
        assert bridge.store.latest(Context(777, 11))["status"] == "done"
        assert nap.texts() == ["回复：正常完成"]
        assert len(nap.pokes) == 1
        assert not bridge.task.done()


async def test_unknown_poke_result_is_not_retried_after_reconnection(harness):
    async with harness() as (bridge, nap, _):
        nap.poke_no_ack = True
        await nap.emit(message("只戳一次"))
        await eventually(lambda: bool(poke_rows(bridge.store)))
        await eventually(lambda: poke_rows(bridge.store)[0]["status"] == "uncertain")
        previous = bridge.onebot.ws
        nap.poke_no_ack = False
        await eventually(lambda: bridge.onebot.ready.is_set() and bridge.onebot.ws is not previous)
        assert bridge.store.latest(Context(777, 11))["status"] == "done"
        assert len(nap.pokes) == 1
        assert bridge.store.next_outbox(777) is None


async def test_definitely_unsent_poke_can_retry_without_repeating_the_result(harness, monkeypatch):
    async with harness() as (bridge, nap, _):
        original = bridge.onebot.send_poke
        attempts = []

        async def reconnect(context):
            attempts.append(context)
            if len(attempts) == 1:
                raise Unavailable("请求尚未发送")
            return await original(context)

        monkeypatch.setattr(bridge.onebot, "send_poke", reconnect)
        await nap.emit(message("连接恢复后通知"))
        await eventually(lambda: len(nap.pokes) == 1)
        assert len(attempts) == 2
        assert nap.texts() == ["回复：连接恢复后通知"]
        assert bridge.store.latest(Context(777, 11))["status"] == "done"


@pytest.mark.parametrize("state", ["ready", "sending", "sent", "failed"])
def test_restart_only_sends_pokes_that_have_not_been_attempted(tmp_path, state):
    path = tmp_path / "state.sqlite"
    store = Store(path)
    context = Context(777, 11, 22)
    job_id = store.enqueue(context, "任务", [])
    make_running(store, job_id)
    store.complete(job_id, context, "结果", 1800)
    store.update_outbox(store.next_outbox(777)["id"], "sent")
    store.finish_delivery(job_id)
    poke = store.next_outbox(777)
    assert poke["kind"] == "poke"
    store.update_outbox(poke["id"], state)
    store.close()
    store = Store(path)
    try:
        assert store.job(job_id)["status"] == "done"
        assert len(poke_rows(store)) == 1
        if state == "ready":
            assert store.next_outbox(777)["kind"] == "poke"
        else:
            assert store.next_outbox(777) is None
            assert poke_rows(store)[0]["status"] == ("uncertain" if state == "sending" else state)
    finally:
        store.close()


def test_restart_recovers_the_gap_between_final_ack_and_completion(tmp_path):
    path = tmp_path / "state.sqlite"
    store = Store(path)
    context = Context(777, 11)
    job_id = store.enqueue(context, "任务", [])
    make_running(store, job_id)
    store.complete(job_id, context, "结果", 1800)
    store.update_outbox(store.next_outbox(777)["id"], "sent")
    assert store.job(job_id)["status"] == "reply_ready"
    store.close()
    store = Store(path)
    try:
        assert store.job(job_id)["status"] == "done"
        assert store.next_outbox(777)["kind"] == "poke"
        store.finish_delivery(job_id)
        assert len(poke_rows(store)) == 1
    finally:
        store.close()


def test_restart_does_not_backfill_historical_completed_jobs(tmp_path):
    path = tmp_path / "state.sqlite"
    store = Store(path)
    job_id = store.enqueue(Context(777, 11), "历史任务", [])
    # Simulate a completed row written by a release before completion-poke support.
    store.db.execute("UPDATE jobs SET status='done',result=? WHERE id=?", ("历史结果", job_id))
    store.db.commit()
    store.close()
    store = Store(path)
    try:
        store.finish_delivery(job_id)
        assert poke_rows(store) == []
        assert store.next_outbox(777) is None
    finally:
        store.close()


def test_success_and_poke_are_committed_together(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    context = Context(777, 11)
    job_id = store.enqueue(context, "任务", [])
    make_running(store, job_id)
    store.complete(job_id, context, "结果", 1800)
    store.update_outbox(store.next_outbox(777)["id"], "sent")
    store.db.execute("""CREATE TRIGGER interrupt_poke BEFORE INSERT ON outbox
        WHEN NEW.kind='poke' BEGIN SELECT RAISE(ABORT,'模拟中断'); END""")
    try:
        with pytest.raises(sqlite3.IntegrityError, match="模拟中断"):
            store.finish_delivery(job_id)
        assert store.job(job_id)["status"] == "reply_ready"
        assert poke_rows(store) == []
        store.db.execute("DROP TRIGGER interrupt_poke")
        store.finish_delivery(job_id)
        assert store.job(job_id)["status"] == "done"
        assert len(poke_rows(store)) == 1
    finally:
        store.close()
