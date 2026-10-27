import asyncio
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from conftest import eventually, message, quoted_records

from qqbot.models import Attachment, Context, normalize


@pytest.mark.parametrize("group,caption", [(None, ""), (22, "原消息的附件说明")])
async def test_quoted_media_are_files_with_plain_caption_and_no_json(harness, group, caption):
    async with harness() as (bridge, nap, op):
        media = {
            "photo.png": ("image", b"\x89PNG\r\n\x1a\nphoto"),
            "clip.mp4": ("video", b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00"),
            "music.wav": ("audio", b"RIFF\x00\x00\x00\x00WAVEdata"),
            "voice.silk": ("record", b"\x02#!SILK_V3\x00\xff"),
            "document.bin": ("file", b"\x00\xff\x01"),
        }
        nap.files = {name: data for name, (_, data) in media.items()}
        parts = [
            {"type": kind, "data": {"file": name, "name": name, "file_size": len(data)}}
            for name, (kind, data) in media.items()
        ]
        nap.messages["101"] = {
            **message(caption, group=group, mid=101, attachments=parts + parts[:1]),
            "sender": {"user_id": 11},
        }
        await nap.emit(message("处理这些附件", group=group, at=group is not None, reply=101))
        await eventually(lambda: bool(op.prompts))
        prompt = op.prompts[0]
        assert len(prompt["files"]) == len(media)
        assert "聊天记录：" not in prompt["text"]
        assert prompt["text"].endswith("处理这些附件")
        if caption:
            assert f"> {caption}" in prompt["text"]
        else:
            assert prompt["text"] == "处理这些附件"
        for file, (name, (_, data)) in zip(prompt["files"], media.items(), strict=True):
            assert file["name"].endswith("-" + name)
            path = Path(unquote(urlsplit(file["uri"]).path))
            assert await asyncio.to_thread(path.read_bytes) == data
        job = bridge.store.latest(Context(777, 11, group))
        assert [a["kind"] for a in json.loads(job["attachments"])] == [
            "image",
            "video",
            "audio",
            "audio",
            "file",
        ]


@pytest.mark.parametrize("original_id", [101, -101])
@pytest.mark.parametrize("group", [None, 22])
@pytest.mark.parametrize("kind", ["image", "file"])
async def test_reply_uses_only_the_quoted_attachment_after_unrelated_text(
    harness, original_id, group, kind
):
    async with harness() as (bridge, nap, op):
        nap.files = {"first": b"\x89PNG\r\n\x1a\nfirst", "second": b"\x89PNG\r\n\x1a\nsecond"}
        await nap.emit(
            message(
                group=group,
                mid=original_id,
                attachments=[{"type": kind, "data": {"file_id": "first", "name": "first.png"}}],
            )
        )
        await nap.emit(
            message(
                group=group,
                mid=102,
                attachments=[{"type": kind, "data": {"file_id": "second", "name": "second.png"}}],
            )
        )
        await nap.emit(message("普通文字", group=group, at=group is not None))
        await eventually(lambda: any("回复：普通文字" in text for text in nap.texts()))
        assert op.prompts[0]["files"] == []
        assert bridge.store.staged(Context(777, 11, group)) == []
        assert not any(action["action"] == "get_msg" for action in nap.actions)

        quoted = message("分析第一张图", group=group, at=group is not None, reply=original_id)
        await nap.emit(quoted)
        await nap.emit(quoted)
        await eventually(lambda: any("分析第一张图" in text for text in nap.texts()))
        await nap.emit(message("/status", group=group, at=group is not None))
        await eventually(lambda: any("这个聊天还有" in text for text in nap.texts()))
        assert len(op.prompts) == 2
        assert op.prompts[1]["text"].endswith("分析第一张图")
        assert op.prompts[1]["sessionID"] == op.prompts[0]["sessionID"]
        assert len(op.prompts[1]["files"]) == 1
        assert op.prompts[1]["files"][0]["name"].endswith("-first.png")
        assert [
            action["params"]["file_id"]
            for action in nap.actions
            if action["action"] == "download_file_stream"
        ] == ["first"]
        assert sum(action["action"] == "get_msg" for action in nap.actions) == 1


@pytest.mark.parametrize(
    "group,original_user,original_group",
    [
        (22, 11, 23),
        (22, 11, None),
        (None, 12, None),
        (None, 777, None),
        (None, 11, 22),
    ],
)
@pytest.mark.parametrize("kind", ["image", "file"])
async def test_reply_does_not_attach_another_sender_or_chat(
    harness, group, original_user, original_group, kind
):
    async with harness() as (_, nap, op):
        original = message(
            user=original_user,
            group=original_group,
            mid=101,
            attachments=[{"type": kind, "data": {"file_id": "foreign-attachment"}}],
        )
        nap.messages["101"] = {**original, "sender": {"user_id": original_user}}
        await nap.emit(message("看图", group=group, at=group is not None, reply=101))
        await eventually(lambda: bool(nap.sent))
        assert "那条消息我没读到" in nap.texts()[0]
        assert op.prompts == []
        assert not any(action["action"] == "download_file_stream" for action in nap.actions)


@pytest.mark.parametrize("kind", ["image", "file"])
async def test_group_reply_requires_at_and_preserves_command_routing(harness, kind):
    async with harness() as (_, nap, op):
        await nap.emit(
            message(
                group=22,
                mid=101,
                attachments=[{"type": kind, "data": {"file_id": "unused-attachment"}}],
            )
        )
        await nap.emit(message("没有@", group=22, reply=101))
        await nap.emit(message("ww抽卡", group=22, at=True, reply=101))
        await nap.emit(message("/status", group=22, at=True, reply=101))
        await eventually(lambda: bool(nap.sent))
        assert op.prompts == []
        assert not any(action["action"] == "get_msg" for action in nap.actions)


@pytest.mark.parametrize("original", [None, {}, {"sender": {"user_id": 11}}])
@pytest.mark.parametrize("group", [None, 22])
async def test_unavailable_quoted_message_reports_failure_without_submitting(
    harness, original, group
):
    async with harness() as (bridge, nap, op):
        nap.messages["101"] = original
        await nap.emit(message("分析图片", group=group, at=group is not None, reply=101))
        await eventually(lambda: bool(nap.sent))
        assert "那条消息我没读到" in nap.texts()[0]
        assert op.prompts == []
        assert bridge.store.unfinished(Context(777, 11, group)) == []
        await nap.emit(message("/status", group=group, at=group is not None))
        await eventually(lambda: len(nap.sent) == 2)


@pytest.mark.parametrize("group", [None, 22])
@pytest.mark.parametrize("kind", ["image", "file"])
async def test_quoted_attachments_obey_attachment_limits(harness, group, kind):
    async with harness(max_attachment_bytes=4) as (_, nap, op):
        await nap.emit(
            message(
                group=group,
                mid=101,
                attachments=[
                    {"type": kind, "data": {"file_id": "large-attachment", "file_size": 5}}
                ],
            )
        )
        await nap.emit(message("分析图片", group=group, at=group is not None, reply=101))
        await eventually(lambda: bool(nap.sent))
        assert "附件数量或总大小超限" in nap.texts()[0]
        assert op.prompts == []
        assert not any(action["action"] == "download_file_stream" for action in nap.actions)


@pytest.mark.parametrize("kind", ["image", "file"])
async def test_old_staged_attachments_are_not_added_to_unrelated_group_task(harness, kind):
    async with harness() as (bridge, nap, op):
        bridge.store.stage(Context(777, 11, 22), [Attachment("old-attachment", kind=kind)], 600, 5)
        await nap.emit(message("普通文字", group=22, at=True))
        await eventually(lambda: bool(op.prompts))
        assert op.prompts[0]["files"] == []


@pytest.mark.parametrize("original_user", [11, 777])
async def test_private_reply_to_text_or_bot_keeps_text_routing(harness, original_user):
    async with harness() as (bridge, nap, op):
        if original_user == 777:
            bridge.store.put_outbox(Context(777, 11), "之前的文字", "fixture", 1800)
            row = bridge.store.next_outbox(777)
            bridge.store.update_outbox(row["id"], "sent", "101")
        nap.messages["101"] = {
            **message("之前的文字", user=original_user, mid=101),
            "sender": {"user_id": original_user},
        }
        await nap.emit(message("私聊文字", reply=101))
        await eventually(lambda: bool(op.prompts))
        assert len(op.prompts[0]["files"]) == 1
        assert "之前的文字" not in op.prompts[0]["text"]
        assert "之前的文字" in json.dumps(quoted_records(op.prompts[0]), ensure_ascii=False)
        assert any(action["action"] == "get_msg" for action in nap.actions)


@pytest.mark.parametrize("busy", [False, True])
@pytest.mark.parametrize("kind", ["image", "file"])
async def test_private_attachment_only_stays_silent_when_idle_or_busy(harness, busy, kind):
    async with harness(max_queued_per_context=1) as (bridge, nap, op):
        if busy:
            op.mode = "stalled"
            await nap.emit(message("长任务"))
            await eventually(lambda: len(op.prompts) == 1)
        attachment = {
            "type": kind,
            "data": {"file_id": "unused-attachment", "file_size": 99999999},
        }
        await nap.emit(message(attachments=[attachment], mid=101))
        await nap.emit(message(" \n\t ", attachments=[attachment], mid=102))
        await nap.emit(message(reply=101))
        await nap.emit(message("/status"))
        await eventually(lambda: bool(nap.sent))
        assert len(nap.sent) == 1
        assert "这个聊天还有" in nap.texts()[0]
        assert len(op.prompts) == int(busy)
        assert len(bridge.store.unfinished(Context(777, 11))) == int(busy)
        assert op.interrupted == []
        assert not any(
            action["action"] in {"get_msg", "download_file_stream"} for action in nap.actions
        )


async def test_private_image_with_text_creates_one_task(harness):
    async with harness() as (_, nap, op):
        nap.files["image"] = b"\x89PNG\r\n\x1a\nimage"
        await nap.emit(
            message(
                "解释这张图",
                attachments=[{"type": "image", "data": {"file": "image", "name": "image.png"}}],
            )
        )
        await eventually(lambda: bool(nap.sent))
        assert len(op.prompts) == 1
        assert op.prompts[0]["text"] == "解释这张图"
        assert len(op.prompts[0]["files"]) == 1
        assert op.prompts[0]["files"][0]["name"].endswith("-image.png")
        assert not any(action["action"] == "get_msg" for action in nap.actions)


@pytest.mark.parametrize("group", [None, 22])
async def test_file_upload_with_caption_waits_for_a_reply(harness, group):
    async with harness() as (bridge, nap, op):
        nap.files["document"] = b"document contents\n"
        await nap.emit(
            message(
                "文件说明",
                group=group,
                at=group is not None,
                mid=101,
                attachments=[
                    {"type": "file", "data": {"file_id": "document", "name": "document.txt"}}
                ],
            )
        )
        await nap.emit(message("/status", group=group, at=group is not None))
        await eventually(lambda: bool(nap.sent))
        assert len(nap.sent) == 1
        assert op.prompts == []
        assert bridge.store.unfinished(Context(777, 11, group)) == []
        assert not any(action["action"] == "download_file_stream" for action in nap.actions)

        await nap.emit(message("总结文件", group=group, at=group is not None, reply=101))
        await eventually(lambda: any("总结文件" in text for text in nap.texts()))
        assert len(op.prompts) == 1
        assert op.prompts[0]["text"].endswith("总结文件")
        assert len(op.prompts[0]["files"]) == 1
        assert op.prompts[0]["files"][0]["name"].endswith("-document.txt")


async def test_group_upload_notice_is_not_attached_to_the_next_message(harness):
    async with harness() as (bridge, nap, op):
        await nap.emit(
            {
                "post_type": "notice",
                "notice_type": "group_upload",
                "self_id": 777,
                "user_id": 11,
                "group_id": 22,
                "time": 1,
                "file": {"id": "unquoted-file", "name": "old.txt", "size": 10},
            }
        )
        await nap.emit(message("普通文字", group=22, at=True))
        await eventually(lambda: any("回复：普通文字" in text for text in nap.texts()))
        assert op.prompts[0]["files"] == []
        assert bridge.store.staged(Context(777, 11, 22)) == []
        assert not any(action["action"] == "download_file_stream" for action in nap.actions)


async def test_group_file_reply_queues_while_the_previous_task_is_running(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("长任务", group=22, at=True))
        await eventually(lambda: len(op.prompts) == 1)
        nap.files["document"] = b"document contents\n"
        await nap.emit(
            message(
                mid=101,
                group=22,
                attachments=[
                    {"type": "file", "data": {"file_id": "document", "name": "document.txt"}}
                ],
            )
        )
        await nap.emit(message("总结文件", reply=101, group=22, at=True))
        await eventually(lambda: any("这条已经替你排好队" in text for text in nap.texts()))
        assert len(bridge.store.unfinished(Context(777, 11, 22))) == 2
        assert len(op.prompts) == 1
        assert op.interrupted == []
        assert not any(action["action"] == "download_file_stream" for action in nap.actions)

        op.mode = "normal"
        op.finish(op.prompts[0]["sessionID"], text="上一件完成")
        await eventually(lambda: any("总结文件" in text for text in nap.texts()))
        assert len(op.prompts) == 2
        assert op.prompts[1]["text"].endswith("总结文件")
        assert len(op.prompts[1]["files"]) == 1


@pytest.mark.parametrize("reply_id", [101, "-101"])
def test_reply_segment_preserves_message_id_and_text(reply_id):
    event = message("说明", group=22, at=True)
    event["message"].insert(0, {"type": "reply", "data": {"id": reply_id}})
    incoming = normalize(event)
    assert incoming.reply_id == str(reply_id)
    assert incoming.mentioned
    assert incoming.text == "说明"


def test_legacy_cq_reply_is_parsed_without_interpreting_plain_text_segments():
    event = message(group=22)
    event["message"] = "[CQ:reply,id=-101][CQ:at,qq=777]说明"
    incoming = normalize(event)
    assert incoming.reply_id == "-101"
    assert incoming.mentioned
    assert incoming.text == "说明"
    literal = normalize(message("[CQ:reply,id=-101]", group=22, at=True))
    assert literal.reply_id is None
