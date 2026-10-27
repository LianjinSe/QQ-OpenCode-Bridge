import asyncio

from conftest import eventually, message

from qqbot.models import Context


async def test_gscore_exclusions_are_silent_and_clear_staged_files(harness):
    async with harness() as (bridge, nap, op):
        upload = {
            "post_type": "notice",
            "notice_type": "group_upload",
            "self_id": 777,
            "user_id": 11,
            "group_id": 22,
            "time": 1,
            "file": {"id": "must-not-download", "name": "secret.txt", "size": 10},
        }
        await nap.emit(upload)
        for text in ["ww抽卡", "  mm帮助", "\nCodeX 修复", "WWtest", "codex"]:
            await nap.emit(
                message(
                    text,
                    group=22,
                    at=True,
                    attachments=[
                        {"type": "file", "data": {"file_id": "must-not-download", "name": "x.txt"}},
                    ],
                )
            )
        await nap.emit(message("  Mm 私聊"))
        await nap.emit(message("/status", group=22, at=True))
        await eventually(lambda: bool(nap.sent))
        assert len(nap.sent) == 1
        assert op.prompts == []
        assert bridge.store.staged(Context(777, 11, 22)) == []
        assert not any(a["action"] == "download_file_stream" for a in nap.actions)
        await nap.emit(message("解释 codex 的作用", group=22, at=True))
        await eventually(lambda: len(op.prompts) == 1)
        assert op.prompts[0]["files"] == []
        await eventually(lambda: any("回复：解释 codex 的作用" in t for t in nap.texts()))


async def test_allowlists_at_self_messages_and_duplicate_delivery(harness):
    async with harness() as (_, nap, op):
        await nap.emit(message("禁止", user=99))
        await nap.emit(message("禁止", group=99, at=True))
        await nap.emit(message("没有@", group=22))
        await nap.emit(message("机器人自己", user=777))
        duplicate = message("允许", user=99, group=22, at=True, mid=101)
        await nap.emit(duplicate)
        await nap.emit(duplicate)
        await eventually(lambda: bool(nap.sent))
        assert len(op.prompts) == 1
        assert op.prompts[0]["text"].endswith("允许")
        assert "没有@" in op.prompts[0]["text"]
        assert nap.sent[0]["group_id"] == "22"
        assert nap.sent[0]["message"][0] == {"type": "at", "data": {"qq": "99"}}
        assert "不应该被发送" not in "".join(nap.texts())


async def test_sessions_are_isolated_reused_and_reset(harness):
    async with harness() as (bridge, nap, op):
        contexts = [(11, None), (12, None), (11, 22), (12, 22), (11, 23)]
        for index, (user, group) in enumerate(contexts, 1):
            await nap.emit(message(f"任务{index}", user=user, group=group, at=bool(group)))
            await eventually(lambda index=index: len(nap.sent) >= index)
        assert len({p["sessionID"] for p in op.prompts}) == 4
        assert op.prompts[2]["sessionID"] == op.prompts[3]["sessionID"]
        first = op.prompts[0]["sessionID"]
        await nap.emit(message("继续"))
        await eventually(lambda: len(nap.sent) == 6)
        assert op.prompts[-1]["sessionID"] == first
        await nap.emit(message("/new"))
        await eventually(lambda: len(nap.sent) == 7)
        await nap.emit(message("新的上下文"))
        await eventually(lambda: len(nap.sent) == 8)
        assert op.prompts[-1]["sessionID"] != first
        assert bridge.store.session(Context(777, 11)) == op.prompts[-1]["sessionID"]


async def test_permission_owner_child_session_and_control_bypasses_queue(harness):
    async with harness(allowed_users=frozenset({11, 12, 31}), superadmin_user_id=31) as (
        bridge,
        nap,
        op,
    ):
        op.mode, op.permission_in_child = "permission", True
        await nap.emit(message("修改", group=22, at=True))
        await eventually(lambda: bool(nap.sent))
        job = bridge.store.latest(Context(777, 11, 22))
        pending = bridge.store.pending_for(job["id"])[0]
        code = pending["code"]
        await nap.emit(message(f"/approve {code}", user=12, group=22, at=True))
        await nap.emit(message(f"/approve {code}", user=11))
        await eventually(lambda: len(nap.sent) >= 3)
        assert op.decisions == []
        await nap.emit(message("排队任务", user=12, group=22, at=True))
        await nap.emit(message(f"/approve {code}", user=31, group=22))
        await eventually(lambda: bool(op.decisions))
        assert op.decisions[0][0].startswith("ses_child_")
        assert op.decisions[0][2] == "once"
        await eventually(lambda: len(op.prompts) == 2)
        # The other context only starts after the first root completes.
        assert bridge.store.job(job["id"])["status"] in {"done", "reply_ready"}
        second = bridge.store.latest(Context(777, 12, 22))
        await eventually(lambda: bool(bridge.store.pending_for(second["id"])))
        second_code = bridge.store.pending_for(second["id"])[0]["code"]
        await nap.emit(message(f"/reject {second_code}", user=31, group=22))
        await eventually(lambda: len(op.decisions) == 2)
        assert op.decisions[-1][2] == "reject"


async def test_form_fields_validated_and_collected_sequentially(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "form"
        await nap.emit(message("做任务"))
        await eventually(lambda: bool(nap.sent))
        job = bridge.store.latest(Context(777, 11))
        code = bridge.store.pending_for(job["id"])[0]["code"]
        await nap.emit(message(f"/answer {code} 99"))
        await eventually(lambda: any("有效的选项" in t for t in nap.texts()))
        assert op.answers == []
        await nap.emit(message(f"/answer {code} 1"))
        await eventually(lambda: any("运行测试" in t for t in nap.texts()))
        await nap.emit(message(f"/answer {code} 是"))
        await eventually(lambda: any("逗号分隔多个" in t for t in nap.texts()))
        await nap.emit(message(f"/answer {code} 1,2"))
        await eventually(lambda: bool(op.answers))
        assert op.answers[0] == {"language": "python", "tests": True, "targets": ["a", "b"]}
        await eventually(lambda: any("回复：做任务" in t for t in nap.texts()))


async def test_attachment_streams_native_binary_from_quoted_message(harness):
    async with harness() as (_, nap, op):
        nap.files = {
            "code": b"print('hello')\n",
            "image": b"\x89PNG\r\n\x1a\n" + b"x" * 70000,
            "binary": b"\x00\xff\x01",
        }
        await nap.emit(
            {
                "post_type": "notice",
                "notice_type": "group_upload",
                "self_id": 777,
                "user_id": 11,
                "group_id": 22,
                "time": 1,
                "file": {"id": "code", "name": "codex.py", "size": 15},
            }
        )
        await nap.emit(
            message(
                "",
                group=22,
                mid=201,
                attachments=[
                    {"type": "image", "data": {"file": "image"}},
                    {"type": "file", "data": {"file_id": "code", "name": "codex.py"}},
                    {"type": "file", "data": {"file_id": "binary", "name": "../../a.bin"}},
                ],
            )
        )
        await nap.emit(
            message(
                "分析这些附件",
                group=22,
                at=True,
                reply=201,
            )
        )
        await eventually(lambda: bool(op.prompts))
        prompt = op.prompts[0]
        assert len(prompt["files"]) == 3
        assert all(f["uri"].startswith("file:///") for f in prompt["files"])
        assert any("codex.py" in f["name"] for f in prompt["files"])
        assert any(f["name"].endswith("-a.bin") for f in prompt["files"])
        assert "聊天记录：" not in prompt["text"]
        assert prompt["text"].endswith("分析这些附件")
        assert len([a for a in nap.actions if a["action"] == "download_file_stream"]) == 3


async def test_size_count_and_corrupt_stream_fail_without_prompt(harness):
    async with harness(max_attachment_bytes=4) as (bridge, nap, op):
        nap.files["large"] = b"12345"
        await nap.emit(
            message(
                mid=301,
                attachments=[
                    {"type": "file", "data": {"file_id": "large", "name": "file.txt"}},
                ],
            )
        )
        await nap.emit(message("文件", reply=301))
        await eventually(lambda: bool(nap.sent))
        assert op.prompts == []
        assert bridge.store.latest(Context(777, 11))["status"] == "failed"
        assert "超过大小限制" in nap.texts()[-1]
        assert not list(bridge.config.workdir.rglob("*.part"))
        nap.files["small"] = b"x"
        nap.stream_fault = "order"
        await nap.emit(
            message(
                mid=302,
                attachments=[
                    {"type": "file", "data": {"file_id": "small", "name": "file.txt"}},
                ],
            )
        )
        await nap.emit(message("文件", reply=302))
        await eventually(lambda: len(nap.sent) == 2)
        assert op.prompts == []
        await nap.emit(
            message(
                mid=303,
                attachments=[
                    {"type": "file", "data": {"file_id": str(i), "name": "a"}}
                    for i in range(bridge.config.max_attachments + 1)
                ],
            )
        )
        await nap.emit(message("太多", reply=303))
        await eventually(lambda: len(nap.sent) == 3)
        assert "数量或总大小" in nap.texts()[-1]


async def test_cancel_clears_queue_and_new_requires_idle(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("长任务"))
        await eventually(lambda: len(op.prompts) == 1)
        await nap.emit(message("补充要求"))
        await eventually(lambda: len(op.prompts) == 2)
        assert nap.sent == []
        assert len(bridge.store.unfinished(Context(777, 11))) == 1
        assert op.interrupted == []
        await nap.emit(message("/new"))
        await eventually(lambda: any("先 /cancel" in text for text in nap.texts()))
        await nap.emit(message("/cancel"))
        await eventually(lambda: bool(op.interrupted))
        await eventually(lambda: bridge.store.unfinished(Context(777, 11)) == [])
        assert len(op.prompts) == 2
        assert bridge.store.latest(Context(777, 11))["status"] == "cancelled"
        root = bridge.store.latest(Context(777, 11))
        assert bridge.store.steers(root["id"])[0]["status"] == "cancelled"


async def test_lost_admission_response_does_not_resubmit(harness):
    async with harness() as (bridge, nap, op):
        op.lose_prompt_response = True
        await nap.emit(message("网络断开也只能提交一次"))
        await eventually(lambda: bool(nap.sent))
        assert len(op.prompts) == 1
        await eventually(lambda: bridge.store.latest(Context(777, 11))["status"] == "done")


async def test_long_reply_chunks_and_uncertain_delivery_not_retried(harness):
    async with harness(reply_chunk_size=20) as (bridge, nap, op):
        text = "很长的回复" * 10
        await nap.emit(message(text))
        await eventually(lambda: bridge.store.latest(Context(777, 11)) is not None)
        await eventually(lambda: bridge.store.latest(Context(777, 11))["status"] == "done")
        assert "".join(nap.texts()) == "回复：" + text
        assert all(len(text) <= 20 for text in nap.texts())
        nap.no_send_ack = True
        await nap.emit(message("结果不可确定"))
        await eventually(
            lambda: bridge.store.latest(Context(777, 11))["status"] == "send_uncertain"
        )
        previous = len(nap.sent)
        await asyncio.sleep(1.3)
        assert len(nap.sent) == previous
        assert len(op.prompts) == 2


async def test_timeouts_stop_execution_and_waiting(harness):
    async with harness(execution_timeout=0.15, interaction_timeout=0.2) as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("超时"))
        await eventually(lambda: bool(nap.sent))
        assert "执行超时" in nap.texts()[-1]
        assert bridge.store.latest(Context(777, 11))["status"] == "cancelled"
        op.mode = "permission"
        await nap.emit(message("等待批准"))
        await eventually(lambda: any("等你点头或回答等得有点久" in t for t in nap.texts()))
        assert op.decisions[-1][2] == "reject"
        assert bridge.store.latest(Context(777, 11))["status"] == "cancelled"


async def test_paginated_history_extracts_only_current_final_text(harness):
    async with harness() as (_, nap, op):
        op.page_size = 1
        await nap.emit(message("第一轮"))
        await eventually(lambda: len(nap.sent) == 1)
        await nap.emit(message("第二轮"))
        await eventually(lambda: len(nap.sent) == 2)
        assert nap.texts() == ["回复：第一轮", "回复：第二轮"]


async def test_model_failure_is_reported_as_failure_after_reply_delivery(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "failed"
        await nap.emit(message("模拟供应商失败"))
        await eventually(lambda: bool(nap.sent))
        await eventually(lambda: bridge.store.latest(Context(777, 11))["status"] == "failed")
        assert "还没做完" in nap.texts()[-1]
