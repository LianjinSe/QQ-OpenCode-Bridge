from __future__ import annotations

import json
import sqlite3
from unittest.mock import AsyncMock

from test_memory import memory as memory
from test_memory_tools import running_job
from test_memory_tools import service as service

from qqbot.memory_evidence import redact_evidence
from qqbot.memory_store import MemoryStore


def completed_exchange(memory, text="为助手开通邮箱", *, user=11, group=None, output=None):
    job, context = running_job(memory, text, user=user, group=group)
    memory.bridge_store.update_job(job["id"], status="done", result="操作结束")
    memory.bridge_store.db.execute("UPDATE jobs SET admitted=1 WHERE id=?", (job["id"],))
    memory.bridge_store.db.commit()
    if memory.owns(context):
        memory.store.complete(job["id"], "助手说操作结束了")
    part = {
        "type": "tool",
        "id": "tool_mail",
        "name": "execute",
        "state": {
            "status": "completed",
            "metadata": {"exit": 0},
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        output or {"ok": True, "mailbox": "assistant@example.invalid"},
                        ensure_ascii=False,
                    ),
                }
            ],
        },
    }
    memory.opencode.turn = AsyncMock(
        return_value=(
            None,
            [
                {"id": "msg_mail", "type": "assistant", "content": [part]},
            ],
        )
    )
    return memory.bridge_store.job(job["id"]), context


def validator(memory, *, subject, kind="experience", allowed=True, reason=""):
    async def validate(system, data, schema):
        return {
            "allowed": allowed,
            "reason": reason,
            "subject": subject,
            "kind": kind,
            "fact_key": "",
            "explicit": "记住" in data["user"],
            "updates_previous": False,
        }

    memory.api.structured = AsyncMock(side_effect=validate)


async def test_user_confirmed_assistant_profile_and_user_preferences_stay_separate(service):
    memory, call = service
    owner = "qq:777:11"
    first, _ = running_job(memory, "记住我喜欢咖啡")
    assert (await call(first, "remember", {"content": "用户喜欢咖啡", "evidence": "我喜欢咖啡"}))[
        1
    ]["ok"]
    second, _ = running_job(memory, "记住助手喜欢喝茶")
    result = (
        await call(second, "remember", {"content": "助手喜欢喝茶", "evidence": "助手喜欢喝茶"})
    )[1]
    assert result["ok"] and result["memory"]["subject"] == "assistant"
    rows = memory.store.entries(owner)
    assert {row["subject"] for row in rows} == {"user", "assistant"}
    assert all(row["fact_key"] == "preferred_drink" for row in rows)
    assert {row["content"] for row in rows} == {"用户喜欢咖啡", "助手喜欢喝茶"}


async def test_historical_tool_proof_can_support_shared_memory_and_is_traceable(service):
    memory, call = service
    origin, _ = completed_exchange(memory)
    current, _ = running_job(memory, "记住我们今天开通邮箱的事")
    _, found = await call(current, "evidence", {"query": "邮箱", "source_ids": [origin["id"]]})
    proof = next(row for row in found["evidence"] if row["kind"] == "tool")
    assert proof["tool"] == "execute"
    validator(memory, subject="shared")
    args = {
        "content": "共同开通了邮箱 assistant@example.invalid",
        "evidence": "assistant@example.invalid",
        "evidence_ids": [proof["id"]],
    }
    _, result = await call(current, "remember", args)
    assert result["ok"] and result["memory"]["subject"] == "shared"
    entry = memory.store.entry(result["memory"]["id"])
    assert set(json.loads(entry["sources"])) == {origin["id"], current["id"]}
    assert json.loads(entry["evidence"]) == [proof["id"]]
    assert memory.store.db.execute(
        "SELECT used FROM memory_evidence WHERE id=?", (proof["id"],)
    ).fetchone()[0]
    memory.store.forget("qq:777:11", "邮箱", [entry])
    assert memory.tools.evidence.resolve([proof["id"]], current["id"], "qq:777:11", True) is None


async def test_saved_proof_survives_history_unavailability_and_purge_removes_excerpt(service):
    memory, call = service
    origin, _ = completed_exchange(memory)
    current, context = running_job(memory, "记住我们开通邮箱的事")
    _, found = await call(current, "evidence", {"query": "邮箱", "source_ids": [origin["id"]]})
    proof = next(row for row in found["evidence"] if row["kind"] == "tool")
    validator(memory, subject="shared")
    _, saved = await call(
        current,
        "remember",
        {
            "content": "共同开通邮箱 assistant@example.invalid",
            "evidence": "assistant@example.invalid",
            "evidence_ids": [proof["id"]],
        },
    )
    memory.opencode.turn.side_effect = RuntimeError("history unavailable")
    later, _ = running_job(memory, "查查之前的邮箱")
    _, recalled = await call(later, "evidence", {"query": "邮箱", "source_ids": [origin["id"]]})
    assert recalled["partial"]
    assert any(
        row["kind"] == "tool" and "assistant@example.invalid" in row["text"]
        for row in recalled["evidence"]
    )
    payload = {
        "action": "purge",
        "argument": "邮箱",
        "selected_ids": [saved["memory"]["id"]],
        "source": later["id"],
        "context": context.to_dict(),
        "key": "purge-test",
    }
    memory.store.enqueue("qq:777:11", "control", payload, "purge-test")
    work = memory.store.next_work(control=True)
    await memory.process_control(work)
    assert (
        memory.store.db.execute(
            "SELECT excerpt FROM memory_evidence WHERE id=?", (proof["id"],)
        ).fetchone()[0]
        == ""
    )


async def test_forgetting_assistant_preference_does_not_block_user_same_preference(service):
    memory, call = service
    one, _ = running_job(memory, "我喜欢茶")
    user = await memory.save_entry(
        "qq:777:11", "喜欢茶", "profile", "private", [one["id"]], subject="user"
    )
    two, _ = running_job(memory, "助手喜欢茶")
    assistant = await memory.save_entry(
        "qq:777:11", "喜欢茶", "profile", "private", [two["id"]], subject="assistant"
    )
    memory.store.forget("qq:777:11", "喜欢茶", [assistant])
    current, _ = running_job(memory, "我喜欢茶")
    _, result = await call(current, "remember", {"content": "喜欢茶", "evidence": "我喜欢茶"})
    assert result["ok"] and result["memory"]["id"] == user["id"]


async def test_learned_methods_accept_reference_proof_without_claiming_execution(service):
    memory, call = service
    origin, _ = completed_exchange(
        memory,
        "学习邮件接口文档",
        output={"method": "POST /mail/send", "note": "202表示已接受，并不证明投递完成"},
    )
    current, _ = running_job(memory, "保存你刚学到的方法")
    _, found = await call(current, "evidence", {"query": "邮件", "source_ids": [origin["id"]]})
    proof = next(row for row in found["evidence"] if row["kind"] == "tool")
    validator(memory, subject="assistant", kind="knowledge")
    _, result = await call(
        current,
        "remember",
        {
            "content": "邮件方法：POST /mail/send；202只表示接受，实际投递尚未验证",
            "evidence": "POST /mail/send",
            "evidence_ids": [proof["id"]],
        },
    )
    assert result["ok"] and result["memory"]["kind"] == "knowledge"
    assert result["memory"]["subject"] == "assistant"


async def test_evidence_cannot_cross_owner_job_or_private_visibility(service):
    memory, call = service
    origin, _ = completed_exchange(memory)
    current, _ = running_job(memory, "记住今天的邮箱")
    _, found = await call(current, "evidence", {"query": "邮箱", "source_ids": [origin["id"]]})
    proof = next(row for row in found["evidence"] if row["kind"] == "tool")
    next_job, _ = running_job(memory, "记住邮箱")
    args = {"content": "助手邮箱", "evidence": "记住邮箱", "evidence_ids": [proof["id"]]}
    assert (await call(next_job, "remember", args))[1]["status"] == "invalid_evidence"
    group, _ = running_job(memory, "群里聊聊天", group=22)
    _, result = await call(group, "evidence", {"query": "邮箱", "source_ids": [origin["id"]]})
    assert all(row["source_id"] != origin["id"] for row in result["evidence"])
    outsider, _ = completed_exchange(memory, "私人邮箱", user=12)
    _, result = await call(current, "evidence", {"query": "邮箱", "source_ids": [outsider["id"]]})
    assert all(row["source_id"] != outsider["id"] for row in result["evidence"])


async def test_private_proof_keeps_shared_memory_private_even_from_group(service):
    memory, call = service
    origin, _ = completed_exchange(memory)
    current, _ = running_job(memory, "你记得私聊说过的邮箱吗？记住这件事", group=22)
    _, found = await call(current, "evidence", {"query": "邮箱", "source_ids": [origin["id"]]})
    proof = next(row for row in found["evidence"] if row["kind"] == "tool")
    validator(memory, subject="shared")
    _, result = await call(
        current,
        "remember",
        {
            "content": "共同开通 assistant@example.invalid",
            "evidence": "assistant@example.invalid",
            "evidence_ids": [proof["id"]],
        },
    )
    assert result["ok"]
    assert memory.store.entry(result["memory"]["id"])["scope"] == "private"


async def test_tools_from_later_turns_and_memory_results_are_not_operation_proof(service):
    memory, _ = service
    origin, _ = completed_exchange(memory)
    good = memory.opencode.turn.return_value[1][0]
    memory_tool = {
        "type": "assistant",
        "id": "msg_memory",
        "content": [
            {
                "type": "tool",
                "id": "memory_1",
                "name": "memory_search",
                "state": {"status": "completed", "content": [{"type": "text", "text": "recalled"}]},
            }
        ],
    }
    future = {
        "type": "assistant",
        "id": "msg_future",
        "content": [
            {
                "type": "tool",
                "id": "future_1",
                "name": "execute",
                "state": {"status": "completed", "content": [{"type": "text", "text": "future"}]},
            }
        ],
    }
    memory.opencode.turn.return_value = (
        None,
        [good, memory_tool, {"type": "user", "id": "next_turn"}, future],
    )
    records = await memory.tools.evidence.tool_records(origin)
    assert len(records) == 1 and records[0][2]["tool_id"] == "tool_mail"


async def test_completed_private_steers_stay_in_original_execution_evidence(service):
    memory, _ = service
    root, context = running_job(memory, "处理邮件")
    steer = memory.bridge_store.enqueue(
        context, "再看看邮箱", [], config=memory.config, steer_parent_id=root["id"]
    )
    memory.bridge_store.update_job(steer, session_id=root["session_id"])
    memory.bridge_store.acknowledge(steer)
    memory.bridge_store.db.execute("UPDATE jobs SET admitted=1 WHERE id=?", (root["id"],))
    memory.bridge_store.db.commit()
    memory.bridge_store.update_job(root["id"], status="done")
    assert memory.bridge_store.job(steer)["status"] == "done"
    steer_message = {"type": "user", "id": memory.bridge_store.job(steer)["prompt_id"]}
    tool = {
        "type": "assistant",
        "id": "msg_steer_result",
        "content": [
            {
                "type": "tool",
                "id": "tool_after_steer",
                "name": "execute",
                "state": {"status": "completed", "content": [{"type": "text", "text": "邮箱结果"}]},
            }
        ],
    }
    memory.opencode.turn = AsyncMock(return_value=(None, [steer_message, tool]))
    records = await memory.tools.evidence.tool_records(memory.bridge_store.job(root["id"]))
    assert len(records) == 1 and records[0][2]["tool_id"] == "tool_after_steer"


async def test_failed_tools_are_failure_evidence_and_credentials_are_redacted(service):
    memory, call = service
    origin, _ = completed_exchange(
        memory,
        "测试邮箱",
        output={
            "ok": False,
            "error": "HTTP 401",
            "token": "PRIVATE-TOKEN",
            "authorization": "Bearer PRIVATE-AUTH",
        },
    )
    current, _ = running_job(memory, "总结邮箱失败经验")
    _, found = await call(current, "evidence", {"query": "邮箱", "source_ids": [origin["id"]]})
    proof = next(row for row in found["evidence"] if row["kind"] == "tool_error")
    assert "401" in proof["text"] and proof["status"] == "failed"
    assert "PRIVATE-TOKEN" not in json.dumps(found)
    assert "PRIVATE-AUTH" not in json.dumps(found)
    assert all(row["kind"] != "tool" for row in found["evidence"])
    validator(
        memory,
        subject="assistant",
        kind="knowledge",
        allowed=False,
        reason="只有401失败记录，不能证明成功发送",
    )
    _, rejected = await call(
        current,
        "remember",
        {"content": "助手已成功学会发邮件", "evidence": "401", "evidence_ids": [proof["id"]]},
    )
    assert rejected["status"] == "unsupported" and "401" in rejected["message"]


async def test_runtime_persona_can_support_assistant_profile(service, tmp_path):
    memory, call = service
    # Use an isolated workdir rather than reading the deployed persona in this unit test.
    from dataclasses import replace

    persona = tmp_path / "persona"
    persona.mkdir()
    (persona / "AGENTS.md").write_text("助手喜欢草莓蛋糕。角色设定不证明线下活动。")
    memory.config = replace(memory.config, workdir=persona)
    current, _ = running_job(memory, "记住自己的偏好")
    _, found = await call(current, "evidence", {"query": "草莓"})
    proof = next(row for row in found["evidence"] if row["kind"] == "persona")
    validator(memory, subject="assistant", kind="profile")
    _, saved = await call(
        current,
        "remember",
        {
            "content": "助手喜欢草莓蛋糕",
            "evidence": "助手喜欢草莓蛋糕",
            "evidence_ids": [proof["id"]],
        },
    )
    assert saved["ok"] and saved["memory"]["subject"] == "assistant"


def test_subject_migration_keeps_existing_data_and_is_repeatable(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    store = MemoryStore(path)
    store.prepare_entry("owner", "原有事实", "profile", "private", [], subject="assistant")
    store.close()
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE entries DROP COLUMN subject")
        db.execute("ALTER TABLE entries DROP COLUMN evidence")
    store = MemoryStore(path)
    row = store.db.execute("SELECT * FROM entries").fetchone()
    assert row["content"] == "原有事实" and row["subject"] == "user" and row["evidence"] == "[]"
    store.close()
    store = MemoryStore(path)
    assert store.db.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 1
    store.close()


def test_plain_text_credential_redaction():
    text = "token=PRIVATE-TOKEN\nAuthorization: Bearer PRIVATE-AUTH\n成功读取说明"
    redacted = redact_evidence(text)
    assert "PRIVATE-TOKEN" not in redacted and "PRIVATE-AUTH" not in redacted
    assert "成功读取说明" in redacted
