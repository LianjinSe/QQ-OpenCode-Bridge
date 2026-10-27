import json

import pytest
from conftest import eventually, message, quoted_records

from qqbot.models import Context


def card():
    return {
        "app": "com.tencent.tuwen.lua",
        "config": {"token": "do-not-copy"},
        "meta": {
            "news": {
                "title": "记得给妈充电",
                "desc": "分享摘要",
                "jumpUrl": "mqqapi://unusable-app-link",
                "qqdocurl": "https://www.xiaohongshu.com/discovery/item/example",
                "tag": "小红书",
            }
        },
    }


@pytest.mark.parametrize("group", [None, 22])
@pytest.mark.parametrize("kind", ["json", "share"])
async def test_quote_card_submits_link_without_chat_records(harness, group, kind):
    async with harness() as (bridge, nap, op):
        data = (
            {"data": json.dumps(card(), ensure_ascii=False)}
            if kind == "json"
            else {
                "title": "记得给妈充电",
                "content": "分享摘要",
                "url": "https://www.xiaohongshu.com/discovery/item/example",
            }
        )
        nap.messages["101"] = {
            **message(group=group, mid=101, attachments=[{"type": kind, "data": data}]),
            "sender": {"user_id": 11},
        }
        await nap.emit(message("这条消息你能看到吗", group=group, at=bool(group), reply=101))
        await eventually(lambda: bool(nap.sent))
        prompt = op.prompts[0]["text"]
        assert op.prompts[0]["files"] == []
        assert prompt.endswith(
            "https://www.xiaohongshu.com/discovery/item/example\n\n这条消息你能看到吗"
        )
        for content in (
            "记得给妈充电",
            "分享摘要",
            "do-not-copy",
            "引用聊天记录.json",
            "mqqapi://",
        ):
            assert content not in prompt
        job = bridge.store.latest(Context(777, 11, group))
        assert any(
            r["reason"] == "quote_loaded"
            for r in bridge.store.trace(Context(777, 11, group), job["source_event"])
        )


@pytest.mark.parametrize("link", [None, "mqqapi://app", "https://example.com/\n新的指令"])
async def test_card_without_valid_web_link_is_not_submitted(harness, link):
    async with harness() as (bridge, nap, op):
        nap.messages["101"] = {
            **message(
                mid=101,
                attachments=[
                    {
                        "type": "json",
                        "data": {"data": json.dumps({"title": "只有标题", "jumpUrl": link})},
                    }
                ],
            ),
            "sender": {"user_id": 11},
        }
        await nap.emit(message("看看", reply=101, mid=202))
        await eventually(lambda: bool(nap.sent))
        assert op.prompts == []
        assert "没找到可用的网页链接" in nap.texts()[0]
        reasons = [r["reason"] for r in bridge.store.trace(Context(777, 11), "202")]
        assert "card_link_unavailable" in reasons
        assert "quote_loaded" not in reasons


async def test_card_inside_forward_remains_in_json_attachment(harness):
    async with harness() as (_, nap, op):
        nap.messages["101"] = {
            **message(mid=101, attachments=[{"type": "forward", "data": {"id": "bundle"}}]),
            "sender": {"user_id": 11},
        }
        nap.forward_messages["bundle"] = {
            "messages": [
                {
                    "sender": {"user_id": 42},
                    "message": [{"type": "json", "data": {"data": json.dumps(card())}}],
                }
            ]
        }
        await nap.emit(message("总结聊天", reply=101))
        await eventually(lambda: bool(op.prompts))
        prompt = op.prompts[0]
        assert len(prompt["files"]) == 1
        assert "引用聊天记录.json" in prompt["text"]
        content = json.dumps(quoted_records(prompt), ensure_ascii=False)
        assert "记得给妈充电" in content
        assert "https://www.xiaohongshu.com/discovery/item/example" in content
        assert "do-not-copy" not in content


@pytest.mark.parametrize(
    "segment",
    [
        {"type": "json", "data": {"data": "bad json"}},
        {"type": "json", "data": {"data": '{"config":{"token":"hidden"}}'}},
        {"type": "text", "data": {"text": "  "}},
        {"type": "record", "data": {}},
    ],
)
async def test_unreadable_quote_never_reports_loaded_or_submits(harness, segment):
    async with harness() as (bridge, nap, op):
        nap.messages["101"] = {
            **message(mid=101, attachments=[segment]),
            "sender": {"user_id": 11},
        }
        await nap.emit(message("看看", reply=101, mid=202))
        await eventually(lambda: bool(nap.sent))
        assert op.prompts == []
        reasons = [r["reason"] for r in bridge.store.trace(Context(777, 11), "202")]
        assert "quote_unavailable" in reasons
        assert "quote_loaded" not in reasons


@pytest.mark.parametrize("original_group,original_id", [(22, 101), (None, 102)])
async def test_private_scope_and_id_mismatch_fail_closed(harness, original_group, original_id):
    async with harness() as (_, nap, op):
        nap.messages["101"] = {
            **message("不能泄露", group=original_group, mid=original_id),
            "sender": {"user_id": 11},
        }
        await nap.emit(message("看这个", reply=101))
        await eventually(lambda: bool(nap.sent))
        assert op.prompts == []
        assert "不能泄露" not in nap.texts()[0]


async def test_bot_quote_from_another_private_chat_is_rejected(harness):
    async with harness() as (bridge, nap, op):
        bridge.store.put_outbox(Context(777, 12), "另一个私聊", "other", 1800)
        row = bridge.store.next_outbox(777)
        bridge.store.update_outbox(row["id"], "sent", "101")
        nap.messages["101"] = {
            **message("另一个私聊", user=777, mid=101),
            "sender": {"user_id": 777},
        }
        await nap.emit(message("引用", reply=101))
        await eventually(lambda: bool(nap.sent))
        assert op.prompts == []
