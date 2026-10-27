"""Fork admission, mapping changes, shared-group privacy and uncertain creation."""

import json

import pytest
from test_webui import assistant

from qqbot.models import Context
from qqbot.webui_auth import AdminAuth

pytest_plugins = ["test_webui"]


def setup_source(console, *, group=None, status="done"):
    job_id = console.job(group=group, status=status)
    context = Context(777, 11, group)
    console.store.set_session(context, "ses_current")
    console.fake.messages["ses_current"] = [assistant("original")]
    return job_id, context


async def fork(console, headers, context, *, request_id="fork_request_1", title="另一种方案"):
    return await console.client.post(
        "/api/sessions/ses_current/fork",
        headers=headers,
        json={
            "confirm": "fork",
            "conversation": context.conversation_key,
            "expected_current": "ses_current",
            "request_id": request_id,
            "title": title,
        },
    )


@pytest.mark.parametrize("group", [None, 22])
async def test_fork_switch_return_original_and_switch_back_to_unused_branch(console, group):
    job_id, context = setup_source(console, group=group)
    original = json.dumps(console.fake.sessions["ses_current"])
    headers = await console.login()
    response = await fork(console, headers, context)
    assert response.status == 201
    result = await response.json()
    branch = result["session_id"]
    assert result["switched"]
    assert console.store.session(context) == branch
    assert console.store.job(job_id)["session_id"] == "ses_current"
    assert json.dumps(console.fake.sessions["ses_current"]) == original
    assert console.fake.messages[branch] == console.fake.messages["ses_current"]
    assert console.fake.sessions[branch]["metadata"]["qq_bridge_job_id"] is None
    assert console.fake.sessions[branch]["title"] == "另一种方案"
    for expected, target in [(branch, "ses_current"), ("ses_current", branch)]:
        response = await console.client.post(
            "/api/mappings",
            headers=headers,
            json={
                "confirm": "switch",
                "conversation": context.conversation_key,
                "session_id": target,
                "expected_current": expected,
            },
        )
        assert response.status == 200
        assert console.store.session(context) == target
    assert len(console.fake.forks) == 1


async def test_group_fork_resets_previous_initiators_authority(console):
    _, context = setup_source(console, group=22)
    console.fake.sessions["ses_current"]["permissions"] = [
        {"action": "*", "resource": "*", "effect": "allow"}
    ]
    console.fake.sessions["ses_current"]["metadata"].update(
        qq_bridge_job_id="old-admin-job", qq_bridge_auto_allow=True
    )
    headers = await console.login()
    result = await (await fork(console, headers, context)).json()
    child = console.fake.sessions[result["session_id"]]
    assert child["metadata"]["qq_bridge_auto_allow"] is False
    assert child["metadata"]["qq_bridge_job_id"] is None
    assert child["permissions"][0]["effect"] == "ask"
    assert next(r for r in child["permissions"] if r["action"] == "memory_*")["effect"] == "deny"
    assert console.fake.sessions["ses_current"]["metadata"]["qq_bridge_auto_allow"] is True


async def test_fork_request_replay_survives_restart_and_never_undoes_manual_switch(console):
    _, context = setup_source(console)
    headers = await console.login()
    first = await (await fork(console, headers, context)).json()
    console.store.switch_session(context, "ses_current")
    console.dashboard.auth = AdminAuth(console.config.state_db.parent)
    second = await (await fork(console, headers, context)).json()
    assert second["session_id"] == first["session_id"]
    assert second["replayed"] and not second["switched"]
    assert console.store.session(context) == "ses_current"
    assert len(console.fake.forks) == 1


@pytest.mark.parametrize("status", ["queued", "running", "waiting", "delivering"])
async def test_fork_blocks_unfinished_work(console, status):
    _, context = setup_source(console, status=status)
    response = await fork(console, await console.login(), context)
    assert response.status == 409
    assert not console.fake.forks


async def test_fork_blocks_active_descendants_and_pending_compaction(console):
    _, context = setup_source(console)
    headers = await console.login()
    console.fake.add("child", parent="ses_current")
    for active, inbox in [({"child": {}}, []), ({}, [{"type": "compaction"}])]:
        console.fake.active_ids = active
        console.fake.inboxes["ses_current"] = inbox
        assert (await fork(console, headers, context)).status == 409
    assert not console.fake.forks


async def test_switch_branch_rejects_pending_work_on_target(console):
    _, context = setup_source(console)
    headers = await console.login()
    branch = (await (await fork(console, headers, context)).json())["session_id"]
    console.fake.inboxes["ses_current"] = [{"type": "compaction"}]
    response = await console.client.post(
        "/api/mappings",
        headers=headers,
        json={
            "confirm": "switch",
            "conversation": context.conversation_key,
            "session_id": "ses_current",
            "expected_current": branch,
        },
    )
    assert response.status == 409
    assert console.store.session(context) == branch


async def test_fork_auth_csrf_scope_privacy_and_stale_mapping(console):
    _, context = setup_source(console)
    assert (await fork(console, {}, context)).status == 401
    headers = await console.login()
    assert (await fork(console, {}, context)).status == 403
    console.job(user=12, session="other")
    console.store.set_session(Context(777, 12), "other")
    assert (await fork(console, headers, Context(777, 12))).status == 403
    console.store.switch_session(context, "changed")
    assert (await fork(console, headers, context)).status == 409
    private_job, group_context = setup_source(console, group=22)
    console.store.db.execute("UPDATE jobs SET memory_isolated=1 WHERE id=?", (private_job,))
    console.store.db.commit()
    assert (await fork(console, headers, group_context, request_id="private_request")).status == 403
    assert not console.fake.forks


@pytest.mark.parametrize("change", ["job", "mapping"])
async def test_new_work_during_fork_keeps_created_branch_without_switching_or_recreating(
    console, change
):
    _, context = setup_source(console)
    original = console.fake.request

    async def request(method, path, **kwargs):
        result = await original(method, path, **kwargs)
        if path.endswith("/fork"):
            if change == "job":
                console.job(status="queued")
            else:
                console.fake.add("changed", context.conversation_key)
                console.store.switch_session(context, "changed")
        return result

    console.fake.request = request
    headers = await console.login()
    for _ in range(2):
        response = await fork(console, headers, context)
        assert response.status == 201
        assert not (await response.json())["switched"]
    assert console.store.session(context) == ("ses_current" if change == "job" else "changed")
    assert len(console.fake.forks) == 1


async def test_uncertain_fork_creation_is_never_resubmitted_and_branch_is_discoverable(console):
    _, context = setup_source(console)
    original = console.fake.request

    async def request(method, path, **kwargs):
        result = await original(method, path, **kwargs)
        if path.endswith("/fork"):
            raise TimeoutError
        return result

    console.fake.request = request
    headers = await console.login()
    assert (await fork(console, headers, context)).status == 503
    assert (await fork(console, headers, context)).status == 409
    assert len(console.fake.forks) == 1
    index = await (await console.client.get("/api/sessions")).json()
    branch = next(item for item in index["items"] if item["id"] == "ses_fork_1")
    assert branch["eligible"] and branch["fork_of"] == "ses_current"
    assert console.store.session(context) == "ses_current"


async def test_fork_ancestry_cannot_make_private_group_history_reusable(console):
    job_id, _ = setup_source(console, group=22)
    console.store.db.execute("UPDATE jobs SET memory_isolated=1 WHERE id=?", (job_id,))
    console.store.db.commit()
    console.fake.add("private-fork", "777:group:22")
    console.fake.sessions["private-fork"]["fork"] = {"sessionID": "ses_current"}
    await console.login()
    index = await (await console.client.get("/api/sessions")).json()
    branch = next(item for item in index["items"] if item["id"] == "private-fork")
    assert branch["isolated"] and not branch["eligible"]
