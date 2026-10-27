"""Context reads and manual compaction use fake OpenCode; no real model or QQ calls."""

import json

import pytest
from test_webui import assistant

from qqbot.models import Context
from qqbot.opencode import ApiError
from qqbot.webui_context import context_usage

pytest_plugins = ["test_webui"]


async def test_context_uses_latest_measured_call_and_current_model_limit(console):
    console.job()
    console.fake.sessions["ses_current"]["model"] = {"id": "test-model", "providerID": "test"}
    console.fake.sessions["ses_current"]["tokens"] = {"input": 99999999}
    last = assistant("last")
    last["tokens"]["cache"]["write"] = 30
    console.fake.contexts["ses_current"] = [assistant("old"), last]
    await console.login()
    result = await (await console.client.get("/api/sessions/ses_current/context")).json()
    assert result["used_tokens"] == 210
    assert result["input_tokens"] == 180
    assert result["output_tokens"] == 30
    assert result["context_limit"] == 1000
    assert result["percentage"] == 21
    assert not console.fake.compactions
    assert "content" not in json.dumps(result)


@pytest.mark.parametrize("state", ["running", "completed", "failed"])
async def test_compaction_state_and_stale_usage_after_checkpoint(console, state):
    console.job()
    console.fake.contexts["ses_current"] = [
        assistant("before"),
        {"id": "msg_compacted", "type": "compaction", "status": state, "summary": "private"},
    ]
    await console.login()
    result = await (await console.client.get("/api/sessions/ses_current/context")).json()
    assert result["compaction"]["status"] == state
    assert result["used_tokens"] == (None if state == "completed" else 180)
    assert "private" not in json.dumps(result)
    console.fake.inboxes["ses_current"] = [{"type": "compaction", "id": "msg_pending"}]
    result = await (await console.client.get("/api/sessions/ses_current/context")).json()
    assert result["compaction"]["status"] == "queued"


def test_context_missing_usage_and_limit_are_unknown():
    result = context_usage({"id": "empty"}, [], [], None, [])
    assert result["used_tokens"] is result["context_limit"] is result["percentage"] is None
    measured = assistant("measured")
    result = context_usage(
        {"id": "empty"}, [measured, assistant("zero") | {"tokens": {}}], [], None, []
    )
    assert result["used_tokens"] == 180
    assert result["context_limit"] is result["percentage"] is None


async def test_context_follows_current_mapping_instead_of_latest_historical_job(console):
    console.job(session="current")
    console.job(session="newer-history")
    console.store.set_session(Context(777, 11), "current")
    await console.login()
    result = await (await console.client.get("/api/conversations")).json()
    assert result["items"][0]["current_session_id"] == "current"
    console.store.reset_session(Context(777, 11))
    result = await (await console.client.get("/api/conversations")).json()
    assert result["items"][0]["current_session_id"] is None


async def test_context_and_compaction_require_admin_csrf_confirmation_and_bridge_scope(console):
    console.job()
    url = "/api/sessions/ses_current"
    assert (await console.client.get(url + "/context")).status == 401
    assert (await console.client.post(url + "/compact", json={})).status == 401
    headers = await console.login()
    assert (await console.client.post(url + "/compact", json={})).status == 403
    for body in ({}, {"confirm": "compact", "request_id": "invalid"}):
        assert (
            await console.client.post(url + "/compact", headers=headers, json=body)
        ).status == 400
    console.fake.add("foreign")
    assert (await console.client.get("/api/sessions/foreign/context")).status == 404
    response = await console.client.post(
        "/api/sessions/foreign/compact",
        headers=headers,
        json={"confirm": "compact", "request_id": "msg_foreign"},
    )
    assert response.status == 404
    assert not console.fake.compactions


async def test_manual_compaction_is_accepted_without_changing_history_or_mapping(console):
    job_id = console.job()
    console.fake.add("child", parent="ses_current")
    console.store.set_session(Context(777, 11), "ses_current")
    headers = await console.login()
    for _ in range(2):
        response = await console.client.post(
            "/api/sessions/child/compact",
            headers=headers,
            json={"confirm": "compact", "request_id": "msg_once"},
        )
        assert response.status == 202
        assert await response.json() == {"status": "accepted", "id": "msg_once"}
    assert len(console.fake.compactions) == 1
    assert console.fake.compactions["msg_once"]["sessionID"] == "child"
    assert console.store.session(Context(777, 11)) == "ses_current"
    assert console.store.job(job_id)["status"] == "done"
    assert console.dashboard.auth.data["audit"][-1]["action"] == "compaction_requested"


@pytest.mark.parametrize("state", ["queued", "preparing", "running", "waiting", "delivering"])
async def test_compaction_rejects_unfinished_chat_work(console, state):
    console.job(status=state)
    headers = await console.login()
    response = await console.client.post(
        "/api/sessions/ses_current/compact",
        headers=headers,
        json={"confirm": "compact", "request_id": "msg_busy"},
    )
    assert response.status == 409
    assert not console.fake.compactions


async def test_compaction_rejects_active_sibling_and_pending_work(console):
    console.job()
    console.fake.add("child", parent="ses_current")
    console.fake.add("sibling", parent="ses_current")
    headers = await console.login()
    for active, inbox in (({"sibling": {}}, []), ({}, [{"type": "compaction"}])):
        console.fake.active_ids = active
        console.fake.inboxes["child"] = inbox
        response = await console.client.post(
            "/api/sessions/child/compact",
            headers=headers,
            json={"confirm": "compact", "request_id": "msg_busy"},
        )
        assert response.status == 409
    assert not console.fake.compactions


async def test_compaction_rechecks_local_work_after_remote_checks(console):
    console.job()
    original = console.fake.inbox

    async def inbox(session_id):
        console.job(status="queued")
        return await original(session_id)

    console.fake.inbox = inbox
    headers = await console.login()
    response = await console.client.post(
        "/api/sessions/ses_current/compact",
        headers=headers,
        json={"confirm": "compact", "request_id": "msg_race"},
    )
    assert response.status == 409
    assert not console.fake.compactions


@pytest.mark.parametrize("failure", [ApiError(404, "compact"), TimeoutError()])
async def test_unsupported_or_uncertain_compaction_never_retries(console, failure):
    console.job()
    original, calls = console.fake.request, []

    async def request(method, path, **kwargs):
        if method == "POST":
            calls.append(path)
            raise failure
        return await original(method, path, **kwargs)

    console.fake.request = request
    headers = await console.login()
    response = await console.client.post(
        "/api/sessions/ses_current/compact",
        headers=headers,
        json={"confirm": "compact", "request_id": "msg_failure"},
    )
    assert response.status == (501 if isinstance(failure, ApiError) else 503)
    assert len(calls) == 1
    if not isinstance(failure, ApiError):
        assert "尚未确认" in (await response.json())["error"]
