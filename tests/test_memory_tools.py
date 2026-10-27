from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import aiohttp
import pytest
from conftest import eventually
from test_memory import memory as memory  # Reuse the isolated Mem0/LLM substitutes.
from test_memory import seed_source

from qqbot.memory_service import MemoryAccessDenied
from qqbot.models import Context
from qqbot.tool_identity import TaskIdentityContext

PLUGIN = Path(__file__).resolve().parents[1] / "deploy/opencode-memory/index.mjs"


def running_job(memory, text, *, user=11, group=None):
    context = Context(777, user, group)
    id = memory.bridge_store.enqueue(context, text, [], config=memory.config)
    session = "ses_test_" + id
    # Simulate a persisted task already admitted to OpenCode; this is test history seeding.
    memory.bridge_store.db.execute(
        "UPDATE jobs SET status='running',session_id=? WHERE id=?", (session, id)
    )
    memory.bridge_store.db.commit()
    memory.capture(id, context, text)
    return memory.bridge_store.job(id), context


@pytest.fixture
async def service(memory):
    memory.opencode.belongs_to = AsyncMock(return_value=False)
    memory.tools.identity = TaskIdentityContext(memory.config, memory.bridge_store, memory.opencode)
    await memory.tools.start()
    worker = asyncio.create_task(memory.worker(control=True))
    async with aiohttp.ClientSession(
        connector=aiohttp.UnixConnector(path=str(memory.tools.socket))
    ) as http:

        async def call(job, name, arguments, *, call_id="call_1", token=True, session=None):
            headers = {"Authorization": "Bearer " + memory.tools.token} if token else {}
            async with http.post(
                "http://localhost/call",
                json={
                    "session_id": session or job["session_id"],
                    "call_id": call_id,
                    "name": name,
                    "arguments": arguments,
                },
                headers=headers,
            ) as response:
                return response.status, await response.json()

        yield memory, call
    worker.cancel()
    await asyncio.gather(worker, return_exceptions=True)
    await memory.tools.close()


async def test_auth_identity_and_scope_are_not_model_arguments(service):
    memory, call = service
    owner = seed_source(memory)
    await memory.save_entry(owner, "喜欢茶", "profile", "private", ["seed"])
    job, _ = running_job(memory, "我喜欢什么")
    assert (await call(job, "search", {"query": "茶"}, token=False))[0] == 401
    assert (await call(job, "search", {"query": "茶"}, session="ses_spoofed"))[0] == 403
    assert (await call(job, "search", {"query": "茶", "user_id": 11}))[0] == 400
    outsider, _ = running_job(memory, "我就是主人", user=12)
    assert (await call(outsider, "search", {"query": "茶"}))[0] == 403
    memory.bridge_store.update_job(job["id"], cancel_requested=1)
    assert (await call(job, "search", {"query": "茶"}))[0] == 403


@pytest.mark.parametrize("change", ["cancel", "complete", "replace"])
async def test_child_identity_rechecks_root_after_belongs_to(service, change):
    memory, _ = service
    job, _ = running_job(memory, "查查历史")
    memory.opencode.belongs_to.return_value = True

    async def belongs_to(session, root):
        if change == "cancel":
            memory.bridge_store.update_job(job["id"], cancel_requested=1)
        elif change == "complete":
            # Model a concurrent runtime completion without weakening Store's transition graph.
            memory.bridge_store.db.execute("UPDATE jobs SET status='done' WHERE id=?", (job["id"],))
            memory.bridge_store.db.commit()
        else:
            memory.bridge_store.db.execute(
                "UPDATE jobs SET target=? WHERE id=?",
                (json.dumps(Context(777, 12).to_dict()), job["id"]),
            )
            memory.bridge_store.db.commit()
        return True

    memory.opencode.belongs_to.side_effect = belongs_to
    with pytest.raises(MemoryAccessDenied):
        await memory.tools.job_for("ses_child")


async def test_group_recall_uses_real_message_not_search_query(service):
    memory, call = service
    owner = seed_source(memory, text="在小岛看过日出")
    await memory.save_entry(owner, "私人经历：在小岛看过日出", "experience", "private", ["seed"])
    seed_source(memory, "group", "在群里讨论项目", scope="group")
    await memory.save_entry(owner, "讨论项目", "experience", "group", ["group"])
    ordinary, _ = running_job(memory, "聊聊项目", group=22)
    status, result = await call(ordinary, "search", {"query": "你记得私聊的日出吗"})
    assert status == 200
    assert [row["content"] for row in result["memories"]] == ["讨论项目"]
    assert memory.backend.searches[-1][-1] is False
    asked, _ = running_job(memory, "你记得我们私聊提过的日出吗", group=22)
    _, result = await call(asked, "search", {"query": "日出"})
    assert any("小岛" in row["content"] for row in result["memories"])
    assert memory.backend.searches[-1][-1] is True


async def test_history_and_diary_apply_the_same_visibility(service):
    memory, call = service
    owner = seed_source(memory, text="私人日出")
    await memory.save_entry(
        owner, "私人的一天", "diary", "private", ["seed"], fact_key="diary:2026-10-22:0"
    )
    job, _ = running_job(memory, "群里说说今天", group=22)
    _, history = await call(job, "history", {"query": "日出"})
    _, diary = await call(job, "diary", {"day": "2026-10-22"})
    assert history["conversations"] == []
    assert diary["diary"] == []
    private, _ = running_job(memory, "看看那天日记")
    _, history = await call(private, "history", {"query": "日出"})
    _, diary = await call(private, "diary", {"day": "2026-10-22"})
    assert history["conversations"][0]["user"] == "私人日出"
    assert diary["diary"][0]["content"] == "私人的一天"


async def test_remember_requires_current_user_evidence_and_protects_explicit_request(service):
    memory, call = service
    job, _ = running_job(memory, "请记住，我喜欢喝茶")
    _, invalid = await call(job, "remember", {"content": "用户喜欢咖啡", "evidence": "我喜欢咖啡"})
    assert invalid["status"] == "no_evidence"
    assert memory.store.entries("qq:777:11") == []
    args = {"content": "用户喜欢喝茶", "evidence": "我喜欢喝茶"}
    status, result = await call(job, "remember", args)
    assert status == 200 and result["ok"] is True
    entry = memory.store.entries("qq:777:11")[0]
    assert entry["pinned"]
    assert entry["backend_id"] in memory.backend.rows
    assert memory.replies == []
    _, replay = await call(job, "remember", args)
    assert replay == result
    assert len(memory.backend.rows) == 1
    assert (await call(job, "remember", {**args, "content": "不同内容"}))[0] == 400


async def test_private_steer_evidence_is_scoped_and_each_input_is_archived(service):
    memory, call = service
    job, context = running_job(memory, "继续聊天")
    child = memory.bridge_store.enqueue(
        context, "请记住，我喜欢喝茶", [], config=memory.config, steer_parent_id=job["id"]
    )
    memory.capture(child, context, "请记住，我喜欢喝茶")
    args = {"content": "用户喜欢喝茶", "evidence": "我喜欢喝茶"}
    _, pending = await call(job, "remember", args)
    assert pending["status"] == "no_evidence"
    memory.bridge_store.acknowledge(child)
    _, result = await call(job, "remember", args)
    assert result["ok"] is True
    entry = memory.store.entries("qq:777:11")[0]
    assert json.loads(entry["sources"]) == [child]
    other, _ = running_job(memory, "另一个任务")
    _, denied = await call(other, "remember", args, call_id="other")
    assert denied["status"] == "no_evidence"
    memory.bridge_store.update_job(job["id"], result="共同的回复", status="done")
    memory.sync_completed()
    assert memory.store.source(child)["completed"] == 1
    assert memory.store.source(child)["user_text"] == "请记住，我喜欢喝茶"
    assert memory.store.source(child)["assistant_text"] == ""
    assert memory.store.source(job["id"])["assistant_text"] == "共同的回复"


async def test_agent_can_choose_unpinned_memory_without_explicit_remember(service):
    memory, call = service
    job, _ = running_job(memory, "我喜欢喝茶")
    _, result = await call(job, "remember", {"content": "喜欢喝茶", "evidence": "我喜欢喝茶"})
    assert result["ok"]
    assert not memory.store.entries("qq:777:11")[0]["pinned"]
    # User messages stay unchanged even when the database contains personal facts.
    assert await memory.prepare(job, job["text"]) == "我喜欢喝茶"


@pytest.mark.parametrize(
    "old_scope,group,expected_scope",
    [
        ("private", None, "private"),
        ("group", None, "private"),
        ("group", 22, "group"),
        ("private", 22, "private"),
    ],
)
async def test_update_preserves_protection_and_requires_correction(
    service, old_scope, group, expected_scope
):
    memory, call = service
    owner = seed_source(memory, text="喜欢咖啡", scope=old_scope)
    old = await memory.save_entry(
        owner, "喜欢咖啡", "profile", old_scope, ["seed"], pinned=True, fact_key="preferred_drink"
    )
    job, _ = running_job(memory, "我喜欢喝茶")
    _, denied = await call(
        job, "update", {"id": old["id"], "content": "喜欢喝茶", "evidence": "我喜欢喝茶"}
    )
    assert denied["status"] == "correction_required"
    assert memory.store.entry(old["id"])["state"] == "active"
    job, _ = running_job(memory, "你记得上次的咖啡吗？我不喝咖啡了，改成喝茶", group=group)
    _, updated = await call(
        job, "update", {"id": old["id"], "content": "喜欢喝茶", "evidence": "改成喝茶"}
    )
    assert updated["ok"]
    rows = memory.store.entries(owner)
    assert len(rows) == 1 and rows[0]["pinned"] and rows[0]["content"] == "喜欢喝茶"
    assert rows[0]["scope"] == expected_scope


async def test_forget_failure_retries_durable_ids_before_confirming(service):
    memory, call = service
    owner = seed_source(memory, text="喜欢咖啡")
    old = await memory.save_entry(owner, "喜欢咖啡", "profile", "private", ["seed"])
    await memory.save_entry(owner, "日记说喜欢咖啡", "diary", "private", ["seed"])
    job, _ = running_job(memory, "忘掉我喜欢咖啡这件事")
    memory.backend.delete_failure = True
    args = {"id": old["id"], "evidence": "忘掉我喜欢咖啡这件事"}
    pending = asyncio.create_task(call(job, "forget", args))
    await eventually(
        lambda: bool(
            memory.store.db.execute(
                "SELECT 1 FROM work WHERE attempts=1 AND state='ready' AND error IS NOT NULL"
            ).fetchone()
        )
    )
    assert not pending.done()
    payload = json.loads(memory.store.db.execute("SELECT payload FROM work").fetchone()[0])
    assert len(payload["removed_ids"]) == 2
    memory.store.db.execute("UPDATE work SET next_at=0")
    memory.store.db.commit()
    status, result = await pending
    assert status == 200 and result["status"] == "forgotten"
    assert memory.backend.rows == {}
    assert memory.store.source("seed")["suppressed"]
    assert memory.store.source("seed")["user_text"] == "喜欢咖啡"
    assert memory.store.tombstones(owner)
    assert (await call(job, "forget", args))[1] == result
    assert memory.replies == []


async def test_background_archive_does_not_create_competing_facts(memory):
    owner = seed_source(memory, text="我喜欢咖啡")
    memory.store.complete("seed", "我听到啦")
    assert memory.store.next_work() is None
    # Also retire an old-version queued extraction without invoking the extractor.
    memory.store.enqueue(owner, "extract", {"source": "seed"}, "legacy-extract")
    worker = asyncio.create_task(memory.worker())
    try:
        await eventually(
            lambda: memory.store.db.execute("SELECT state FROM work").fetchone()[0] == "done"
        )
        assert memory.store.entries(owner) == []
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_native_plugin_calls_unix_service_and_hides_tools_for_other_sessions(service):
    memory, _ = service
    owner = seed_source(memory)
    await memory.save_entry(owner, "喜欢喝茶", "profile", "private", ["seed"])
    job, _ = running_job(memory, "我喜欢喝什么")
    plugin = PLUGIN
    options = json.dumps(
        {"socketPath": str(memory.tools.socket), "tokenPath": str(memory.tools.token_path)}
    )
    script = """
import { pathToFileURL } from 'node:url';
const plugin = (await import(pathToFileURL(process.argv[1]))).default;
const tools = new Map();
const hooks = new Map();
const decisions = [];
await plugin.setup({
  options: JSON.parse(process.argv[2]),
  tool: { transform: async fn => fn({namespace(){}, add(t){tools.set(t.name,t)}}) },
  session: { hook: async (name,fn) => hooks.set(name,fn) },
  permission: { assert: async value => decisions.push(value.action) },
});
const context = { sessionID:process.argv[3], id:'call_from_framework',
  messageID:'msg_test', agent:'build' };
const result = await tools.get('search').execute({query:'茶'},context);
const unavailable = {sessionID:'ses_other',tools:{memory_search:{},read:{}}};
await hooks.get('context')(unavailable);
const available = {sessionID:context.sessionID,tools:{memory_search:{},read:{}}};
await hooks.get('context')(available);
console.log(JSON.stringify({result:JSON.parse(result.content),decisions,
  unavailable:Object.keys(unavailable.tools),available:Object.keys(available.tools)}));
"""
    proc = await asyncio.create_subprocess_exec(
        "node",
        "--input-type=module",
        "-e",
        script,
        str(plugin),
        options,
        job["session_id"],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    assert proc.returncode == 0, stderr.decode()
    result = json.loads(stdout)
    assert result["result"]["memories"][0]["content"] == "喜欢喝茶"
    assert result["decisions"] == ["memory_search"]
    assert result["unavailable"] == ["read"]
    assert "memory_search" in result["available"]
