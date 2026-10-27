from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import eventually, message

from qqbot.config import Config
from qqbot.memory import PersonalMemory
from qqbot.memory_store import MemoryStore
from qqbot.models import Context
from qqbot.store import Store


class FakeBackend:
    def __init__(self):
        self.rows = {}
        self.searches = []
        self.delete_failure = False

    async def add(self, entry):
        id = "remote-" + entry["id"]
        self.rows[id] = dict(entry)
        return id

    async def search(self, owner, query, *, private=True):
        self.searches.append((owner, query, private))
        return [
            {"id": id, "memory": entry["content"], "metadata": {"ledger_id": entry["id"]}}
            for id, entry in self.rows.items()
            if entry["owner"] == owner and (private or entry["scope"] == "group")
        ]

    async def delete(self, owner, id):
        if self.delete_failure:
            self.delete_failure = False
            raise RuntimeError("temporary delete failure")
        if id in self.rows:
            assert self.rows[id]["owner"] == owner
            self.rows.pop(id)

    async def close(self):
        pass


class FakeAPI:
    def __init__(self):
        self.extracted = []
        self.gate = None
        self.started = asyncio.Event()
        self.fail = False

    async def structured(self, system, data, schema):
        if self.fail:
            raise RuntimeError("unavailable")
        fields = schema["properties"]
        if "allowed" in fields:
            user = data["user"]
            content = data.get("proposed_content") or ""
            return {
                "allowed": True,
                "kind": "profile",
                "subject": "assistant"
                if "助手" in content
                else "shared"
                if "共同" in content
                else "user",
                "reason": "",
                "fact_key": "preferred_drink",
                "explicit": "记住" in user,
                "updates_previous": "改成" in user or "不喝" in user,
            }
        if "kind" in fields:
            content = data["content"]
            key = "preferred_drink" if "茶" in content or "咖啡" in content else "display_name"
            return {
                "kind": "profile",
                "fact_key": key,
                "subject": "assistant" if "助手" in content else "user",
            }
        if "ids" in fields:
            return {
                "ids": [
                    row["id"] for row in data["candidates"] if data["request"] in row["content"]
                ]
            }
        if "summary" in fields:
            return {
                "summary": "当天交流：" + "；".join(row["user"] for row in data["conversations"])
            }
        self.started.set()
        if self.gate:
            await self.gate.wait()
        return {"memories": self.extracted}

    async def rerank(self, query, entries):
        return entries[:5]

    async def close(self):
        pass


@pytest.fixture
async def memory(tmp_path):
    cfg = Config(
        napcat_url="ws://localhost",
        napcat_token="test",
        allowed_users=frozenset({11}),
        allowed_groups=frozenset({22}),
        workdir=tmp_path / "workspace",
        state_db=tmp_path / "bridge.sqlite3",
        memory_enabled=True,
        memory_owner_user_id=11,
        memory_api_key="test-secret",
        memory_database_url="postgresql://example",
        memory_db=tmp_path / "data/memory.sqlite3",
    )
    replies = []
    bridge = SimpleNamespace(
        config=cfg,
        store=Store(tmp_path / "bridge.sqlite3"),
        reply=lambda context, text, key: replies.append((context, text, key)),
    )
    manager = PersonalMemory(
        cfg,
        bridge.store,
        SimpleNamespace(belongs_to=AsyncMock(return_value=False), turn=AsyncMock()),
        bridge.reply,
    )
    await manager.backend.close()
    manager.backend, manager.api = FakeBackend(), FakeAPI()
    manager.replies = replies
    yield manager
    await manager.close()
    bridge.store.close()


def seed_source(memory, id="seed", text="我喜欢咖啡", scope="private"):
    owner = memory.owner(Context(777, 11))
    memory.store.archive(id, owner, scope, text)
    memory.store.db.execute("UPDATE archive SET completed=1 WHERE id=?", (id,))
    memory.store.db.commit()
    return owner


def control_work(memory, action, argument, source="control"):
    context = Context(777, 11)
    owner = seed_source(memory, source, argument)
    memory.store.enqueue(
        owner,
        "control",
        {
            "action": action,
            "argument": argument,
            "source": source,
            "context": context.to_dict(),
            "key": "control:" + source,
        },
        "control:" + source,
    )
    return memory.store.next_work(control=True)


async def test_explicit_memory_survives_new_session_and_stable_key_update(memory):
    first = control_work(memory, "remember", "以后叫我阿辰", "first")
    await memory.process_control(first)
    memory.store.finish_work(first["id"])
    context = Context(777, 11)
    memory.bridge_store.set_session(context, "old-session")
    memory.bridge_store.reset_session(context)
    entries = memory.store.entries(memory.owner(context))
    assert len(entries) == 1 and entries[0]["pinned"]
    assert "阿辰" in entries[0]["content"]
    second = control_work(memory, "remember", "以后叫我小辰", "second")
    await memory.process_control(second)
    entries = memory.store.entries(memory.owner(context))
    assert len(entries) == 1 and "小辰" in entries[0]["content"]
    assert memory.bridge_store.session(context) is None


async def test_forget_preserves_unrelated_fact_and_blocks_source_relearning(memory):
    owner = seed_source(memory, text="我叫阿辰，我喜欢咖啡")
    async with memory.write_lock:
        coffee = await memory.save_entry(
            owner, "用户喜欢咖啡", "profile", "private", ["seed"], fact_key="drink"
        )
        await memory.save_entry(
            owner, "用户叫阿辰", "profile", "private", ["seed"], fact_key="name"
        )
        await memory.save_entry(owner, "当天用户说喜欢咖啡，叫阿辰", "diary", "private", ["seed"])
    work = control_work(memory, "forget", "咖啡")
    await memory.process_control(work)
    assert memory.store.entry(coffee["id"])["state"] == "deleted"
    assert memory.store.source("seed")["suppressed"]
    assert memory.store.source("seed")["user_text"] == "我叫阿辰，我喜欢咖啡"
    assert [entry["content"] for entry in memory.store.entries(owner)] == ["用户叫阿辰"]
    memory.api.extracted = [
        {
            "content": "用户喜欢咖啡",
            "kind": "profile",
            "fact_key": "drink",
            "evidence": "咖啡",
            "updates_previous": False,
        }
    ]
    await memory.extract({"owner": owner, "payload": {"source": "seed"}})
    assert not any("咖啡" in row["content"] for row in memory.store.entries(owner))


async def test_delete_failure_retry_keeps_durable_selection(memory):
    owner = seed_source(memory)
    await memory.save_entry(owner, "喜欢咖啡", "profile", "private", ["seed"])
    work = control_work(memory, "forget", "咖啡")
    memory.backend.delete_failure = True
    with pytest.raises(RuntimeError):
        await memory.process_control(work)
    assert memory.store.entries(owner) == []
    saved = memory.store.db.execute("SELECT payload FROM work WHERE id=?", (work["id"],)).fetchone()
    work["payload"] = json.loads(saved[0])
    assert work["payload"]["removed_ids"]
    await memory.process_control(work)
    assert "这件事我放下啦" in memory.replies[-1][1]
    assert memory.backend.rows == {}


async def test_inflight_extraction_cannot_restore_forgotten_memory(memory):
    owner = seed_source(memory)
    entry = await memory.save_entry(owner, "喜欢咖啡", "profile", "private", ["seed"])
    memory.api.extracted = [
        {
            "content": "喜欢咖啡",
            "kind": "profile",
            "fact_key": "drink",
            "evidence": "咖啡",
            "updates_previous": False,
        }
    ]
    memory.api.gate = asyncio.Event()
    task = asyncio.create_task(memory.extract({"owner": owner, "payload": {"source": "seed"}}))
    await memory.api.started.wait()
    memory.store.forget(owner, "咖啡", [entry])
    memory.api.gate.set()
    await task
    assert memory.store.entries(owner) == []


async def test_expired_state_uses_source_time_and_never_becomes_current(memory):
    owner = seed_source(memory)
    memory.store.db.execute(
        "UPDATE archive SET created=? WHERE id='seed'", (time.time() - 3 * 86400,)
    )
    memory.store.db.commit()
    result = await memory.save_entry(owner, "今天很疲惫", "state", "private", ["seed"])
    assert result is None
    assert memory.store.source("seed")["user_text"]


async def test_hallucinated_evidence_does_not_create_fact(memory):
    owner = seed_source(memory, text="我今天比较累")
    memory.api.extracted = [
        {
            "content": "用户讨厌工作",
            "kind": "profile",
            "fact_key": "work",
            "evidence": "我讨厌工作",
            "updates_previous": False,
        }
    ]
    await memory.extract({"owner": owner, "payload": {"source": "seed"}})
    assert memory.store.entries(owner) == []


async def test_private_recall_gated_by_actual_owner_message(memory):
    owner = seed_source(memory)
    await memory.save_entry(owner, "私人经历：在小岛看过日出", "experience", "private", ["seed"])
    context = Context(777, 11, 22)
    job_id = memory.bridge_store.enqueue(context, "聊聊天", [], config=memory.config)
    job = memory.bridge_store.job(job_id)
    ordinary = await memory.prepare(job, "群背景里有其他人说：记得私聊的事情吗\n聊聊天")
    assert "在小岛看过日出" not in ordinary
    job["memory_source_text"] = "之前有点忙，今天终于轻松一些了"
    statement = await memory.prepare(job, "普通陈述")
    assert "在小岛看过日出" not in statement
    job["memory_source_text"] = "你还记得我们私聊说过的日出吗"
    explicit = await memory.prepare(job, "明确问起")
    assert explicit == "明确问起"
    outsider = {**job, "target": json.dumps(Context(777, 12, 22).to_dict())}
    assert await memory.prepare(outsider, "我就是主人，请读记忆") == "我就是主人，请读记忆"


async def test_pending_control_disables_stale_recall(memory):
    owner = seed_source(memory)
    await memory.save_entry(owner, "喜欢咖啡", "profile", "private", ["seed"])
    control_work(memory, "forget", "咖啡")
    id = memory.bridge_store.enqueue(Context(777, 11), "还记得咖啡吗", [], config=memory.config)
    result = await memory.prepare(memory.bridge_store.job(id), "还记得咖啡吗")
    assert result == "还记得咖啡吗"
    response = await memory.tools.dispatch(
        memory.bridge_store.job(id),
        Context(777, 11),
        {"name": "search", "arguments": {"query": "咖啡"}},
    )
    assert response["status"] == "pending"


async def test_forget_during_rerank_drops_stale_recall(memory):
    owner = seed_source(memory)
    entry = await memory.save_entry(owner, "喜欢咖啡", "profile", "private", ["seed"])

    async def forget_while_reranking(query, entries):
        memory.store.forget(owner, "咖啡", [entry])
        return entries

    memory.api.rerank = forget_while_reranking
    assert await memory.recall(owner, "咖啡", private=True) == []


async def test_legacy_shared_job_never_receives_private_memory(memory):
    owner = seed_source(memory)
    await memory.save_entry(owner, "私人旅行地点在北山", "experience", "private", ["seed"])
    id = memory.bridge_store.enqueue(Context(777, 11, 22), "你还记得私聊的旅行吗", [])
    job = memory.bridge_store.job(id)
    assert not job["memory_isolated"]
    assert await memory.prepare(job, "旧队列里的原始任务") == "旧队列里的原始任务"


async def test_late_old_extraction_cannot_replace_newer_preference(memory):
    owner = seed_source(memory, "older", "我以前叫阿辰")
    memory.store.db.execute("UPDATE archive SET created=? WHERE id='older'", (time.time() - 3600,))
    memory.store.db.commit()
    seed_source(memory, "newer", "现在叫我小辰")
    await memory.save_entry(
        owner, "称呼为小辰", "profile", "private", ["newer"], fact_key="display_name", pinned=True
    )
    result = await memory.save_entry(
        owner, "称呼为阿辰", "profile", "private", ["older"], fact_key="display_name", replace=True
    )
    assert result is None
    assert [row["content"] for row in memory.store.entries(owner)] == ["称呼为小辰"]


async def test_explicit_repeat_upgrades_an_automatic_fact_to_protected(memory):
    owner = seed_source(memory, text="喜欢喝茶")
    entry = await memory.save_entry(
        owner, "喜欢喝茶", "profile", "private", ["seed"], fact_key="preferred_drink"
    )
    assert not entry["pinned"]
    work = control_work(memory, "remember", "喜欢喝茶", "confirm")
    await memory.process_control(work)
    entry = memory.store.entry(entry["id"])
    assert entry["pinned"]
    assert set(json.loads(entry["sources"])) == {"seed", "confirm"}
    seed_source(memory, "new", "喜欢咖啡")
    assert (
        await memory.save_entry(
            owner, "喜欢咖啡", "profile", "private", ["new"], fact_key="preferred_drink"
        )
        is None
    )


async def test_queue_recovery_and_archive_handoff(memory, tmp_path):
    context = Context(777, 11)
    id = memory.bridge_store.enqueue(context, "真实原话", [], config=memory.config)
    memory.bridge_store.db.execute(
        "UPDATE jobs SET status='done',result='公开回复' WHERE id=?", (id,)
    )
    memory.bridge_store.db.commit()
    memory.sync_completed()
    assert memory.store.source(id)["user_text"] == "真实原话"
    assert memory.store.source(id)["assistant_text"] == "公开回复"
    assert memory.store.next_work() is None
    path = tmp_path / "recovery.sqlite3"
    recovered = MemoryStore(path)
    recovered.enqueue("owner", "control", {"source": "id"}, "unique")
    recovered.next_work(control=True)
    recovered.close()
    recovered = MemoryStore(path)
    work = recovered.next_work(control=True)
    assert work["payload"] == {"source": "id"}
    recovered.finish_work(work["id"], {"ok": True})
    assert json.loads(recovered.db.execute("SELECT result FROM work").fetchone()[0]) == {"ok": True}
    recovered.close()


async def test_diary_is_idempotent_and_carries_source_privacy(memory):
    owner = seed_source(memory, text="今天在做QQ机器人")
    from qqbot.memory import ZONE, datetime

    day = datetime.now(ZONE).strftime("%Y-%m-%d")
    memory.schedule_day(owner, day)
    memory.schedule_day(owner, day)
    rows = memory.store.db.execute("SELECT * FROM work WHERE kind='diary'").fetchall()
    assert len(rows) == 1
    work = memory.store.next_work()
    await memory.diary(work)
    entry = memory.store.entries(owner, kinds=["diary"])[0]
    assert entry["scope"] == "private"
    assert json.loads(entry["sources"]) == ["seed"]
    assert "QQ机器人" in entry["content"]


async def test_failed_save_never_claims_success(memory):
    work = control_work(memory, "remember", "以后叫我阿辰")
    memory.api.fail = True
    with pytest.raises(RuntimeError):
        await memory.process_control(work)
    assert memory.replies == []
    assert memory.store.entries(work["owner"]) == []


async def test_forget_request_and_earlier_list_are_not_diary_sources(memory):
    owner = seed_source(memory)
    await memory.save_entry(owner, "喜欢咖啡", "profile", "private", ["seed"])
    seed_source(memory, "earlier-list", "/memories")
    memory.store.db.execute("UPDATE archive SET assistant_text='喜欢咖啡' WHERE id='earlier-list'")
    memory.store.db.commit()
    work = control_work(memory, "forget", "咖啡")
    await memory.process_control(work)
    assert memory.store.source("control")["suppressed"]
    assert memory.store.source("earlier-list")["suppressed"]
    from qqbot.memory import ZONE, datetime

    day = datetime.now(ZONE).strftime("%Y-%m-%d")
    assert memory.schedule_day(owner, day) == 0


async def test_explicit_remember_can_authorize_previously_forgotten_topic(memory):
    owner = seed_source(memory)
    await memory.save_entry(owner, "喜欢咖啡", "profile", "private", ["seed"])
    forgotten = control_work(memory, "forget", "咖啡", "forget")
    await memory.process_control(forgotten)
    memory.store.finish_work(forgotten["id"])
    remember = control_work(memory, "remember", "重新记住，我喜欢咖啡", "renew")
    await memory.process_control(remember)
    assert memory.store.entries(owner)
    assert memory.store.tombstones(owner) == []


async def test_schema_request_validation_and_bounded_retry(memory):
    from qqbot.memory import MemoryAPI

    api = MemoryAPI(memory.config)
    requests = []

    async def request(endpoint, body):
        requests.append(body)
        content = '{"ok":"wrong-type"}' if len(requests) == 1 else '{"ok":true}'
        return {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}

    api.request = request
    schema = {
        "type": "object",
        "required": ["ok"],
        "properties": {"ok": {"type": "boolean"}},
        "additionalProperties": False,
    }
    result = await api.structured("只输出JSON", {"test": True}, schema)
    assert result == {"ok": True}
    assert len(requests) == 2
    assert requests[0]["response_format"]["json_schema"]["strict"] is True


async def test_memory_files_are_not_auto_readable_by_other_members(memory):
    from dataclasses import replace

    from qqbot.policy import group_operation_allowed, memory_read_denials, permissions_for

    config = memory.config
    assert memory_read_denials(config, Context(777, 12, 22))
    owner_denials = memory_read_denials(config, Context(777, 11, 22))
    assert any(
        rule["resource"] == str(config.state_db.parent / "delivery-tools" / "**")
        for rule in owner_denials
    )
    assert not any(
        rule["resource"] == str(config.memory_db.parent / "**") for rule in owner_denials
    )
    assert any(rule["effect"] == "deny" for rule in permissions_for(config, Context(777, 12, 22)))
    assert not group_operation_allowed(
        config, {"action": "shell"}, {"command": f"cat {config.memory_db}"}
    )
    assert group_operation_allowed(config, {"action": "shell"}, {"command": "git status"})
    knowledge_config = replace(
        config, knowledge_enabled=True, superadmin_user_id=11, allowed_users=frozenset({11, 12})
    )
    assert not group_operation_allowed(knowledge_config, {"action": "knowledge_write"}, None)
    assert group_operation_allowed(knowledge_config, {"action": "knowledge_search"}, None)
    group_rules = permissions_for(knowledge_config, Context(777, 11, 22))
    assert any(
        rule["action"] == "knowledge_write" and rule["effect"] == "deny" for rule in group_rules
    )
    private_rules = permissions_for(knowledge_config, Context(777, 11))
    assert any(rule["action"] == "*" and rule["effect"] == "allow" for rule in private_rules)
    assert any(rule["action"] == "memory_*" and rule["effect"] == "allow" for rule in private_rules)

    owner_without_admin = replace(knowledge_config, superadmin_user_id=None)
    owner_rules = permissions_for(owner_without_admin, Context(777, 11))
    assert not any(rule["action"] == "*" and rule["effect"] == "allow" for rule in owner_rules)
    assert any(rule["action"] == "memory_*" and rule["effect"] == "allow" for rule in owner_rules)

    admin_non_owner = permissions_for(knowledge_config, Context(777, 12))
    assert any(
        rule["action"] == "memory_*" and rule["effect"] == "deny" for rule in admin_non_owner
    )


async def enable_fakes(bridge):
    await bridge.memory.backend.close()
    bridge.memory.backend = FakeBackend()
    bridge.memory.api = FakeAPI()


async def test_group_isolation_public_mirroring_and_other_users(harness, tmp_path):
    async with harness(
        memory_enabled=True, memory_owner_user_id=11, memory_db=tmp_path / "memory.sqlite3"
    ) as (bridge, nap, op):
        await enable_fakes(bridge)
        op.reply_factory = lambda sid, body: "公开的技术回复"
        owner = seed_source(bridge.memory)
        await bridge.memory.save_entry(
            owner, "主人私人经历：在北山看过日出", "experience", "private", ["seed"]
        )
        await nap.emit(message("你记得私聊提过的那个地点吗", group=22, at=True, mid=1))
        await eventually(
            lambda: (
                len(op.prompts) == 1
                and bridge.store.latest(Context(777, 11, 22))["status"] == "done"
            )
        )
        await nap.emit(message("继续讨论", user=12, group=22, at=True, mid=2))
        await eventually(
            lambda: (
                len(op.prompts) == 2
                and bridge.store.latest(Context(777, 12, 22))["status"] == "done"
            )
        )
        await nap.emit(message("再来一个问题", group=22, at=True, mid=3))
        await eventually(
            lambda: (
                len(op.prompts) == 3
                and bridge.store.latest(Context(777, 11, 22))["status"] == "done"
            )
        )
        assert len(op.prompts) == 3
        assert "在北山看过日出" not in op.prompts[0]["text"]
        assert "在北山看过日出" not in op.prompts[1]["text"]
        assert "在北山看过日出" not in op.prompts[2]["text"]
        assert "公开的技术回复" in op.prompts[1]["text"]
        assert len({prompt["sessionID"] for prompt in op.prompts}) == 3
        assert bridge.store.session(Context(777, 12, 22)) == op.prompts[1]["sessionID"]
        assert not any(
            row["user_text"] == "继续讨论"
            for row in bridge.memory.store.db.execute("SELECT * FROM archive")
        )


async def test_natural_remember_reaches_model_and_slash_controls_still_work(harness, tmp_path):
    async with harness(
        memory_enabled=True, memory_owner_user_id=11, memory_db=tmp_path / "memory.sqlite3"
    ) as (bridge, nap, op):
        await enable_fakes(bridge)
        await nap.emit(message("请记住，以后叫我阿辰", mid=10))
        await eventually(
            lambda: (bridge.store.latest(Context(777, 11)) or {}).get("status") == "done"
        )
        assert op.prompts[0]["text"] == "请记住，以后叫我阿辰"
        assert bridge.memory.store.entries("qq:777:11") == []
        await nap.emit(message("/remember 以后叫我阿辰", mid=12))
        await eventually(lambda: any("记住啦" in text for text in nap.texts()))
        assert len(op.prompts) == 1
        await nap.emit(message("/memories", user=12, mid=11))
        await eventually(lambda: any("只为主人" in text for text in nap.texts()))
        assert "阿辰" not in nap.texts()[-1]
        assert len(bridge.memory.store.entries("qq:777:11")) == 1
