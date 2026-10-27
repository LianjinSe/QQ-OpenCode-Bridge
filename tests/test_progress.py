import asyncio
import json
import time

import pytest
from conftest import eventually, message

from qqbot.bridge import Bridge
from qqbot.delivery import directory, marker
from qqbot.models import Context
from qqbot.opencode import reply_segments, text_outputs
from qqbot.store import Store


def progress(mid, text, *, streaming=False):
    return {
        "id": mid,
        "type": "assistant",
        "time": {"created": time.time() * 1000},
        "content": [
            {"type": "reasoning", "text": "私密推理不应转发"},
            {"type": "text", "text": text},
            {
                "type": "tool",
                "id": "tool_" + mid,
                "name": "read",
                "state": {
                    "status": "streaming" if streaming else "running",
                    "input": {"path": "不应转发的路径.txt"},
                    "content": [{"type": "text", "text": "不应转发的工具日志"}],
                },
            },
        ],
    }


async def test_progress_arrives_before_completion_without_releasing_the_serial_queue(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("修改文档", user=12, group=22, at=True))
        await eventually(lambda: len(op.prompts) == 1)
        sid = op.prompts[0]["sessionID"]
        op.messages[sid].append(progress("msg_progress", "我先看看你提到的文档。"))
        await eventually(lambda: "我先看看你提到的文档。" in [text.strip() for text in nap.texts()])
        context = Context(777, 12, 22)
        assert bridge.store.latest(context)["status"] == "running"
        sent = nap.sent[0]
        assert sent["group_id"] == "22"
        assert sent["message"][0] == {"type": "at", "data": {"qq": "12"}}

        await nap.emit(message("下一项任务", group=22, at=True))
        await eventually(lambda: len(bridge.store.conversation_jobs(context)) == 2)
        assert len(op.prompts) == 1
        op.messages[sid].append(
            {
                "id": "msg_second_progress",
                "type": "assistant",
                "content": [{"type": "text", "text": "文档看完了，我来修改。"}],
            }
        )
        op.mode = "normal"
        op.finish(sid, "文档修改完成。")
        await eventually(lambda: len(op.prompts) == 2)
        await eventually(lambda: not bridge.store.conversation_jobs(context))
        texts = [text.strip() for text in nap.texts()]
        assert texts.count("我先看看你提到的文档。") == 1
        assert texts.count("文档看完了，我来修改。") == 1
        assert texts.count("文档修改完成。") == 1
        assert texts.index("我先看看你提到的文档。") < texts.index("文档看完了，我来修改。")
        assert texts.index("文档看完了，我来修改。") < texts.index("文档修改完成。")
        assert "不应转发" not in "\n".join(texts)


async def test_streaming_paragraphs_arrive_before_the_message_finishes(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("查看文档"))
        await eventually(lambda: bool(op.prompts))
        sid = op.prompts[0]["sessionID"]
        item = progress("msg_streaming", "我先", streaming=True)
        item["content"].pop()  # Only a reasoning block and the growing text block exist.
        op.messages[sid].append(item)
        await asyncio.sleep(0.1)
        assert nap.texts() == []
        item["content"][1]["text"] = "我先看看文档。\n\n发现了两处"
        await eventually(lambda: nap.texts() == ["我先看看文档。"])
        assert bridge.store.latest(Context(777, 11))["status"] == "running"
        assert "streamed" not in item["time"]
        item["content"][1]["text"] = "我先看看文档。\n\n发现了两处问题。"
        item["time"]["streamed"] = time.time() * 1000
        await eventually(lambda: nap.texts() == ["我先看看文档。", "发现了两处问题。"])
        op.finish(sid, "查看完成。")
        await eventually(lambda: bridge.store.latest(Context(777, 11))["status"] == "done")
        assert nap.texts() == ["我先看看文档。", "发现了两处问题。", "查看完成。"]


async def test_progress_is_not_replayed_after_restart(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("继续处理文档"))
        await eventually(lambda: bool(op.prompts))
        sid = op.prompts[0]["sessionID"]
        item = {
            "id": "msg_before_restart",
            "type": "assistant",
            "content": [{"type": "text", "text": "我先读取第一段。\n\n再读取"}],
        }
        op.messages[sid].append(item)
        await eventually(lambda: nap.texts() == ["我先读取第一段。"])
        job = bridge.store.latest(Context(777, 11))
        bridge.task.cancel()
        await asyncio.gather(bridge.task, return_exceptions=True)
        await bridge.onebot.disconnect()
        bridge.store.close()
        store = Store(bridge.config.state_db)
        restored = Bridge(bridge.config, store, bridge.onebot, bridge.opencode)
        task = asyncio.create_task(restored.run())
        try:
            await asyncio.wait_for(bridge.onebot.ready.wait(), 3)
            item["content"][0]["text"] = "我先读取第一段。\n\n再读取第二段。\n\n"
            await eventually(lambda: nap.texts() == ["我先读取第一段。", "再读取第二段。"])
            op.finish(sid, "文档处理完了。")
            await eventually(lambda: store.job(job["id"])["status"] == "done")
            assert nap.texts() == ["我先读取第一段。", "再读取第二段。", "文档处理完了。"]
            assert len(op.prompts) == 1
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await bridge.onebot.disconnect()
            store.close()


async def test_progress_preserves_file_delivery_and_hides_the_manifest(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("修改文档后发给我"))
        await eventually(lambda: bool(op.prompts))
        sid = op.prompts[0]["sessionID"]
        job = bridge.store.latest(Context(777, 11))
        op.messages[sid].append(progress("msg_read_document", "我先看看文档。"))
        await eventually(lambda: "我先看看文档。" in nap.texts())
        (directory(bridge.config, job["id"]) / "report.txt").write_text("修改后的文档")
        await bridge.delivery_tools.submit(
            sid, "edited-document", {"files": [{"path": "report.txt"}]}
        )
        op.finish(
            sid,
            "修改完成。\n"
            + marker(job["id"])
            + "\n"
            + json.dumps({"files": [{"path": "report.txt"}]})
            + "\n</qq-delivery>",
        )
        await eventually(lambda: bridge.store.job(job["id"])["status"] == "done")
        assert nap.media_sent[0]["bytes"] == "修改后的文档".encode()
        assert nap.texts()[0] == "我先看看文档。"
        assert "修改完成。" in nap.texts()
        assert nap.texts()[-1] == "修改完成。"
        assert "qq-delivery" not in "\n".join(nap.texts())


async def test_turn_ending_after_a_tool_does_not_repeat_its_text(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("检查文档"))
        await eventually(lambda: bool(op.prompts))
        sid = op.prompts[0]["sessionID"]
        item = progress("msg_only_answer", "我来检查文档。")
        op.messages[sid].append(item)
        await eventually(lambda: nap.texts() == ["我来检查文档。"])
        item["content"][-1]["state"]["status"] = "completed"
        op.active_ids.pop(sid)
        op.messages[sid].append({"id": "msg_idle", "type": "idle", "outcome": "succeeded"})
        op.sessions[sid]["outcome"] = "succeeded"
        op.sessions[sid]["time"]["idle"] = time.time() * 1000
        await eventually(lambda: bridge.store.latest(Context(777, 11))["status"] == "done")
        assert nap.texts() == ["我来检查文档。"]


async def test_long_progress_is_chunked_once(harness):
    async with harness(reply_chunk_size=12) as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("检查长文档"))
        await eventually(lambda: bool(op.prompts))
        sid = op.prompts[0]["sessionID"]
        text = "我先看看文档里的这些段落。" * 4
        op.messages[sid].append(progress("msg_long_progress", text))
        await eventually(lambda: "".join(nap.texts()) == text)
        assert bridge.store.latest(Context(777, 11))["status"] == "running"
        op.finish(sid, "完成。")
        await eventually(lambda: bridge.store.latest(Context(777, 11))["status"] == "done")
        assert "".join(nap.texts()) == text + "完成。"
        assert all(len(part) <= 12 for part in nap.texts())


@pytest.mark.parametrize("status", ["failed", "uncertain"])
def test_progress_send_failure_survives_restart_and_allows_the_final_answer(tmp_path, status):
    path = tmp_path / "state.sqlite"
    store = Store(path)
    context = Context(777, 11)
    job_id = store.enqueue(context, "处理文档", [])
    store.transition_job(job_id, "preparing")
    store.transition_job(job_id, "submitting")
    store.transition_job(job_id, "running")
    store.put_outbox(context, "我先看看文档。", f"progress:{job_id}:msg_first", 1800, job_id)
    first = store.next_outbox(777)
    store.update_outbox(first["id"], status)
    store.finish_delivery(job_id)
    assert store.job(job_id)["status"] == "running"
    store.close()
    store = Store(path)
    try:
        assert store.job(job_id)["status"] == "running"
        store.complete(job_id, context, "文档处理完成。", 1800)
        final = store.next_outbox(777)
        assert final["text"] == "文档处理完成。"
        store.update_outbox(final["id"], "sent")
        store.finish_delivery(job_id)
        assert store.job(job_id)["status"] == "done"
    finally:
        store.close()


def test_progress_hides_delivery_protocol_including_incomplete_blocks():
    first = progress("msg_protocol", '我先整理文档。\n<qq-delivery id="job">\n{"files":[]')
    last = {"id": "msg_final", "type": "assistant", "content": [{"type": "text", "text": "完成"}]}
    assert text_outputs([first]) == []
    outputs = text_outputs([first, last])
    mid, part_index, text, complete = outputs[0]
    assert (mid, part_index, complete) == ("msg_protocol", 1, True)
    assert [body for _, body in reply_segments(text, 0, 1800, complete=complete)] == [
        "我先整理文档。"
    ]


async def test_completed_text_block_is_forwarded_while_the_next_block_streams(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("逐段处理"))
        await eventually(lambda: bool(op.prompts))
        sid = op.prompts[0]["sessionID"]
        item = {
            "id": "msg_blocks",
            "type": "assistant",
            "content": [
                {"type": "text", "text": "第一个文本块。"},
                {"type": "reasoning", "text": "不应转发的推理"},
                {"type": "text", "text": "第二个文本块的第一段。\n\n尾段"},
            ],
        }
        op.messages[sid].append(item)
        await eventually(lambda: nap.texts() == ["第一个文本块。", "第二个文本块的第一段。"])
        item["content"][-1]["text"] += "完成。"
        op.active_ids.pop(sid)
        op.messages[sid].append({"id": "msg_blocks_idle", "type": "idle", "outcome": "succeeded"})
        op.sessions[sid]["outcome"] = "succeeded"
        op.sessions[sid]["time"]["idle"] = time.time() * 1000
        await eventually(lambda: bridge.store.latest(Context(777, 11))["status"] == "done")
        assert nap.texts() == ["第一个文本块。", "第二个文本块的第一段。", "尾段完成。"]


async def test_streaming_delivery_marker_never_leaks_and_final_text_is_not_repeated(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("修改文档并回传"))
        await eventually(lambda: bool(op.prompts))
        sid = op.prompts[0]["sessionID"]
        job = bridge.store.latest(Context(777, 11))
        item = {
            "id": "msg_streaming_delivery",
            "type": "assistant",
            "content": [{"type": "text", "text": "文档已经读取。\n\n正在修改"}],
        }
        op.messages[sid].append(item)
        await eventually(lambda: nap.texts() == ["文档已经读取。"])
        item["content"][0]["text"] = "文档已经读取。\n\n正在修改。\n\n<qq-deli"
        await eventually(lambda: nap.texts() == ["文档已经读取。", "正在修改。"])
        (directory(bridge.config, job["id"]) / "report.txt").write_text("edited")
        await bridge.delivery_tools.submit(
            sid, "streamed-document", {"files": [{"path": "report.txt"}]}
        )
        item["content"][0]["text"] = (
            "文档已经读取。\n\n正在修改。\n\n修改完成。\n\n"
            + marker(job["id"])
            + '\n{"files":[{"path":"report.txt"}]}\n</qq-delivery>'
        )
        op.active_ids.pop(sid)
        op.messages[sid].append({"id": "msg_delivery_idle", "type": "idle", "outcome": "succeeded"})
        op.sessions[sid]["outcome"] = "succeeded"
        op.sessions[sid]["time"]["idle"] = time.time() * 1000
        await eventually(lambda: bridge.store.job(job["id"])["status"] == "done")
        assert nap.texts()[:3] == ["文档已经读取。", "正在修改。", "修改完成。"]
        assert len(nap.media_sent) == 1
        assert nap.texts()[-1] == "修改完成。"
        assert "qq-deli" not in "\n".join(nap.texts())


@pytest.mark.parametrize("length", range(1, len("<qq-delivery") + 1))
def test_split_delivery_marker_is_held_at_chunk_boundaries(length):
    text = "正常文字\n\n" + "<qq-delivery"[:length]
    bodies = [body for _, body in reply_segments(text, 0, 4, complete=False)]
    assert "".join(bodies) == "正常文字"


def test_progress_cursor_and_outbox_roll_back_together(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.sqlite")
    context = Context(777, 11)
    job_id = store.enqueue(context, "处理文档", [])

    def unavailable(*args, **kwargs):
        raise RuntimeError("模拟写入中断")

    monkeypatch.setattr(store, "put_outbox", unavailable)
    try:
        with pytest.raises(RuntimeError, match="模拟写入中断"):
            store.put_progress(context, job_id, "msg_progress", 0, "第一段。\n\n", "第一段。", 1800)
        assert store.output_prefix(job_id, "msg_progress", 0) == ""
        assert store.next_outbox(777) is None
    finally:
        store.close()


def test_existing_database_gains_cursors_without_replaying_legacy_progress(tmp_path):
    path = tmp_path / "state.sqlite"
    context = Context(777, 11)
    store = Store(path)
    job_id = store.enqueue(context, "检查文档", [])
    store.transition_job(job_id, "preparing")
    store.transition_job(job_id, "submitting")
    store.transition_job(job_id, "running")
    key = f"progress:{job_id}:msg_legacy"
    store.put_outbox(context, "已经发送的过程说明。", key, 1800, job_id)
    store.update_outbox(store.next_outbox(777)["id"], "sent")
    store.db.execute("DROP TABLE assistant_output_cursors")
    store.db.commit()
    store.close()
    store = Store(path)
    try:
        assert store.job(job_id)["status"] == "running"
        assert store.output_prefix(job_id, "msg_legacy", 0) == ""
        assert store.has_outbox(key)
        assert store.next_outbox(777) is None
    finally:
        store.close()


async def test_bare_manifest_json_never_reaches_qq(harness):
    """清单 JSON 与标签被拆到不同文本块时，也不能把内部内容发给用户。"""
    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("工具装好了吗"))
        await eventually(lambda: bool(op.prompts))
        sid = op.prompts[0]["sessionID"]
        op.messages[sid].append(
            {
                "id": "msg_manifest_split",
                "type": "assistant",
                "content": [
                    {"type": "text", "text": "明白啦，那就不用管它了。\n\n"},
                    {"type": "text", "text": '{"files":[]}\n</qq-delivery>'},
                ],
            }
        )
        await eventually(lambda: "明白啦，那就不用管它了。" in nap.texts())
        op.finish(sid, "好了。")
        await eventually(lambda: bridge.store.latest(Context(777, 11))["status"] == "done")
        joined = "\n".join(nap.texts())
        assert '"files"' not in joined
        assert "</qq-delivery>" not in joined
        assert "明白啦" in joined
