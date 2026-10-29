"""Session settings, sanitized downloads, capabilities and history-bound forks."""

import asyncio
import json

import pytest
from test_webui import assistant
from test_webui_forks import setup_source

from qqbot.opencode import ApiError

pytest_plugins = ["test_webui"]


async def test_concurrent_settings_reads_do_not_exhaust_the_remote_semaphore(console):
    setup_source(console)
    await console.login()
    async with asyncio.timeout(3):
        responses = await asyncio.gather(
            *[console.client.get("/api/sessions/ses_current/settings") for _ in range(2)]
        )
    assert all(r.status == 200 for r in responses)


async def test_models_and_variants_are_whitelisted_and_apply_only_to_selected_session(console):
    _, context = setup_source(console)
    console.fake.add("other", "777:private:12")
    console.fake.models[0].update(
        variants=[{"id": "max", "body": {"private": "private-model-body"}}],
        headers={"Authorization": "private-model-header"},
    )
    headers = await console.login()
    settings = await (await console.client.get("/api/sessions/ses_current/settings")).json()
    assert settings["models"][0]["variants"] == ["max"]
    assert "private-model-" not in json.dumps(settings)
    ref = {"id": "test-model", "providerID": "test", "variant": "max"}
    response = await console.client.post(
        "/api/sessions/ses_current/model",
        headers=headers,
        json={
            "confirm": "model",
            "model": ref,
            "expected_current": "ses_current",
            "expected_model": None,
        },
    )
    assert response.status == 200
    assert console.fake.sessions["ses_current"]["model"] == ref
    assert console.fake.sessions["other"].get("model") is None
    assert console.store.session(context) == "ses_current"
    assert not console.fake.forks


@pytest.mark.parametrize("variant", ["nonexistent", [], None])
async def test_model_rejects_unknown_or_malformed_variants(console, variant):
    setup_source(console)
    headers = await console.login()
    response = await console.client.post(
        "/api/sessions/ses_current/model",
        headers=headers,
        json={
            "confirm": "model",
            "model": {"id": "test-model", "providerID": "test", "variant": variant},
            "expected_current": "ses_current",
            "expected_model": None,
        },
    )
    assert response.status == 400
    assert not console.fake.mutations


async def test_model_change_rejects_busy_work_and_stale_model_or_mapping(console):
    setup_source(console)
    headers = await console.login()
    body = {
        "confirm": "model",
        "model": {"id": "test-model", "providerID": "test", "variant": "default"},
        "expected_current": "ses_current",
        "expected_model": None,
    }
    console.fake.sessions["ses_current"]["model"] = {"id": "old", "providerID": "test"}
    assert (
        await console.client.post("/api/sessions/ses_current/model", headers=headers, json=body)
    ).status == 409
    body["expected_model"] = console.fake.sessions["ses_current"]["model"]
    console.fake.active_ids = {"ses_current": {}}
    assert (
        await console.client.post("/api/sessions/ses_current/model", headers=headers, json=body)
    ).status == 409
    console.fake.active_ids = {}
    console.job(status="queued")
    assert (
        await console.client.post("/api/sessions/ses_current/model", headers=headers, json=body)
    ).status == 409
    assert not console.fake.mutations


async def test_model_selection_is_rechecked_after_remote_preflight(console):
    setup_source(console)

    async def active():
        console.fake.sessions["ses_current"]["model"] = {"id": "newer", "providerID": "test"}
        return {}

    console.fake.active = active
    headers = await console.login()
    response = await console.client.post(
        "/api/sessions/ses_current/model",
        headers=headers,
        json={
            "confirm": "model",
            "model": {"id": "test-model", "providerID": "test"},
            "expected_current": "ses_current",
            "expected_model": None,
        },
    )
    assert response.status == 409
    assert not console.fake.mutations


async def test_rename_archive_restore_preserves_history_and_protects_current_mapping(console):
    _, context = setup_source(console)
    console.fake.add("old", context.conversation_key)
    console.fake.messages["old"] = [assistant("msg_old")]
    headers = await console.login()

    async def properties(id, **changes):
        return await console.client.post(
            f"/api/sessions/{id}/properties",
            headers=headers,
            json={"confirm": "properties", "expected_current": "ses_current", **changes},
        )

    assert (await properties("ses_current", archived=True)).status == 409
    assert (await properties("old", title="已验证方案")).status == 200
    assert (await properties("old", archived=True)).status == 200
    assert console.fake.messages["old"][0]["id"] == "msg_old"
    result = await (await console.client.get("/api/sessions")).json()
    assert next(item for item in result["items"] if item["id"] == "old")["archived"]
    response = await console.client.post(
        "/api/mappings",
        headers=headers,
        json={
            "confirm": "switch",
            "conversation": context.conversation_key,
            "session_id": "old",
            "expected_current": "ses_current",
        },
    )
    assert response.status == 409
    assert (await properties("old", archived=False)).status == 200
    assert console.fake.sessions["old"]["title"] == "已验证方案"
    assert console.store.session(context) == "ses_current"


async def test_target_archive_is_rechecked_before_switch(console):
    _, context = setup_source(console)
    console.fake.add("old", context.conversation_key)

    async def active():
        console.fake.sessions["old"]["archived"] = True
        return {}

    console.fake.active = active
    headers = await console.login()
    response = await console.client.post(
        "/api/mappings",
        headers=headers,
        json={
            "confirm": "switch",
            "conversation": context.conversation_key,
            "session_id": "old",
            "expected_current": "ses_current",
        },
    )
    assert response.status == 409
    assert console.store.session(context) == "ses_current"


async def test_export_body_excludes_tools_reasoning_and_full_json_redacts_credentials(console):
    setup_source(console)
    result = assistant("msg_result")
    result["content"] = [
        {"type": "text", "text": "最终正文"},
        {"type": "reasoning", "text": "private-thought"},
        {
            "type": "tool",
            "name": "read",
            "state": {
                "status": "completed",
                "input": {"password": "private-password"},
                "content": [{"type": "text", "text": "napcat-test-secret"}],
            },
        },
    ]
    console.fake.messages["ses_current"] = [
        {"id": "msg_user", "type": "user", "text": "用户要求"},
        result,
    ]
    console.fake.sessions["ses_current"]["metadata"]["private"] = "private-config"
    await console.login()
    response = await console.client.get("/api/sessions/ses_current/export")
    assert response.status == 200 and "attachment" in response.headers["Content-Disposition"]
    text = await response.text()
    assert "最终正文" in text and "用户要求" in text
    assert "private-thought" not in text and "read" not in text
    full = await console.client.get("/api/sessions/ses_current/export?format=json&scope=full")
    content = await full.text()
    assert full.status == 200 and "private-thought" in content and '"name": "read"' in content
    assert all(
        value not in content
        for value in ["private-password", "private-config", "napcat-test-secret"]
    )
    assert not console.fake.mutations


async def test_management_and_exports_require_auth_csrf_and_bridge_scope(console):
    setup_source(console)
    for path in [
        "/api/capabilities",
        "/api/sessions/ses_current/settings",
        "/api/sessions/ses_current/export",
    ]:
        assert (await console.client.get(path)).status == 401
    headers = await console.login()
    assert (await console.client.post("/api/sessions/ses_current/model", json={})).status == 403
    console.fake.add("foreign")
    for path in ["settings", "export"]:
        assert (await console.client.get(f"/api/sessions/foreign/{path}")).status == 404
    assert (
        await console.client.post(
            "/api/sessions/foreign/properties",
            headers=headers,
            json={"confirm": "properties", "title": "no"},
        )
    ).status == 404


async def test_legacy_group_member_history_does_not_become_an_editable_shared_mapping(console):
    job_id, _ = setup_source(console, group=22)
    console.store.db.execute(
        "UPDATE jobs SET conversation=? WHERE id=?", ("777:group:22:11", job_id)
    )
    console.store.db.commit()
    await console.login()
    response = await console.client.get("/api/sessions/ses_current/settings")
    assert response.status == 409
    assert not console.fake.mutations


async def test_capability_panel_projects_only_public_fields_and_separates_native_plugins(console):
    console.fake.capabilities.update(
        {
            "/api/plugin": [
                {
                    "id": "qq.memory",
                    "source": {"type": "local", "path": "/private/plugin"},
                    "features": {"server": True},
                    "state": {"status": "failed", "error": "private-error-token"},
                    "options": {"token": "private-plugin-token"},
                }
            ],
            "/api/skill": [
                {
                    "id": "skill",
                    "name": "技能",
                    "description": "说明",
                    "content": "private-skill-content",
                }
            ],
            "/api/agent": [
                {"id": "build", "name": "Build", "hidden": False, "system": "private-system-prompt"}
            ],
            "/api/mcp": [
                {
                    "name": "server",
                    "status": {"status": "connected"},
                    "credentials": "private-mcp-key",
                }
            ],
            "/api/websearch/provider": [{"id": "deepseek", "name": "DeepSeek"}],
        }
    )
    console.fake.config_documents = [
        {
            "type": "document",
            "info": {
                "websearch": {"provider": "deepseek"},
                "providers": {"private-config-key": "private-provider-key"},
            },
        }
    ]
    await console.login()
    response = await console.client.get("/api/capabilities")
    result = await response.json()
    assert result["search_provider"] == "deepseek"
    assert result["sections"]["mcp"]["items"][0]["status"] == "connected"
    assert result["sections"]["plugins"]["items"][0]["id"] == "qq.memory"
    assert "private-" not in json.dumps(result)
    assert not console.fake.mutations


async def test_capability_failure_is_not_reported_as_an_empty_configured_list(console):
    original = console.fake.request

    async def request(method, path, **kwargs):
        if path == "/api/plugin":
            raise ApiError(503, "private-error-secret")
        return await original(method, path, **kwargs)

    console.fake.request = request
    await console.login()
    result = await (await console.client.get("/api/capabilities")).json()
    assert result["sections"]["plugins"]["available"] is False
    assert result["sections"]["skills"]["available"] is True
    assert "private-" not in json.dumps(result)


async def test_fork_before_message_from_a_historical_branch_preserves_current_mapping_checks(
    console,
):
    _, context = setup_source(console)
    console.fake.messages["ses_current"] = [
        {"id": "msg_one", "type": "user", "text": "第一条"},
        assistant("msg_two"),
        {"id": "msg_three", "type": "user", "text": "另一种方案"},
    ]
    console.fake.add("mapped", context.conversation_key)
    console.store.switch_session(context, "mapped")
    headers = await console.login()
    body = {
        "confirm": "fork",
        "conversation": context.conversation_key,
        "expected_current": "mapped",
        "request_id": "fork_at_message",
        "before": "msg_three",
    }
    response = await console.client.post(
        "/api/sessions/ses_current/fork", headers=headers, json=body
    )
    assert response.status == 201
    branch = (await response.json())["session_id"]
    assert [m["id"] for m in console.fake.messages[branch]] == ["msg_one", "msg_two"]
    assert console.store.session(context) == branch
    assert len(console.fake.messages["ses_current"]) == 3


async def test_fork_rejects_message_from_another_session_without_creating(console):
    _, context = setup_source(console)
    headers = await console.login()
    response = await console.client.post(
        "/api/sessions/ses_current/fork",
        headers=headers,
        json={
            "confirm": "fork",
            "conversation": context.conversation_key,
            "expected_current": "ses_current",
            "request_id": "foreign_message",
            "before": "msg_foreign",
        },
    )
    assert response.status == 400
    assert not console.fake.forks
