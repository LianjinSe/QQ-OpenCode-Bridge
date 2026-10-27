from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from contextlib import suppress
from pathlib import Path

import aiohttp

from . import messages as copy
from .delivery import DeliveryError, prepare_directory
from .forms import next_field, render_form
from .forward import CHAT_RECORDS_FILENAME
from .job_state import PREPARATION_STATUSES
from .models import Attachment, Context
from .onebot import AttachmentError, DeliveryUnknown, Unavailable
from .opencode import (
    ApiError,
    ProtocolError,
    assistant_text,
    final_reply,
    public_reply,
    reply_segments,
    text_outputs,
)
from .policy import group_operation_allowed, has_full_access

log = logging.getLogger(__name__)

NETWORK_ERRORS = (aiohttp.ClientError, OSError, TimeoutError, Unavailable, DeliveryUnknown)
STATUS_LABELS = copy.STATUS_LABELS


class TaskRunner:
    def __init__(
        self,
        *,
        config,
        store,
        onebot,
        opencode,
        events,
        typing,
        conversations,
        memory,
        delivery_tools,
        reply,
        jobs_ready,
        outbox_ready,
        control_lock,
    ):
        self.config, self.store, self.onebot, self.opencode = config, store, onebot, opencode
        self.events, self.typing, self.conversations = events, typing, conversations
        self.memory, self.delivery_tools = memory, delivery_tools
        self.reply, self.jobs_ready, self.outbox_ready = reply, jobs_ready, outbox_ready
        self.control_lock = control_lock

    async def worker(self) -> None:
        while True:
            job = self.store.next_job()
            if job is None:
                self.jobs_ready.clear()
                with suppress(TimeoutError):
                    async with asyncio.timeout(1):
                        await self.jobs_ready.wait()
                continue
            await self.onebot.ready.wait()
            # A pending job from a different logged-in QQ account must not execute.
            if json.loads(job["target"])["self_id"] != self.onebot.self_id:
                log.warning("任务所属 QQ 与当前登录账号不同，保留任务并等待")
                await asyncio.sleep(5)
                continue
            try:
                if not self.opencode.available:
                    info = await self.opencode.ensure()
                    log.info("已连接 OpenCode %s", info["version"])
                await self.execute(job["id"])
            except asyncio.CancelledError:
                raise
            except NETWORK_ERRORS:
                self.events.job(job["id"], "waiting", "connection_unavailable")
                log.warning("任务等待服务恢复，job=%s", job["id"])
                await asyncio.sleep(2)
            except ApiError as exc:
                if exc.status in {401, 502, 503, 504}:
                    self.opencode.available = False
                    await asyncio.sleep(2)
                else:
                    await self.fail(job["id"], str(exc))
            except (AttachmentError, ProtocolError, ValueError, KeyError) as exc:
                await self.fail(job["id"], str(exc))

    async def prepare(self, job: dict) -> list[str]:
        paths = json.loads(job["files"] or "[]")
        attachments = [Attachment(**a) for a in json.loads(job["attachments"])]
        if any(not self._valid_download(path, job["id"]) for path in paths):
            raise AttachmentError("已保存附件缺失或路径无效，请重新发送")
        total = sum(self._download_path(p).stat().st_size for p in paths)
        for item in attachments[len(paths) :]:
            if self.store.job(job["id"])["cancel_requested"]:
                break
            directory = self.config.workdir / ".qq-attachments" / job["id"]
            if item.inline_text is not None:
                path = await asyncio.to_thread(
                    self._save_chat_records,
                    item,
                    directory,
                    self.config.max_attachment_bytes - total,
                )
            else:
                path = await self.onebot.download(
                    item,
                    directory,
                    self.config.max_attachment_bytes - total,
                    self.config.download_timeout,
                )
            total += path.stat().st_size
            paths.append(str(path.resolve()))
            self.store.update_job(job["id"], files=json.dumps(paths))
        return paths

    @staticmethod
    def _save_chat_records(item: Attachment, directory: Path, remaining: int) -> Path:
        if item.name != CHAT_RECORDS_FILENAME or item.inline_text is None:
            raise AttachmentError("生成的聊天记录附件无效")
        data = item.inline_text.encode("utf-8")
        if len(data) != item.size or len(data) > remaining:
            raise AttachmentError("聊天记录附件大小无效或超过限制")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if directory.resolve() != directory:
            raise AttachmentError("聊天记录附件目录不能是符号链接")
        destination = directory / CHAT_RECORDS_FILENAME
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=directory, prefix=".chat-records-", delete=False
            ) as f:
                temporary = Path(f.name)
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            temporary.replace(destination)
        except OSError as exc:
            raise AttachmentError("聊天记录附件保存失败") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return destination

    @staticmethod
    def _download_path(path: str) -> Path:
        return Path(path)

    def _valid_download(self, path: str, job_id: str) -> bool:
        file = self._download_path(path)
        expected = (self.config.workdir / ".qq-attachments" / job_id).resolve()
        return file.is_file() and file.resolve().parent == expected

    async def execute(self, job_id: str) -> None:
        job = self.store.job(job_id)
        context = Context(**json.loads(job["target"]))
        if job["cancel_requested"]:
            await self.cancel(job_id)
            return
        if job["status"] in {status.value for status in PREPARATION_STATUSES}:
            self.store.transition_job(job_id, "preparing")
            self.typing.wake()
            if job["status"] == "queued":
                self.events.job(job_id, "preparing", "attachment_preparation")
            paths = await self.prepare(job)
            if self.store.job(job_id)["cancel_requested"]:
                await self.cancel(job_id)
                return
            isolated = bool(job["memory_isolated"])
            session_id = job["session_id"] if isolated else self.store.session(context)
            if session_id is None:
                session_id = "ses_" + uuid.uuid4().hex
                if isolated:
                    self.store.update_job(job_id, session_id=session_id)
                else:
                    self.store.set_session(context, session_id)
            try:
                session = await self.opencode.get_session(session_id)
            except ApiError as exc:
                if exc.status != 404:
                    raise
                session = await self.opencode.create_session(session_id, context)
            if session.get("metadata", {}).get(
                "qq_bridge_context"
            ) != context.conversation_key or session.get("location", {}).get("directory") != str(
                self.config.workdir.resolve()
            ):
                raise ProtocolError("OpenCode 会话的来源或工作目录不匹配")
            if context.group_id is not None and not isolated:
                try:
                    ready = await self.opencode.prepare_shared(session_id, context, job_id)
                except (ApiError, ProtocolError):
                    self.events.job(job_id, "waiting", "session_preflight_failed")
                    await asyncio.sleep(self.config.poll_interval)
                    return
                if not ready:
                    self.events.job(job_id, "waiting", "previous_tree_not_idle")
                    await asyncio.sleep(self.config.poll_interval)
                    return
            if self.store.job(job_id)["cancel_requested"]:
                await self.cancel(job_id)
                return
            self.store.transition_job(
                job_id, "submitting", session_id=session_id, files=json.dumps(paths)
            )
            job = self.store.job(job_id)
        prepare_directory(self.config, job_id)
        await self.opencode.sync_context(job["session_id"], context, job_id)
        if self.store.job(job_id)["cancel_requested"]:
            await self.cancel(job_id)
            return
        if job["status"] == "submitting":
            await self.submit(job_id, delivery="steer" if context.group_id is None else "queue")
        await self.monitor(job_id)

    async def submit(self, job_id: str, *, delivery: str) -> None:
        job = self.store.job(job_id)
        parent_id = job["steer_parent_id"] or job_id
        if not await self.opencode.admitted(job["session_id"], job["prompt_id"]):
            files = [
                {"uri": self._download_path(item).as_uri(), "name": self._download_path(item).name}
                for item in json.loads(job["files"] or "[]")
            ]
            text, cursor = self.conversations.compose(job)
            if job["submitted_text"] is None:
                text = await self.memory.prepare(job, text)
                self.store.update_job(job_id, submitted_text=text, submit_cursor=cursor)
            if self.store.job(parent_id)["cancel_requested"]:
                return
            self.events.job(job_id, "submitting", "prompt_submission")
            try:
                await self.opencode.prompt(
                    job["session_id"], job["prompt_id"], text, files, delivery=delivery
                )
            except ApiError as exc:
                if exc.status != 409 or not await self.opencode.admitted(
                    job["session_id"], job["prompt_id"]
                ):
                    raise
        if self.store.job(parent_id)["cancel_requested"]:
            return
        self.store.acknowledge(job_id)
        self.typing.wake()
        self.events.job(job_id, "running", "prompt_admitted")

    async def submit_steers(self, job_id: str) -> None:
        parent = self.store.job(job_id)
        for job in self.store.steers(job_id, pending_only=True):
            if self.store.job(job_id)["cancel_requested"]:
                return
            try:
                self.store.update_job(job["id"], session_id=parent["session_id"])
                paths = await self.prepare(job)
                self.store.update_job(job["id"], files=json.dumps(paths))
                await self.submit(job["id"], delivery="steer")
            except ApiError as exc:
                if exc.status in {401, 502, 503, 504}:
                    raise
                self.fail_steer(job, str(exc))
            except (AttachmentError, ProtocolError, ValueError, KeyError) as exc:
                self.fail_steer(job, str(exc))

    def fail_steer(self, job: dict, reason: str) -> None:
        self.store.transition_job(job["id"], "failed", error=reason)
        self.reply(
            Context(**json.loads(job["target"])),
            copy.failure_reply(reason),
            f"failure:{job['id']}",
        )
        self.events.job(job["id"], "failed", "steer_failed")

    def turn_tail(self, job: dict, user: dict | None, messages: list[dict]):
        """Only an idle after every admitted input can finish this bridge execution."""
        if user is None or self.store.steers(job["id"], pending_only=True):
            return None, []
        delivered = {user["id"], *(item["id"] for item in messages)}
        if any(
            item["status"] == "steered" and item["prompt_id"] not in delivered
            for item in self.store.steers(job["id"])
        ):
            return None, []
        last = next(
            (
                index
                for index in range(len(messages) - 1, -1, -1)
                if messages[index]["type"] == "user"
            ),
            None,
        )
        return (messages[last], messages[last + 1 :]) if last is not None else (user, messages)

    async def process_interactions(
        self, root: str, job_id: str, context: Context, auto_allow: bool
    ) -> bool:
        permissions, forms = await self.opencode.interactions(root)
        blocked_permissions = 0
        async with self.control_lock:
            remote_keys = set()
            for kind, collection in (("permission", permissions), ("form", forms)):
                for remote in collection:
                    remote_keys.add((kind, remote["id"]))
                    item = self.store.pending(job_id, kind, remote["sessionID"], remote)
                    allow = auto_allow
                    if kind == "permission" and context.group_id is not None and not auto_allow:
                        tool_input = None
                        if remote.get("action") == "shell":
                            tool_input = await self.opencode.permission_input(remote)
                        allow = group_operation_allowed(self.config, remote, tool_input)
                    if kind == "permission" and allow:
                        try:
                            await self.opencode.permission(
                                remote["sessionID"], remote["id"], "once"
                            )
                        except ApiError as exc:
                            if exc.status != 404:
                                raise
                        self.store.update_interaction(item["code"], state="answered")
                        self.events.job(job_id, "approval", "auto_approved_once")
                        continue
                    if kind == "permission":
                        blocked_permissions += 1
                    if item["state"] != "pending":
                        continue
                    if time.time() - item["created"] > self.config.interaction_timeout:
                        self.store.transition_job(
                            job_id,
                            "cancelling",
                            cancel_requested=1,
                            error="等待授权或回答超时，任务已停止。",
                        )
                        break
                    recipient = context
                    if kind == "permission":
                        text = copy.permission_prompt(item["code"], remote)
                        if context.group_id is not None:
                            if self.config.superadmin_user_id is not None:
                                recipient = Context(
                                    context.self_id,
                                    self.config.superadmin_user_id,
                                    context.group_id,
                                )
                                text = (
                                    "这一步要请本群的超级管理员点个头呀。\n"
                                    f"发起人 QQ：{context.user_id}\n"
                                    + text
                                    + "\n管理员直接在本群回上面的指令就行啦。"
                                )
                            else:
                                text = "群里还没配置超级管理员，这一步暂时没法批准呀。\n" + text
                        version = "permission"
                    else:
                        state = json.loads(item["answers"])
                        field = next_field(remote, state)
                        if field is None:
                            await self.opencode.answer(
                                item["session_id"], item["remote_id"], state["values"]
                            )
                            self.store.update_interaction(item["code"], state="answered")
                            continue
                        text = render_form(item["code"], remote, state)
                        version = str(field["key"])
                    self.events.job(
                        job_id,
                        "waiting",
                        "permission_required" if kind == "permission" else "answer_required",
                    )
                    self.reply(recipient, text, f"interaction:{item['code']}:{version}")
            for item in self.store.pending_for(job_id):
                if (item["kind"], item["remote_id"]) not in remote_keys:
                    self.store.update_interaction(item["code"], state="answered")
        paused = bool(forms or blocked_permissions)
        if not self.store.job(job_id)["cancel_requested"]:
            self.store.transition_job(job_id, "waiting" if paused else "running")
        self.typing.wake()
        return paused

    async def monitor(self, job_id: str) -> None:
        job = self.store.job(job_id)
        root = job["session_id"]
        context = Context(**json.loads(job["target"]))
        auto_allow = has_full_access(self.config, context)
        waiting = asyncio.create_task(self.opencode.wait(root))
        previous = time.monotonic()
        paused = job["status"] == "waiting"
        try:
            while True:
                job = self.store.job(job_id)
                now = time.monotonic()
                elapsed = job["elapsed"] + (0 if paused else now - previous)
                previous = now
                self.store.update_job(job_id, elapsed=elapsed)
                if job["cancel_requested"]:
                    await self.cancel(job_id)
                    return
                await self.submit_steers(job_id)
                paused = await self.process_interactions(root, job_id, context, auto_allow)
                if self.store.job(job_id)["cancel_requested"]:
                    await self.cancel(job_id)
                    return
                if not paused and elapsed >= self.config.execution_timeout:
                    self.store.transition_job(
                        job_id,
                        "cancelling",
                        cancel_requested=1,
                        error="任务执行超时，已请求停止。",
                    )
                    await self.cancel(job_id)
                    return
                user, messages = await self.opencode.turn(root, job["prompt_id"])
                if user is not None:
                    self.forward_progress(job, context, messages)
                current_user, tail = self.turn_tail(job, user, messages)
                idle = next((m for m in reversed(tail) if m.get("type") == "idle"), None)
                outcome = idle.get("outcome") if idle else None
                if current_user is not None and not paused:
                    active = await self.opencode.active()
                    session = await self.opencode.get_session(root)
                    idle_at = session.get("time", {}).get("idle", 0)
                    if root not in active and idle_at >= current_user["time"]["created"]:
                        outcome = outcome or session.get("outcome")
                    if outcome in {"succeeded", "failed", "interrupted"} and root not in active:
                        # The turn may have completed between the history and status reads.
                        # Re-read history after observing completion to avoid an empty/stale reply.
                        user, messages = await self.opencode.turn(root, job["prompt_id"])
                        current_user, tail = self.turn_tail(job, user, messages)
                        if current_user is None or any(
                            [await self.opencode.belongs_to(sid, root) for sid in active]
                        ):
                            await asyncio.sleep(self.config.poll_interval)
                            continue
                        self.forward_progress(job, context, messages)
                        result = public_reply(final_reply(messages, outcome))
                        assistants = [m for m in messages if m.get("type") == "assistant"]
                        reply_text = None
                        artifacts = []
                        delivery_error = None
                        if outcome == "succeeded":
                            try:
                                artifacts = self.delivery_tools.artifacts(job_id)
                                if assistants and assistant_text(assistants[-1]):
                                    reply_text = self.remaining_reply(job_id, assistants[-1])
                            except (DeliveryError, OSError) as exc:
                                delivery_error = str(exc)
                                log.warning("回传文件准备失败，job=%s，原因=%s", job_id, exc)
                                result = copy.DELIVERY_PREPARE_FAILED
                        if outcome == "failed":
                            log.warning("OpenCode 任务失败，job=%s，会话=%s", job_id, root)
                        if self.store.job(job_id)["cancel_requested"]:
                            await self.cancel(job_id)
                            return
                        if self.store.steers(job_id, pending_only=True):
                            continue
                        self.events.job(job_id, "completed", outcome)
                        error = delivery_error
                        if outcome != "succeeded":
                            error = (
                                "OpenCode 任务失败"
                                if outcome == "failed"
                                else "OpenCode 任务被中断"
                            )
                        self.store.complete(
                            job_id,
                            Context(**json.loads(job["target"])),
                            result,
                            self.config.reply_chunk_size,
                            error=error,
                            artifacts=artifacts,
                            reply_text=reply_text,
                            split_reply=outcome == "succeeded" and delivery_error is None,
                        )
                        self.outbox_ready.set()
                        self.typing.wake()
                        return
                if waiting.done():
                    # wait can return before a newly admitted input starts draining.
                    # Completion is determined from this turn's persisted history instead.
                    waiting.result()
                await asyncio.sleep(self.config.poll_interval)
        finally:
            waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)

    def forward_progress(self, job: dict, context: Context, messages: list[dict]) -> None:
        assistants = [m for m in messages if m.get("type") == "assistant"]
        held = (
            assistants[-1]["id"]
            if assistants and self.delivery_tools.artifacts(job["id"])
            else None
        )
        for message_id, part_index, text, complete in text_outputs(messages):
            if message_id == held:
                continue
            # Compatibility with whole-message progress queued by the previous version.
            if self.store.has_outbox(f"progress:{job['id']}:{message_id}"):
                continue
            prefix = self.store.output_prefix(job["id"], message_id, part_index)
            if not text.startswith(prefix):
                continue
            for end, segment in reply_segments(
                text, len(prefix), self.config.reply_chunk_size, complete=complete
            ):
                self.store.put_progress(
                    context,
                    job["id"],
                    message_id,
                    part_index,
                    text[:end],
                    segment,
                    self.config.reply_chunk_size,
                )
                self.outbox_ready.set()

    def remaining_reply(self, job_id: str, message: dict) -> str:
        if self.store.has_outbox(f"progress:{job_id}:{message['id']}"):
            return ""
        remaining = []
        for part_index, part in enumerate(message.get("content", [])):
            if part.get("type") != "text" or not isinstance(part.get("text"), str):
                continue
            text = part["text"]
            prefix = self.store.output_prefix(job_id, message["id"], part_index)
            if text.startswith(prefix):
                text = text[len(prefix) :]
            remaining.append(public_reply(text))
        return "\n".join(remaining).strip()

    async def cancel(self, job_id: str) -> None:
        job = self.store.job(job_id)
        self.store.transition_job(job_id, "cancelling", cancel_requested=1)
        self.typing.wake()
        if job["session_id"]:
            permissions, forms = await self.opencode.interactions(job["session_id"])
            for item in permissions:
                with suppress(ApiError):
                    await self.opencode.permission(item["sessionID"], item["id"], "reject")
            for item in forms:
                with suppress(ApiError):
                    await self.opencode.cancel_form(item["sessionID"], item["id"])
            if not await self.opencode.stop_tree(job["session_id"]):
                await asyncio.sleep(self.config.poll_interval)
                return
        self.store.settle_interactions(job_id)
        self.store.transition_job(job_id, "cancelled")
        self.events.job(job_id, "cancelled", "task_cancelled")
        if job["error"]:
            reason = job["error"]
            if reason == "等待授权或回答超时，任务已停止。":
                text = copy.INTERACTION_TIMEOUT
            elif reason == "任务执行超时，已请求停止。":
                text = copy.EXECUTION_TIMEOUT
            else:
                text = copy.failure_reply(reason.removeprefix("任务失败并请求停止："), stopped=True)
            self.reply(Context(**json.loads(job["target"])), text, f"cancel:{job_id}")

    async def fail(self, job_id: str, reason: str) -> None:
        job = self.store.job(job_id)
        if job["session_id"] and job["status"] in {
            "submitting",
            "running",
            "waiting",
            "cancelling",
        }:
            # Preserve the serial workspace invariant until stopping is confirmed.
            self.store.transition_job(
                job_id,
                "cancelling",
                cancel_requested=1,
                error="任务失败并请求停止：" + reason,
            )
            try:
                await self.cancel(job_id)
            except NETWORK_ERRORS:
                await asyncio.sleep(2)
            return
        self.store.settle_interactions(job_id)
        self.store.transition_job(job_id, "failed", error=reason)
        self.typing.wake()
        self.reply(
            Context(**json.loads(job["target"])), copy.failure_reply(reason), f"failure:{job_id}"
        )
        self.events.job(job_id, "failed", "task_failed")
        log.warning("任务失败，job=%s", job_id)
