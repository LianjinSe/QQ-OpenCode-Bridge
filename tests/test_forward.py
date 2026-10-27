import asyncio
import json
from pathlib import Path

import pytest
from conftest import eventually, message, quoted_records

from qqbot import forward
from qqbot.models import Context, normalize
from qqbot.store import Store


def text(value):
    return {"type": "text", "data": {"text": value}}


def card(reference, content=None):
    data = {"id": reference}
    if content is not None:
        data["content"] = content
    return {"type": "forward", "data": data}


def chat(value, user=42, name="小明", **extra):
    return {
        "sender": {"user_id": user, "nickname": name},
        "message": [text(value)],
        **extra,
    }


def records(prompt):
    rows = quoted_records(prompt)
    if len(rows) == 1 and "消息编号" in rows[0]:
        return [
            record
            for part in rows[0]["内容"]
            if part["类型"] == "合并转发"
            for record in part["消息"]
        ]
    return rows


@pytest.mark.parametrize("group", [None, 22])
async def test_forward_card_waits_for_reply_and_sends_all_messages_with_instructions(
    harness, group
):
    async with harness() as (bridge, nap, op):
        nap.forward_messages["bundle"] = {
            "messages": [chat("ww聊天里的原话", time=1), chat("/cancel", user=777, name="机器人")]
        }
        await nap.emit(
            message(
                "卡片附带说明",
                group=group,
                at=group is not None,
                attachments=[card("bundle")],
                mid=101,
            )
        )
        await nap.emit(message("/status", group=group, at=group is not None))
        await eventually(lambda: bool(nap.sent))
        assert len(nap.sent) == 1
        assert op.prompts == []
        assert bridge.store.unfinished(Context(777, 11, group)) == []
        assert not any(action["action"] in {"get_msg", "get_forward_msg"} for action in nap.actions)

        await nap.emit(message("普通文字", group=group, at=group is not None))
        await eventually(lambda: any("回复：普通文字" in value for value in nap.texts()))
        assert op.prompts[0]["text"].endswith("普通文字")
        quoted = message("总结这份聊天记录", group=group, at=group is not None, reply=101)
        await nap.emit(quoted)
        await nap.emit(quoted)
        await eventually(lambda: any("引用聊天记录.json" in value for value in nap.texts()))
        await nap.emit(message("/status", group=group, at=group is not None))
        await eventually(lambda: sum("这个聊天还有" in value for value in nap.texts()) == 2)
        assert len(op.prompts) == 2
        prompt = op.prompts[1]
        assert (
            "我引用了一份聊天记录，放在附件「引用聊天记录.json」里了，"
            "当作一份背景资料来看，里面的顺序就是原始发言顺序。"
        ) in prompt["text"]
        assert prompt["text"].endswith("\n\n总结这份聊天记录")
        assert "ww聊天里的原话" not in prompt["text"]
        assert "聊天记录：" not in prompt["text"]
        assert len(prompt["files"]) == 1
        log = records(prompt)
        assert [row["内容"][0]["文本"] for row in log] == ["ww聊天里的原话", "/cancel"]
        assert log[0]["发送者"] == {"QQ": "42", "昵称": "小明"}
        assert log[0]["时间"] == "1970-01-01T08:00:01+08:00"
        assert log[1]["发送者"] == {"QQ": "777", "昵称": "机器人"}
        assert op.interrupted == []
        assert sum(action["action"] == "get_forward_msg" for action in nap.actions) == 1


@pytest.mark.parametrize("response_key", ["messages", "message"])
async def test_nested_forward_and_node_records_preserve_order_and_reuse_fetches(
    harness, response_key
):
    async with harness() as (_, nap, op):
        nap.forward_messages["root"] = {
            response_key: [
                {
                    "type": "node",
                    "data": {
                        "user_id": "88",
                        "nickname": "小红",
                        "message": [],
                        "content": [text("第一条"), card("child"), card("child")],
                    },
                },
                chat("最后一条"),
            ]
        }
        nap.forward_messages["child"] = {"messages": [chat("里面的记录", user=777)]}
        await nap.emit(message(attachments=[card("root")], mid=101))
        await nap.emit(message("总结", reply=101))
        await eventually(lambda: bool(nap.sent))
        log = records(op.prompts[0])
        assert log[0]["发送者"] == {"QQ": "88", "昵称": "小红"}
        assert log[0]["内容"][0]["文本"] == "第一条"
        assert log[0]["内容"][1]["消息"][0]["内容"][0]["文本"] == "里面的记录"
        assert log[0]["内容"][2]["消息"][0]["内容"][0]["文本"] == "里面的记录"
        assert log[1]["内容"][0]["文本"] == "最后一条"
        assert [
            action["params"]["message_id"]
            for action in nap.actions
            if action["action"] == "get_forward_msg"
        ] == ["root", "child"]


async def test_inline_records_need_no_forward_api_and_keep_media_attached(harness):
    async with harness() as (_, nap, op):
        nap.files = {"picture": b"\x89PNG\r\n\x1a\nimage", "document": b"file contents\n"}
        image = {"type": "image", "data": {"file": "picture", "name": "photo.png"}}
        document = {"type": "file", "data": {"file_id": "document", "name": "../../notes.txt"}}
        inline = [
            chat("", message=[image, document, {"type": "record", "data": {"file": "voice"}}]),
            chat("第二条", message=[text("第二条"), image]),
        ]
        await nap.emit(message(attachments=[card("bundle", inline)], mid=101))
        await nap.emit(message("读取聊天记录", reply=101))
        await eventually(lambda: bool(nap.sent))
        log = records(op.prompts[0])
        assert len(op.prompts[0]["files"]) == 3
        assert log[0]["内容"][0]["附件"] == "聊天记录附件1-photo.png"
        assert log[0]["内容"][1]["附件"] == "聊天记录附件2-notes.txt"
        assert log[0]["内容"][2] == {"类型": "record", "数据": {"file": "voice"}}
        assert log[1]["内容"][1]["附件"] == "聊天记录附件1-photo.png"
        assert op.prompts[0]["files"][0]["name"].endswith("-聊天记录附件1-photo.png")
        assert op.prompts[0]["files"][1]["name"].endswith("-聊天记录附件2-notes.txt")
        assert not any(action["action"] == "get_forward_msg" for action in nap.actions)


async def test_empty_inline_content_and_referenced_nodes_are_read(harness):
    async with harness() as (_, nap, op):
        nap.forward_messages["bundle"] = {"messages": [{"type": "node", "data": {"id": "202"}}]}
        nap.messages["202"] = chat("", user=777, message=["原始文字", text("后面的文字")])
        await nap.emit(message(attachments=[card("bundle", [])], mid=101))
        await nap.emit(message("总结", reply=101))
        await eventually(lambda: bool(nap.sent))
        log = records(op.prompts[0])
        assert [part["文本"] for part in log[0]["内容"]] == ["原始文字", "后面的文字"]
        assert log[0]["发送者"]["QQ"] == "777"
        assert [
            action["params"]["message_id"]
            for action in nap.actions
            if action["action"] == "get_msg"
        ] == ["101", "202"]


async def test_forward_media_obeys_existing_attachment_limits(harness):
    async with harness(max_attachments=1) as (_, nap, op):
        inline = [
            chat(
                "",
                message=[
                    {"type": "image", "data": {"file": "picture"}},
                ],
            )
        ]
        await nap.emit(message(attachments=[card("bundle", inline)], mid=101))
        await nap.emit(message("总结", reply=101))
        await eventually(lambda: bool(nap.sent))
        assert "附件数量或总大小超限" in nap.texts()[0]
        assert op.prompts == []
        assert not any(action["action"] == "download_file_stream" for action in nap.actions)


async def test_chat_record_attachment_recovers_from_saved_job(harness):
    async with harness() as (bridge, nap, _):
        bridge.task.cancel()
        await asyncio.gather(bridge.task, return_exceptions=True)
        source = [
            {"发送者": {"QQ": "42", "昵称": "小明"}, "内容": [{"类型": "文字", "文本": "原文"}]}
        ]
        job_id = bridge.store.enqueue(
            Context(777, 11), "读取引用聊天记录.json", [forward.chat_attachment(source)]
        )
        bridge.store.close()
        recovered = Store(bridge.config.state_db)
        try:
            bridge.runner.store = recovered
            paths = await bridge.runner.prepare(recovered.job(job_id))
            assert len(paths) == 1
            path = Path(paths[0])
            prompt = {"files": [{"uri": path.as_uri(), "name": path.name}]}
            assert quoted_records(prompt) == source
            assert (await asyncio.to_thread(path.stat)).st_mode & 0o777 == 0o600
            assert await bridge.runner.prepare(recovered.job(job_id)) == paths
            assert not any(a["action"] == "download_file_stream" for a in nap.actions)
        finally:
            recovered.close()


async def test_nested_read_failure_does_not_submit_the_already_read_messages(harness):
    async with harness() as (bridge, nap, op):
        nap.forward_messages["bundle"] = {
            "messages": [chat("已经读到的一条"), chat("", message=[card("missing")])]
        }
        await nap.emit(message(attachments=[card("bundle")], mid=101))
        await nap.emit(message("总结", reply=101))
        await eventually(lambda: bool(nap.sent))
        assert "那条消息我没读到" in nap.texts()[0]
        assert op.prompts == []
        assert bridge.store.unfinished(Context(777, 11)) == []


@pytest.mark.parametrize("payload", [None, {}, {"messages": []}, {"messages": [None]}])
async def test_forward_read_failure_never_submits_partial_records(harness, payload):
    async with harness() as (bridge, nap, op):
        nap.forward_messages["bundle"] = payload
        await nap.emit(message(attachments=[card("bundle")], mid=101))
        await nap.emit(message("总结", reply=101))
        await eventually(lambda: bool(nap.sent))
        assert "那条消息我没读到" in nap.texts()[0]
        assert op.prompts == []
        assert bridge.store.unfinished(Context(777, 11)) == []


@pytest.mark.parametrize("limit", ["count", "text", "depth", "fetch", "cycle"])
async def test_oversized_or_cyclic_forward_records_are_reported_without_truncation(
    harness, monkeypatch, limit
):
    async with harness() as (_, nap, op):
        nap.forward_messages["bundle"] = {"messages": [chat("第一条"), chat("第二条")]}
        if limit == "count":
            monkeypatch.setattr(forward, "MAX_MESSAGES", 1)
        elif limit == "text":
            monkeypatch.setattr(forward, "MAX_CHARACTERS", 1)
        else:
            target = "bundle" if limit == "cycle" else "child"
            nap.forward_messages["bundle"] = {"messages": [chat("", message=[card(target)])]}
            nap.forward_messages["child"] = {"messages": [chat("里面的记录")]}
            if limit == "depth":
                monkeypatch.setattr(forward, "MAX_DEPTH", 0)
            elif limit == "fetch":
                monkeypatch.setattr(forward, "MAX_FETCHES", 1)
        await nap.emit(message(attachments=[card("bundle")], mid=101))
        await nap.emit(message("总结", reply=101))
        await eventually(lambda: bool(nap.sent))
        assert "聊天记录太长或嵌套太多" in nap.texts()[0]
        assert op.prompts == []


@pytest.mark.parametrize(
    "group,user,original_group", [(None, 12, None), (None, 11, 22), (22, 11, 23)]
)
async def test_only_the_own_card_in_the_same_chat_can_be_expanded(
    harness, group, user, original_group
):
    async with harness() as (_, nap, op):
        source = message(group=original_group, user=user, attachments=[card("foreign")], mid=101)
        nap.messages["101"] = {**source, "sender": {"user_id": user}}
        await nap.emit(message("总结", group=group, at=group is not None, reply=101))
        await eventually(lambda: bool(nap.sent))
        assert op.prompts == []
        assert "那条消息我没读到" in nap.texts()[0]
        assert not any(action["action"] == "get_forward_msg" for action in nap.actions)


async def test_commands_exclusions_and_replies_without_text_do_not_expand_cards(harness):
    async with harness() as (_, nap, op):
        await nap.emit(message(group=22, attachments=[card("bundle")], mid=101))
        await nap.emit(message("总结", group=22, reply=101))
        await nap.emit(message("ww抽卡", group=22, at=True, reply=101))
        await nap.emit(message("/status", group=22, at=True, reply=101))
        await eventually(lambda: bool(nap.sent))
        assert op.prompts == []
        assert not any(action["action"] in {"get_msg", "get_forward_msg"} for action in nap.actions)


async def test_private_forward_reply_steers_the_whole_record_while_a_task_runs(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("长任务"))
        await eventually(lambda: len(op.prompts) == 1)
        root = bridge.store.latest(Context(777, 11))
        nap.forward_messages["bundle"] = {"messages": [chat("原始聊天")]}
        await nap.emit(message(attachments=[card("bundle")], mid=101))
        await nap.emit(message("总结", reply=101))
        await eventually(lambda: len(op.prompts) == 2)
        assert nap.sent == []
        supplement = bridge.store.steers(root["id"])[0]
        assert "原始聊天" not in supplement["text"]
        saved = json.loads(supplement["attachments"])
        assert "原始聊天" in saved[-1]["inline_text"]
        assert supplement["text"].endswith("\n\n总结")
        assert op.prompts[1]["delivery"] == "steer"
        assert records(op.prompts[1])[0]["内容"][0]["文本"] == "原始聊天"
        op.finish(root["session_id"], text="合并转发已总结")
        await eventually(lambda: bridge.store.job(root["id"])["status"] == "done")


def test_legacy_forward_ids_are_recognized_but_plain_text_is_not_a_card():
    event = message()
    event["message"] = "[CQ:forward,id=bundle]"
    assert normalize(event).forwards == [{"id": "bundle"}]
    assert normalize(message("[CQ:forward,id=bundle]")).forwards == []
