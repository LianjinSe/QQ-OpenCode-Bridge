import asyncio
import logging
import time
from dataclasses import replace

import pytest
from conftest import eventually, message

from qqbot.bridge import Bridge
from qqbot.config import Config, ConfigError
from qqbot.forms import AnswerError, add_answer, next_field
from qqbot.logging_utils import RedactingFormatter
from qqbot.models import Attachment, Context
from qqbot.opencode import final_reply
from qqbot.store import Store


def test_store_schema_and_recovery_are_explicit_when_requested(tmp_path):
    store = Store(tmp_path / "state.sqlite", initialize=False)
    try:
        assert not store.initialized
        assert (
            store.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'"
            ).fetchone()
            is None
        )
        store.initialize()
        assert store.initialized
        store.initialize()
        assert (
            store.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'"
            ).fetchone()
            is not None
        )
    finally:
        store.close()


def test_task_state_transition_rejects_skipping_preparation(tmp_path):
    from qqbot.models import Context

    store = Store(tmp_path / "state.sqlite")
    try:
        job_id = store.enqueue(Context(777, 11), "任务", [])
        with pytest.raises(ValueError, match="Illegal job status transition"):
            store.transition_job(job_id, "submitting")
        assert store.job(job_id)["status"] == "queued"
        store.transition_job(job_id, "preparing")
        store.transition_job(job_id, "submitting")
        assert store.job(job_id)["status"] == "submitting"
        store.transition_job(job_id, "running")
        store.transition_job(job_id, "failed")
        with pytest.raises(ValueError, match="Illegal job status transition"):
            store.transition_job(job_id, "running")
        with pytest.raises(ValueError, match="Unknown job status transition"):
            store.transition_job(job_id, "unknown")
    finally:
        store.close()


async def test_restart_recovers_waiting_permission_without_duplicate_generation(harness):
    async with harness() as (bridge, nap, op):
        op.mode = "permission"
        await nap.emit(message("重启后继续"))
        await eventually(lambda: bool(nap.sent))
        job = bridge.store.latest(Context(777, 11))
        code = bridge.store.pending_for(job["id"])[0]["code"]
        bridge.task.cancel()
        await asyncio.gather(bridge.task, return_exceptions=True)
        await bridge.onebot.disconnect()
        bridge.store.close()
        restored_store = Store(bridge.config.state_db)
        restored = Bridge(bridge.config, restored_store, bridge.onebot, bridge.opencode)
        task = asyncio.create_task(restored.run())
        try:
            await asyncio.wait_for(bridge.onebot.ready.wait(), 3)
            await nap.emit(message(f"/approve {code}"))
            await eventually(lambda: restored_store.job(job["id"])["status"] == "done")
            assert len(op.prompts) == 1
            assert sum("/approve " in text for text in nap.texts()) == 1
            assert sum("回复：重启后继续" in text for text in nap.texts()) == 1
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await bridge.onebot.disconnect()
            restored_store.close()


def test_restart_marks_inflight_output_uncertain_and_never_requeues(tmp_path):
    path = tmp_path / "state.sqlite"
    context = Context(777, 11)
    store = Store(path)
    job_id = store.enqueue(context, "test", [])
    store.transition_job(job_id, "preparing")
    store.transition_job(job_id, "submitting")
    store.transition_job(job_id, "running")
    store.complete(job_id, context, "a" * 100, 20)
    item = store.next_outbox(777)
    store.update_outbox(item["id"], "sending")
    store.close()
    reopened = Store(path)
    try:
        assert reopened.job(job_id)["status"] == "send_uncertain"
        assert reopened.next_outbox(777) is None
        assert reopened.next_job() is None
    finally:
        reopened.close()


def test_context_scoped_expiry_and_single_process_lock(tmp_path):
    path = tmp_path / "state.sqlite"
    store = Store(path)
    try:
        first, second = Context(777, 11, 22), Context(777, 12, 22)
        store.stage(first, [Attachment("a", "a.txt")], ttl=0.001, limit=5)
        store.stage(second, [Attachment("b", "b.txt")], ttl=60, limit=5)
        time.sleep(0.01)
        assert store.staged(first) == []
        store.clear_staging(first)
        assert store.staged(second)[0].reference == "b"
        with pytest.raises(RuntimeError, match="已有桥接进程"):
            Store(path)
    finally:
        store.close()


def test_config_rejects_open_access_and_keeps_credentials_out_of_repr(monkeypatch, tmp_path):
    for key in ("ALLOWED_USERS", "NAPCAT_TOKEN", "OPENCODE_URL", "SUPERADMIN_USER_ID"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ConfigError, match="ALLOWED_USERS"):
        Config.from_env(tmp_path / "missing.env")
    monkeypatch.setenv("ALLOWED_USERS", "11,12")
    monkeypatch.setenv("ALLOWED_GROUPS", "")
    monkeypatch.setenv("NAPCAT_TOKEN", "token-that-must-not-appear")
    config = Config.from_env(tmp_path / "missing.env")
    assert config.allowed_groups == frozenset()
    assert config.allowed_users == frozenset({11, 12})
    assert config.napcat_token not in repr(config)
    with pytest.raises(ConfigError, match="NAPCAT_WS_URL"):
        replace(config, napcat_url="ws://host:3001?access_token=secret").validate()


def test_logging_redacts_tokens_in_message_exception_and_url():
    formatter = RedactingFormatter()
    formatter.add_secret("actual-token")
    try:
        raise RuntimeError("credential=actual-token")
    except RuntimeError as error:
        record = logging.LogRecord(
            "test",
            logging.ERROR,
            "",
            0,
            "url=http://host?token=other-token Bearer actual-token",
            (),
            (type(error), error, error.__traceback__),
        )
    output = formatter.format(record)
    assert "actual-token" not in output
    assert "other-token" not in output
    assert "<redacted>" in output


def test_conditional_optional_form_validation():
    form = {
        "fields": [
            {"key": "enabled", "type": "boolean"},
            {
                "key": "count",
                "type": "integer",
                "minimum": 1,
                "maximum": 3,
                "when": [{"key": "enabled", "op": "eq", "value": True}],
            },
            {"key": "note", "type": "string", "required": False},
        ]
    }
    state = add_answer(form, {}, "是")
    with pytest.raises(AnswerError, match="范围"):
        add_answer(form, state, "4")
    state = add_answer(form, state, "2")
    state = add_answer(form, state, "/skip")
    assert next_field(form, state) is None
    assert state["values"] == {"enabled": True, "count": 2}
    disabled = add_answer(form, {}, "否")
    assert next_field(form, disabled)["key"] == "note"


def test_successful_provider_retry_does_not_report_an_old_error():
    messages = [
        {"type": "assistant", "error": {"type": "Timeout", "message": "retrying"}},
        {"type": "assistant", "content": [{"type": "text", "text": "重试成功"}]},
    ]
    assert final_reply(messages, "succeeded") == "重试成功"
    assert "还没做完" in final_reply(messages, "failed")
