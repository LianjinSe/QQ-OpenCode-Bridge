import asyncio
from dataclasses import replace

import pytest
from conftest import eventually, message

from qqbot.bridge import Bridge
from qqbot.config import Config, ConfigError
from qqbot.models import Context
from qqbot.store import Store


def typing_calls(nap):
    return [item["params"] for item in nap.actions if item["action"] == "set_input_status"]


async def test_private_task_starts_refreshes_and_clears_typing(harness):
    async with harness(typing_refresh_interval=0.05) as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("处理文档"))
        await eventually(lambda: len(op.prompts) == 1)
        await eventually(lambda: len(typing_calls(nap)) >= 2)
        assert all(call == {"user_id": "11", "event_type": 1} for call in typing_calls(nap))
        op.finish(op.prompts[0]["sessionID"], "处理完成。")
        await eventually(lambda: bridge.store.latest(Context(777, 11))["status"] == "done")
        await eventually(lambda: typing_calls(nap)[-1] == {"user_id": "11", "event_type": 0})
        assert nap.texts() == ["处理完成。"]


async def test_progress_message_restores_typing_before_the_refresh_interval(harness):
    async with harness(typing_refresh_interval=30) as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("分段分析文档"))
        await eventually(lambda: bool(op.prompts) and bool(typing_calls(nap)))
        sid = op.prompts[0]["sessionID"]
        count = len(typing_calls(nap))
        op.messages[sid].append(
            {
                "id": "msg_typing_progress",
                "type": "assistant",
                "content": [{"type": "text", "text": "我先看看文档。\n\n正在分析"}],
            }
        )
        await eventually(lambda: "我先看看文档。" in nap.texts())
        await eventually(lambda: len(typing_calls(nap)) > count)
        assert typing_calls(nap)[-1]["event_type"] == 1
        assert bridge.store.latest(Context(777, 11))["status"] == "running"


@pytest.mark.parametrize("kind", ["permission", "form"])
async def test_typing_pauses_for_user_input_and_resumes_after_the_answer(harness, kind):
    async with harness(typing_refresh_interval=30) as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("处理需要确认的文档"))
        await eventually(lambda: bool(op.prompts) and bool(typing_calls(nap)))
        sid = op.prompts[0]["sessionID"]
        remote_id = "request_typing_test"
        op.gates[remote_id] = asyncio.Event()
        if kind == "permission":
            op.permissions[remote_id] = {
                "id": remote_id,
                "sessionID": sid,
                "action": "write",
                "resources": ["document.txt"],
            }
        else:
            op.forms[remote_id] = {
                "id": remote_id,
                "sessionID": sid,
                "title": "需要补充信息",
                "fields": [{"key": "description", "type": "string", "title": "修改要求"}],
            }
        context = Context(777, 11)
        await eventually(lambda: bridge.store.latest(context)["status"] == "waiting")
        await eventually(lambda: typing_calls(nap)[-1]["event_type"] == 0)
        job = bridge.store.latest(context)
        code = bridge.store.pending_for(job["id"])[0]["code"]
        command = f"/approve {code}" if kind == "permission" else f"/answer {code} 修改标题"
        await nap.emit(message(command))
        await eventually(lambda: bridge.store.job(job["id"])["status"] == "running")
        await eventually(lambda: typing_calls(nap)[-1]["event_type"] == 1)
        op.finish(sid, "处理完成。")
        await eventually(lambda: bridge.store.job(job["id"])["status"] == "done")
        await eventually(lambda: typing_calls(nap)[-1]["event_type"] == 0)


async def test_queued_private_user_is_not_marked_typing_until_their_turn(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("第一个人的任务", user=11))
        await eventually(lambda: bool(op.prompts) and bool(typing_calls(nap)))
        await nap.emit(message("第二个人的任务", user=12))
        await eventually(lambda: bridge.store.latest(Context(777, 12)) is not None)
        assert bridge.store.latest(Context(777, 12))["status"] == "queued"
        assert len(op.prompts) == 1
        assert all(call["user_id"] == "11" for call in typing_calls(nap))
        op.finish(op.prompts[0]["sessionID"])
        await eventually(lambda: len(op.prompts) == 2)
        await eventually(lambda: {"user_id": "12", "event_type": 1} in typing_calls(nap))
        assert {"user_id": "11", "event_type": 0} in typing_calls(nap)
        await nap.emit(message("/cancel", user=12))
        await eventually(lambda: bridge.store.latest(Context(777, 12))["status"] == "cancelled")
        await eventually(lambda: typing_calls(nap)[-1] == {"user_id": "12", "event_type": 0})


@pytest.mark.parametrize("enabled,group", [(False, None), (True, 22)])
async def test_disabled_and_group_tasks_do_not_send_private_typing(harness, enabled, group):
    async with harness(typing_status_enabled=enabled) as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("处理文档", group=group, at=group is not None))
        await eventually(lambda: bool(op.prompts))
        await nap.emit(message("/status", group=group, at=group is not None))
        await eventually(lambda: bool(nap.sent))
        assert typing_calls(nap) == []
        op.finish(op.prompts[0]["sessionID"])
        await eventually(lambda: bridge.store.latest(Context(777, 11, group))["status"] == "done")
        assert typing_calls(nap) == []


@pytest.mark.parametrize("outcome", ["failed", "cancel", "timeout"])
async def test_typing_is_cleared_on_failure_cancellation_and_timeout(harness, outcome):
    async with harness(execution_timeout=0.3 if outcome == "timeout" else 5) as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("执行任务"))
        await eventually(lambda: bool(op.prompts) and bool(typing_calls(nap)))
        if outcome == "failed":
            op.finish(op.prompts[0]["sessionID"], outcome="failed")
        elif outcome == "cancel":
            await nap.emit(message("/cancel"))
        expected = "failed" if outcome == "failed" else "cancelled"
        await eventually(lambda: bridge.store.latest(Context(777, 11))["status"] == expected)
        await eventually(lambda: typing_calls(nap)[-1]["event_type"] == 0)


@pytest.mark.parametrize("failure", ["api", "native"])
async def test_typing_api_failure_does_not_fail_the_task(harness, failure):
    async with harness() as (bridge, nap, op):
        nap.typing_error = failure == "api"
        nap.typing_result = {"result": 1} if failure == "native" else {}
        await nap.emit(message("接口不可用也要正常回复"))
        await eventually(lambda: bridge.store.latest(Context(777, 11)) is not None)
        await eventually(lambda: bridge.store.latest(Context(777, 11))["status"] == "done")
        assert nap.texts() == ["回复：接口不可用也要正常回复"]
        assert 1 <= len(typing_calls(nap)) <= 2
        assert not bridge.task.done()


async def test_typing_restores_after_a_websocket_reconnect(harness):
    async with harness(typing_refresh_interval=30, execution_timeout=10) as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("重连后继续显示输入状态"))
        await eventually(lambda: bool(op.prompts) and bool(typing_calls(nap)))
        previous = bridge.onebot.ws
        count = len(typing_calls(nap))
        await nap.ws.close()
        await eventually(lambda: bridge.onebot.ready.is_set() and bridge.onebot.ws is not previous)
        await eventually(lambda: len(typing_calls(nap)) > count)
        assert typing_calls(nap)[-1]["event_type"] == 1
        op.finish(op.prompts[0]["sessionID"])
        await eventually(lambda: bridge.store.latest(Context(777, 11))["status"] == "done")
        await eventually(lambda: typing_calls(nap)[-1]["event_type"] == 0)


async def test_typing_restores_for_a_running_task_after_bridge_restart(harness):
    async with harness(typing_refresh_interval=30) as (bridge, nap, op):
        op.mode = "stalled"
        await nap.emit(message("重启后继续任务"))
        await eventually(lambda: bool(op.prompts) and bool(typing_calls(nap)))
        sid = op.prompts[0]["sessionID"]
        job = bridge.store.latest(Context(777, 11))
        bridge.task.cancel()
        await asyncio.gather(bridge.task, return_exceptions=True)
        await bridge.onebot.disconnect()
        bridge.store.close()
        count = len(typing_calls(nap))
        store = Store(bridge.config.state_db)
        restored = Bridge(bridge.config, store, bridge.onebot, bridge.opencode)
        task = asyncio.create_task(restored.run())
        try:
            await eventually(lambda: len(typing_calls(nap)) > count)
            assert typing_calls(nap)[-1]["event_type"] == 1
            op.finish(sid)
            await eventually(lambda: store.job(job["id"])["status"] == "done")
            await eventually(lambda: typing_calls(nap)[-1]["event_type"] == 0)
            assert len(op.prompts) == 1
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await bridge.onebot.disconnect()
            store.close()


async def test_typing_transport_refuses_groups_other_accounts_and_offline_calls(harness):
    async with harness() as (bridge, nap, _):
        assert not await bridge.onebot.set_typing(Context(777, 11, 22), True)
        assert not await bridge.onebot.set_typing(Context(888, 11), True)
        bridge.onebot.online = False
        try:
            assert not await bridge.onebot.set_typing(Context(777, 11), True)
        finally:
            bridge.onebot.online = True
        assert typing_calls(nap) == []


def test_typing_configuration_is_validated(monkeypatch, tmp_path):
    monkeypatch.setenv("NAPCAT_TOKEN", "test-token")
    monkeypatch.setenv("ALLOWED_USERS", "11")
    monkeypatch.setenv("SUPERADMIN_USER_ID", "")
    monkeypatch.setenv("TYPING_STATUS_ENABLED", "false")
    monkeypatch.setenv("TYPING_REFRESH_INTERVAL", "2.5")
    cfg = Config.from_env(tmp_path / "absent.env")
    assert cfg.typing_status_enabled is False
    assert cfg.typing_refresh_interval == 2.5
    with pytest.raises(ConfigError, match="TYPING_REFRESH_INTERVAL"):
        replace(cfg, typing_refresh_interval=0).validate()
    monkeypatch.setenv("TYPING_STATUS_ENABLED", "sometimes")
    with pytest.raises(ConfigError, match="TYPING_STATUS_ENABLED"):
        Config.from_env(tmp_path / "absent.env")
