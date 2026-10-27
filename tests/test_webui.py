from __future__ import annotations

import asyncio
import json
import stat
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from qqbot.bridge import Bridge
from qqbot.config import Config
from qqbot.memory_store import MemoryStore
from qqbot.models import Context
from qqbot.opencode import ApiError
from qqbot.store import Store
from qqbot.webui_auth import COOKIE_NAME, AdminAuth
from qqbot.webui_data import metrics


class ConsoleOpenCode:
    """Read-only fake v2 API with real pagination and explicit archive filtering."""

    def __init__(self):
        self.sessions = {}
        self.messages = {}
        self.active_ids = {}
        self.page_size = 2
        self.requests = []

    def add(self, session_id, conversation=None, *, parent=None, archived=False):
        self.sessions[session_id] = {
            "id": session_id,
            "parentID": parent,
            "title": "会话 " + session_id,
            "metadata": {"qq_bridge_context": conversation} if conversation else {},
            "archived": archived,
            "time": {"created": 1000, "updated": 2000},
        }
        self.messages[session_id] = []

    async def get_session(self, session_id):
        if session_id not in self.sessions:
            raise ApiError(404, "get-session")
        return self.sessions[session_id]

    async def active(self):
        return self.active_ids

    async def belongs_to(self, session_id, root):
        visited = set()
        while session_id and session_id not in visited:
            if session_id == root:
                return True
            visited.add(session_id)
            session_id = (await self.get_session(session_id)).get("parentID")
        return False

    async def request(self, method, path, *, params=None, unwrap=True):
        assert method == "GET", "The console must not submit model work while reading."
        self.requests.append((method, path))
        params = params or {}
        offset = int(params.get("cursor", 0))
        if path == "/api/session":
            parent = params.get("parentID")
            if parent == "null":
                items = [s for s in self.sessions.values() if not s.get("parentID")]
                items = [s for s in items if s["archived"] == (params.get("archived") == "true")]
            else:
                items = [s for s in self.sessions.values() if s.get("parentID") == parent]
        else:
            session_id = path.split("/")[3]
            if session_id not in self.sessions:
                raise ApiError(404, "messages")
            items = list(reversed(self.messages[session_id]))
        end = offset + self.page_size
        data = {
            "data": items[offset:end],
            "cursor": {"next": str(end) if end < len(items) else None},
        }
        return data["data"] if unwrap else data


@pytest.fixture
async def console(tmp_path):
    cfg = Config(
        napcat_url="ws://127.0.0.1:1",
        napcat_token="napcat-test-secret",
        allowed_users=frozenset({11, 12}),
        allowed_groups=frozenset({22, 33}),
        superadmin_user_id=11,
        workdir=tmp_path / "workspace",
        state_db=tmp_path / "state.db",
        memory_db=tmp_path / "memory.db",
        webui_enabled=True,
        webui_port=0,
    )
    store = Store(cfg.state_db)
    bot = SimpleNamespace(self_id=777, online=True)
    opencode = SimpleNamespace(available=True, headers={}, http=None)
    bridge = Bridge(cfg, store, bot, opencode)
    dashboard = bridge.webui
    fake = ConsoleOpenCode()
    dashboard.data.client = lambda: fake
    restarted = asyncio.Event()

    async def restart():
        restarted.set()

    dashboard.restart = restart
    client = TestClient(TestServer(await dashboard.application()))
    await client.start_server()
    password = dashboard.auth.login_file.read_text().split("密码：", 1)[1].splitlines()[0]

    async def login():
        response = await client.post(
            "/api/auth/login", json={"username": "admin", "password": password}
        )
        assert response.status == 200
        payload = await response.json()
        return {"X-CSRF-Token": payload["csrf"]}

    def job(text="测试任务", *, user=11, group=None, session="ses_current", status="done"):
        context = Context(777, user, group)
        job_id = store.enqueue(context, text, [])
        store.update_job(job_id, session_id=session)
        if status != "queued":
            path = {
                "done": ["preparing", "submitting", "running", "done"],
                "running": ["preparing", "submitting", "running"],
                "waiting": ["preparing", "waiting"],
                "cancelling": ["cancelling"],
                "cancelled": ["cancelled"],
                "reply_ready": ["preparing", "submitting", "running", "reply_ready"],
                "delivering": ["preparing", "submitting", "running", "delivering"],
                "failed": ["failed"],
            }.get(status, [status])
            for step in path:
                store.update_job(job_id, status=step)
        if session not in fake.sessions:
            fake.add(session, context.conversation_key)
        return job_id

    try:
        yield SimpleNamespace(
            client=client,
            dashboard=dashboard,
            bridge=bridge,
            store=store,
            fake=fake,
            login=login,
            job=job,
            password=password,
            restarted=restarted,
            config=cfg,
        )
    finally:
        await client.close()
        await dashboard.close()
        await bridge.memory.close()
        store.close()


@pytest.mark.parametrize(
    "path", ["overview", "conversations", "jobs", "memories", "system", "sessions"]
)
async def test_admin_data_requires_login(console, path):
    response = await console.client.get("/api/" + path)
    assert response.status == 401
    assert not console.fake.requests


async def test_auth_cookie_and_private_bootstrap_never_appear_in_responses(console):
    response = await console.client.post(
        "/api/auth/login", json={"username": "admin", "password": "wrong"}
    )
    assert response.status == 401
    headers = await console.login()
    response = await console.client.get("/api/auth/status")
    payload = await response.json()
    assert payload["csrf"] == headers["X-CSRF-Token"]
    assert payload["admin_user_id"] == 11
    assert console.password not in console.dashboard.auth.path.read_text()
    assert stat.S_IMODE(console.dashboard.auth.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(console.dashboard.auth.login_file.stat().st_mode) == 0o600
    cookie = console.client.session.cookie_jar.filter_cookies(console.client.make_url("/"))[
        COOKIE_NAME
    ]
    assert console.dashboard.auth.valid(cookie.value)
    reloaded = AdminAuth(console.config.state_db.parent)
    assert reloaded.valid(cookie.value)
    for path in ("/", "/assets/console.js", "/assets/style.css"):
        response = await console.client.get(path)
        assert response.status == 200
        assert console.password not in await response.text()
        assert response.headers["Cache-Control"] == "no-store"
    assert (await console.client.get("/assets/webui-login.txt")).status == 404


async def test_mutations_require_csrf_and_same_origin(console):
    headers = await console.login()
    assert (
        await console.client.post("/api/system/restart", json={"confirm": "restart"})
    ).status == 403
    response = await console.client.post(
        "/api/system/restart",
        headers=headers | {"Origin": "https://elsewhere.invalid"},
        json={"confirm": "restart"},
    )
    assert response.status == 403
    assert not console.restarted.is_set()
    assert not console.dashboard.restart_pending


async def test_userscript_styles_are_allowed_while_scripts_and_admin_data_remain_restricted(
    console,
):
    response = await console.client.get("/")
    policy = response.headers["Content-Security-Policy"]
    directives = dict(
        (parts[0], parts[1:])
        for directive in policy.split(";")
        if (parts := directive.strip().split())
    )
    assert "'unsafe-inline'" in directives["style-src"]
    assert directives["script-src"] == ["'self'"]
    assert directives["connect-src"] == ["'self'"]
    assert (await console.client.get("/api/jobs")).status == 401


async def test_login_limits_password_work_and_rejects_non_object_bodies(console):
    response = await console.client.post("/api/auth/login", json=[])
    assert response.status == 400
    for _ in range(9):
        assert (
            await console.client.post(
                "/api/auth/login", json={"username": "admin", "password": "wrong"}
            )
        ).status == 401
    assert (
        await console.client.post(
            "/api/auth/login", json={"username": "admin", "password": console.password}
        )
    ).status == 429


async def test_change_password_revokes_old_sessions_and_removes_bootstrap(console):
    headers = await console.login()
    cookie = console.client.session.cookie_jar.filter_cookies(console.client.make_url("/"))[
        COOKIE_NAME
    ].value
    response = await console.client.post(
        "/api/auth/password",
        headers=headers,
        json={
            "username": "owner",
            "current_password": console.password,
            "password": "a-new-test-password-123",
        },
    )
    assert response.status == 200
    assert (await response.json())["username"] == "owner"
    assert not console.dashboard.auth.valid(cookie)
    assert not console.dashboard.auth.login_file.exists()
    assert console.dashboard.auth.check("owner", "a-new-test-password-123")


async def test_restart_is_explicit_queued_and_preserves_durable_state(console):
    job_id = console.job(status="running")
    headers = await console.login()
    assert (
        await console.client.post("/api/system/restart", headers=headers, json={})
    ).status == 400
    response = await console.client.post(
        "/api/system/restart", headers=headers, json={"confirm": "restart"}
    )
    assert response.status == 202
    assert (await response.json())["status"] == "restart_requested"
    assert (
        await console.client.post(
            "/api/system/restart", headers=headers, json={"confirm": "restart"}
        )
    ).status == 409
    await asyncio.wait_for(console.restarted.wait(), 2)
    assert console.store.job(job_id)["status"] == "running"
    assert console.dashboard.auth.data["audit"][-1]["action"] == "restart_requested"


async def test_reads_never_run_store_recovery_or_change_sending_state(console):
    job_id = console.job()
    context = Context(777, 11)
    console.store.put_outbox(context, "已在发送", "test", 1800, job_id)
    console.store.db.execute("UPDATE outbox SET status='sending'")
    console.store.db.commit()
    await console.login()
    for path in ("/api/overview", "/api/jobs", "/api/conversations", "/api/sessions"):
        assert (await console.client.get(path)).status == 200
    assert console.store.db.execute("SELECT status FROM outbox").fetchone()[0] == "sending"


def assistant(message_id, *, text="执行完成", start=1100, end=2100):
    return {
        "id": message_id,
        "type": "assistant",
        "time": {"created": start, "completed": end},
        "content": [{"type": "text", "text": text}],
        "tokens": {"input": 50, "output": 10, "reasoning": 20, "cache": {"read": 100}},
    }


async def test_job_turn_respects_pagination_next_user_boundary_and_redacts_credentials(console):
    job_id = console.job("第一条要求")
    prompt_id = console.store.job(job_id)["prompt_id"]
    response = assistant("answer")
    response["content"] = [
        {
            "type": "reasoning",
            "text": "fake model reasoning",
            "time": {"created": 1100, "completed": 1700},
        },
        {
            "type": "tool",
            "id": "tool-one",
            "name": "read",
            "time": {"created": 1700, "ran": 1800, "completed": 2000},
            "state": {
                "status": "completed",
                "input": {"password": "secret-value", "path": "README.md"},
                "content": [{"type": "text", "text": "napcat-test-secret"}],
            },
        },
        {"type": "text", "text": "第一条回答"},
    ]
    console.fake.messages["ses_current"] = [
        {"id": "before", "type": "user", "text": "更早的要求"},
        assistant("before-answer"),
        {"id": prompt_id, "type": "user", "text": "第一条要求"},
        response,
        {"id": "next-user", "type": "user", "text": "下一条独立要求"},
        assistant("next-answer"),
    ]
    await console.login()
    result = await (await console.client.get("/api/jobs/" + job_id)).json()
    assert result["complete"] is True
    assert [m["id"] for m in result["messages"]] == [prompt_id, "answer"]
    assert result["metrics"]["tools"] == 1
    assert result["metrics"]["reasoning_ms"] == 600
    assert result["metrics"]["input_tokens"] == 50
    assert result["messages"][1]["content"][1]["duration_ms"] == 200
    encoded = json.dumps(result)
    assert "secret-value" not in encoded and "napcat-test-secret" not in encoded
    assert len(console.fake.requests) >= 2


async def test_turn_includes_frozen_steers_once_and_never_a_future_turn(console):
    job_id = console.job(status="running")
    root = console.store.job(job_id)
    steer_id = console.store.enqueue(Context(777, 11), "补充条件", [], steer_parent_id=job_id)
    steer = console.store.job(steer_id)
    console.fake.messages["ses_current"] = [
        {"id": root["prompt_id"], "type": "user", "text": "原任务"},
        assistant("first"),
        {"id": steer["prompt_id"], "type": "user", "text": "补充条件"},
        assistant("second"),
        {"id": "future", "type": "user", "text": "另一轮"},
        assistant("future-answer"),
    ]
    await console.login()
    result = await (await console.client.get("/api/jobs/" + job_id)).json()
    assert [m["id"] for m in result["messages"]] == [
        root["prompt_id"],
        "first",
        steer["prompt_id"],
        "second",
    ]
    assert len(result["steers"]) == 1
    assert result["metrics"]["model_calls"] == 2


async def test_chat_list_includes_separate_supplements_bound_to_the_original_task(console):
    root = console.job("原始要求", status="running")
    first = console.store.enqueue(Context(777, 11), "第一条补充", [], steer_parent_id=root)
    second = console.store.enqueue(Context(777, 11), "第二条补充", [], steer_parent_id=root)
    unrelated = console.job("另一个聊天", user=12, session="other", status="running")
    console.store.enqueue(Context(777, 12), "不能串进来的补充", [], steer_parent_id=unrelated)
    await console.login()
    response = await console.client.get("/api/jobs", params={"conversation": "777:private:11"})
    items = (await response.json())["items"]
    assert len(items) == 1
    assert items[0]["id"] == root
    assert [item["id"] for item in items[0]["steers"]] == [first, second]
    assert [item["text"] for item in items[0]["steers"]] == ["第一条补充", "第二条补充"]
    assert console.store.job(first)["status"] == "steering"
    assert not console.fake.requests


async def test_deleted_remote_record_keeps_local_result_and_delivery(console):
    job_id = console.job()
    console.store.update_job(job_id, result="保存在桥接中的最终结果")
    del console.fake.sessions["ses_current"]
    await console.login()
    result = await (await console.client.get("/api/jobs/" + job_id)).json()
    assert result["result"] == "保存在桥接中的最终结果"
    assert result["remote_error"]
    assert not result["messages"]


async def test_all_historical_and_archived_bridge_sessions_are_discoverable(console):
    console.job(session="old")
    console.job(session="new")
    console.store.set_session(Context(777, 11), "new")
    console.fake.add("archived-root", "777:private:11", archived=True)
    console.fake.add("unrelated")
    console.fake.add("remote-only", "777:private:11")
    console.fake.add("child", parent="old")
    await console.login()
    result = await (await console.client.get("/api/sessions")).json()
    assert {item["id"] for item in result["items"]} == {
        "old",
        "new",
        "archived-root",
        "remote-only",
    }
    assert next(item for item in result["items"] if item["id"] == "new")["current"]
    assert result["complete"]
    assert (await console.client.get("/api/sessions/child")).status == 200
    assert (await console.client.get("/api/sessions/unrelated")).status == 404


async def test_session_detail_reads_all_child_pages_and_public_theme_assets(console):
    console.job(session="root")
    for index in range(5):
        console.fake.add(f"child-{index}", parent="root")
    await console.login()
    result = await (await console.client.get("/api/sessions/root")).json()
    assert {item["id"] for item in result["children"]} == {f"child-{index}" for index in range(5)}
    for asset in (
        "theme.css",
        "serif-sc.woff2",
        "mono.woff2",
        "mist.svg",
        "favicon.svg",
        "assistant-avatar.svg",
        "Lucide-LICENSE.txt",
    ):
        response = await console.client.get("/assets/" + asset)
        assert response.status == 200
        assert await response.read()
        if asset in {"favicon.svg", "assistant-avatar.svg"}:
            assert response.headers["Cache-Control"] == "public, max-age=86400"


async def test_staged_module_console_assets_are_served_from_self(console):
    index = await console.client.get("/")
    assert index.status == 200
    assert 'type="module" src="/assets/console.js"' in await index.text()
    for asset in (
        "console.js",
        "console-conversations.js",
        "console-knowledge.js",
    ):
        response = await console.client.get("/assets/" + asset)
        assert response.status == 200
        assert await response.read()


async def test_conversation_groups_all_generations_and_searches_without_message_id(console):
    first = console.job("较早的咖啡要求", session="old")
    second = console.job("今天的要求", session="new")
    console.job("另一位用户", user=12, session="other")
    await console.login()
    result = await (await console.client.get("/api/conversations", params={"q": "咖啡"})).json()
    assert len(result["items"]) == 1
    assert result["items"][0]["jobs"] == 2
    jobs = await (
        await console.client.get("/api/jobs", params={"conversation": "777:private:11"})
    ).json()
    assert {item["id"] for item in jobs["items"]} == {first, second}
    assert (await console.client.get("/api/conversations", params={"q": "' OR 1=1"})).status == 200


async def test_switch_mapping_preserves_old_records_and_changes_only_selected_chat(console):
    old = console.job(session="old")
    new = console.job(session="new")
    console.job(user=12, session="other")
    console.store.set_session(Context(777, 11), "new")
    console.store.set_session(Context(777, 12), "other")
    headers = await console.login()
    response = await console.client.post(
        "/api/mappings",
        headers=headers,
        json={
            "confirm": "switch",
            "conversation": "777:private:11",
            "session_id": "old",
            "expected_current": "new",
        },
    )
    assert response.status == 200
    assert console.store.session(Context(777, 11)) == "old"
    assert console.store.session(Context(777, 12)) == "other"
    assert console.store.job(old)["session_id"] == "old"
    assert console.store.job(new)["session_id"] == "new"
    assert {item["id"] for item in console.dashboard.auth.data["session_history"]} == {"old", "new"}


@pytest.mark.parametrize("status", ["queued", "running", "waiting", "reply_ready", "delivering"])
async def test_mapping_switch_is_blocked_by_unfinished_tasks(console, status):
    console.job(session="old", status=status)
    console.job(session="new")
    console.store.set_session(Context(777, 11), "old")
    headers = await console.login()
    response = await console.client.post(
        "/api/mappings",
        headers=headers,
        json={
            "confirm": "switch",
            "conversation": "777:private:11",
            "session_id": "new",
            "expected_current": "old",
        },
    )
    assert response.status == 409
    assert console.store.session(Context(777, 11)) == "old"


async def test_mapping_rejects_cross_chat_private_group_context_and_active_child(console):
    console.job(group=22, session="shared")
    isolated = console.job(group=22, session="isolated")
    console.store.db.execute("UPDATE jobs SET memory_isolated=1 WHERE id=?", (isolated,))
    console.store.db.commit()
    console.job(session="private")
    console.store.set_session(Context(777, 11, 22), "shared")
    headers = await console.login()
    for candidate in ("isolated", "private"):
        response = await console.client.post(
            "/api/mappings",
            headers=headers,
            json={
                "confirm": "switch",
                "conversation": "777:group:22",
                "session_id": candidate,
                "expected_current": "shared",
            },
        )
        assert response.status == 403
    console.job(group=22, session="older-shared")
    console.fake.add("busy-child", parent="older-shared")
    console.fake.active_ids = {"busy-child": {}}
    response = await console.client.post(
        "/api/mappings",
        headers=headers,
        json={
            "confirm": "switch",
            "conversation": "777:group:22",
            "session_id": "older-shared",
            "expected_current": "shared",
        },
    )
    assert response.status == 409


async def test_group_mapping_starts_new_generation_without_deleting_history(console):
    console.job(group=22, session="old")
    console.job(group=22, session="new")
    context = Context(777, 11, 22)
    console.store.set_session(context, "new")
    before = console.store.group_state(context)["generation"]
    headers = await console.login()
    response = await console.client.post(
        "/api/mappings",
        headers=headers,
        json={
            "confirm": "switch",
            "conversation": context.conversation_key,
            "session_id": "old",
            "expected_current": "new",
        },
    )
    assert response.status == 200
    assert console.store.group_state(context)["generation"] == before + 1
    assert len(console.store.conversation_jobs(context, unfinished=False)) == 2


async def test_cancel_single_delivery_blocks_only_its_unsent_output_and_steers(console):
    first = console.job(status="running")
    steer = console.store.enqueue(Context(777, 11), "补充", [], steer_parent_id=first)
    console.store.update_job(first, status="delivering")
    second = console.job("另一个任务", status="queued")
    console.store.put_outbox(Context(777, 11), "待交付", "first", 1800, first)
    headers = await console.login()
    assert (
        await console.client.post("/api/jobs/" + first + "/cancel", headers=headers, json={})
    ).status == 200
    assert console.store.job(first)["status"] == "cancelled"
    assert console.store.job(steer)["status"] == "cancelled"
    assert console.store.job(second)["status"] == "queued"
    assert console.store.db.execute("SELECT status FROM outbox").fetchone()[0] == "blocked"


async def test_memory_view_scopes_owner_and_hides_forgotten_sources(console):
    config = replace(console.config, memory_enabled=True, memory_owner_user_id=11)
    console.dashboard.config = console.dashboard.data.config = config
    memory = MemoryStore(config.memory_db)
    try:
        owner = "qq:777:11"
        memory.archive("source", owner, "private", "喜欢绿茶")
        memory.archive("hidden-source", owner, "private", "已遗忘的原话")
        memory.db.execute("UPDATE archive SET suppressed=1 WHERE id='hidden-source'")
        memory.db.commit()
        active = memory.prepare_entry(
            owner, "喜欢绿茶", "profile", "private", ["source", "hidden-source"], pinned=True
        )
        memory.activate(active["id"], "backend-one")
        expired = memory.prepare_entry(
            owner, "前几天疲惫", "state", "private", ["source"], expires=time.time() - 1
        )
        memory.activate(expired["id"], "backend-two")
        deleted = memory.prepare_entry(owner, "删除的记忆", "profile", "private", ["source"])
        memory.activate(deleted["id"], "backend-three")
        memory.deactivate([deleted["id"]])
        other = memory.prepare_entry("qq:777:12", "其他人的事实", "profile", "private", [])
        memory.activate(other["id"], "backend-four")
        await console.login()
        result = await (await console.client.get("/api/memories")).json()
        assert result["total"] == 2
        assert "已遗忘的原话" not in json.dumps(result, ensure_ascii=False)
        assert {item["id"] for item in result["items"]} == {active["id"], expired["id"]}
        assert next(item for item in result["items"] if item["id"] == expired["id"])["expired"]
        result = await (await console.client.get("/api/memories", params={"q": "绿茶"})).json()
        assert result["total"] == 1
        assert result["items"][0]["scope"] == "private"
    finally:
        memory.close()


def test_missing_reasoning_timestamps_do_not_become_model_latency():
    message = assistant("answer", start=0, end=9000)
    message["content"] = [{"type": "reasoning", "text": "no timing provided"}]
    result = metrics([message])
    assert result["reasoning_ms"] is None
    assert result["reasoning_missing"] == 1
    assert result["model_ms"] == 9000


async def test_overview_reports_knowledge_readiness_without_model_or_store_initialization(
    console, monkeypatch, tmp_path
):
    import sqlite3
    from unittest.mock import MagicMock

    data = console.dashboard.data
    headers = await console.login()
    connect = MagicMock()
    monkeypatch.setattr("qqbot.webui_data.psycopg2.connect", connect)
    response = await console.client.get("/api/overview", headers=headers)
    assert (await response.json())["knowledge"] == {
        "enabled": False,
        "ready": False,
        "error": False,
    }
    connect.assert_not_called()
    data.config = replace(console.config, knowledge_enabled=True)
    root = tmp_path / "knowledge"
    root.mkdir()
    console.bridge.knowledge = SimpleNamespace(root=root, backend_error="")
    data.knowledge = console.bridge.knowledge
    assert data.knowledge_status() == {"enabled": True, "ready": False, "error": False}
    with sqlite3.connect(root / "catalogue.sqlite3") as db:
        db.execute("CREATE TABLE libraries (id TEXT)")
    connection = connect.return_value
    connection.cursor.return_value.__enter__.return_value.fetchone.return_value = (1,)
    for _ in range(2):
        response = await console.client.get("/api/overview", headers=headers)
        assert (await response.json())["knowledge"] == {
            "enabled": True,
            "ready": True,
            "error": False,
        }
    connect.assert_called_once()
    connection.set_session.assert_called_once_with(readonly=True, autocommit=True)
    connection.cursor.return_value.__enter__.return_value.execute.assert_called_once_with(
        "SELECT 1"
    )
    connection.close.assert_called_once()
    import psycopg2

    data.cache.pop("knowledge-health")
    connect.side_effect = psycopg2.OperationalError("private connection detail")
    response = await console.client.get("/api/overview", headers=headers)
    payload = await response.json()
    assert payload["knowledge"] == {"enabled": True, "ready": False, "error": True}
    assert "private connection detail" not in str(payload)
    console.bridge.knowledge.backend_error = "embedding configuration changed"
    assert data.knowledge_status()["error"]
