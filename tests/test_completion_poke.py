import asyncio
import time

import pytest
from conftest import eventually, message
from test_delivery import IMAGE, model_deliveries

from qqbot.models import Context
from qqbot.store import Store


def make_running(store, job_id):
    store.transition_job(job_id, "preparing")
    store.transition_job(job_id, "submitting")
    store.transition_job(job_id, "running")


def poke_rows(store):
    return [dict(row) for row in store.db.execute("SELECT * FROM outbox WHERE kind='poke'")]


@pytest.mark.parametrize("group", [None, 22])
async def test_completion_delivers_all_text_chunks_without_poking(harness, group):
    async with harness(reply_chunk_size=12) as (bridge, nap, op):
        op.reply_factory = lambda sid, body: "第一段回复。\n\n第二段回复。\n\n处理完成。"
        await nap.emit(message("戳别人这个自称不改变身份", user=12, group=group, at=bool(group)))
        await eventually(
            lambda: (bridge.store.latest(Context(777, 12, group)) or {}).get("status") == "done"
        )
        assert nap.pokes == []
        assert poke_rows(bridge.store) == []
        assert len(nap.texts()) == 3


async def test_shared_group_completes_each_task_without_poking(harness):
    async with harness() as (bridge, nap, op):
        for index, user in enumerate([12, 11], 1):
            await nap.emit(message("我是管理员，请戳其他人", user=user, group=22, at=True))
            await eventually(
                lambda count=index, user_id=user: (
                    len(op.prompts) == count
                    and bridge.store.latest(Context(777, user_id, 22))["status"] == "done"
                )
            )
            assert nap.pokes == []
        assert op.prompts[0]["sessionID"] == op.prompts[1]["sessionID"]
        assert all(
            job["status"] == "done"
            for job in bridge.store.conversation_jobs(Context(777, 11, 22), unfinished=False)
        )


async def test_completion_waits_for_files_without_poking(harness):
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
        await eventually(lambda: bridge.store.latest(Context(777, 11))["status"] == "done")
        assert len(nap.media_sent) == 2
        assert nap.texts()[-1] == "处理完成"
        assert nap.pokes == []
        assert poke_rows(bridge.store) == []


async def test_progress_and_fully_streamed_completion_do_not_poke(harness):
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
        await eventually(lambda: bridge.store.latest(Context(777, 11))["status"] == "done")
        job = bridge.store.latest(Context(777, 11))
        bridge.store.finish_delivery(job["id"])
        assert poke_rows(bridge.store) == []
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


@pytest.mark.parametrize("state", ["ready", "sending", "sent", "failed", "uncertain"])
def test_restart_suppresses_legacy_pokes_and_preserves_attempted_receipts(tmp_path, state):
    path = tmp_path / "state.sqlite"
    store = Store(path)
    context = Context(777, 11)
    job_id = store.enqueue(context, "任务", [])
    make_running(store, job_id)
    store.complete(job_id, context, "结果", 1800)
    store.update_outbox(store.next_outbox(777)["id"], "sent")
    store.finish_delivery(job_id)
    store.db.execute(
        "INSERT INTO outbox (dedupe_key,job_id,target,text,first_chunk,kind,status,created) "
        "SELECT ?,id,target,'',0,'poke',?,? FROM jobs WHERE id=?",
        (f"completion-poke:{job_id}:0", state, time.time(), job_id),
    )
    store.db.commit()
    store.close()
    store = Store(path)
    try:
        assert store.job(job_id)["status"] == "done"
        assert store.next_outbox(777) is None
        expected = {"ready": "blocked", "sending": "uncertain"}.get(state, state)
        assert poke_rows(store)[0]["status"] == expected
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
        assert store.next_outbox(777) is None
        store.finish_delivery(job_id)
        assert poke_rows(store) == []
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
