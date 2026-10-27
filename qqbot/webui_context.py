"""Session context accounting and explicit administrator compaction requests."""

from __future__ import annotations

import asyncio
import math
import re

from aiohttp import ClientError, web

from .models import Context
from .opencode import ApiError, ProtocolError, path_id


def token_count(value):
    return value if type(value) in {int, float} and math.isfinite(value) and value >= 0 else 0


def context_usage(info, messages, models, default_model, inbox):
    """Use one measured response, never the session's cumulative billing counters."""
    checkpoint = next((m for m in reversed(messages) if m.get("type") == "compaction"), None)
    pending = next((m for m in inbox if m.get("type") == "compaction"), None)
    compaction = None
    if pending or checkpoint:
        item = pending or checkpoint
        compaction = {
            "id": item.get("id"),
            "status": "queued" if pending else item.get("status"),
            "time": (item.get("time") or {}).get("created"),
        }

    measured = None
    for message in reversed(messages):
        # Retained older messages may still carry pre-compaction usage.
        if message.get("type") == "compaction" and message.get("status") == "completed":
            break
        if message.get("type") != "assistant" or message.get("error"):
            continue
        tokens = message.get("tokens") or {}
        cache = tokens.get("cache") or {}
        inputs = sum(
            token_count(v) for v in (tokens.get("input"), cache.get("read"), cache.get("write"))
        )
        if inputs > 0:
            measured = message
            break

    model = info.get("model") or default_model or (measured or {}).get("model")
    model_info = next(
        (
            m
            for m in models
            if model and all(m.get(k) == model.get(k) for k in ("id", "providerID"))
        ),
        {},
    )
    limit = token_count((model_info.get("limit") or {}).get("context")) or None
    used, inputs, outputs = None, None, None
    if measured:
        tokens = measured["tokens"]
        cache = tokens.get("cache") or {}
        inputs = sum(
            token_count(v) for v in (tokens.get("input"), cache.get("read"), cache.get("write"))
        )
        outputs = token_count(tokens.get("output")) + token_count(tokens.get("reasoning"))
        used = inputs + outputs
    return {
        "id": info["id"],
        "used_tokens": used,
        "input_tokens": inputs,
        "output_tokens": outputs,
        "context_limit": limit,
        "percentage": round(used / limit * 100, 2) if used is not None and limit else None,
        "model": {k: model.get(k) for k in ("id", "providerID")} if model else None,
        "usage_model": (measured or {}).get("model"),
        "measured_at": ((measured or {}).get("time") or {}).get("completed"),
        "compaction": compaction,
    }


class ContextConsole:
    def __init__(self, dashboard):
        self.dashboard = dashboard
        self.data = dashboard.data

    def routes(self):
        return [
            web.get("/api/sessions/{id}/context", self.context),
            web.post("/api/sessions/{id}/compact", self.compact),
        ]

    async def context(self, request):
        session_id = request.match_info["id"]
        async with self.data.remote_limit, asyncio.timeout(25):
            client = self.data.client()
            if not await self.data.allowed_session(client, session_id):
                raise KeyError(session_id)
            info = await client.get_session(session_id)
            try:
                messages, inbox = await asyncio.gather(
                    client.request("GET", f"/api/session/{path_id(session_id)}/context"),
                    client.inbox(session_id),
                )
            except ApiError as exc:
                if exc.status in {404, 405, 501}:
                    raise web.HTTPNotImplemented(text="当前 OpenCode 不支持上下文查询") from exc
                raise
            if not isinstance(messages, list) or not isinstance(inbox, list):
                raise ProtocolError("OpenCode 上下文响应无效")
            models, default_model = [], None
            try:
                params = {
                    "location[directory]": info.get("location", {}).get("directory")
                    or str(self.dashboard.config.workdir)
                }
                models = await client.request("GET", "/api/model", params=params)
                if not info.get("model"):
                    default_model = await client.request("GET", "/api/model/default", params=params)
            except (ApiError, ProtocolError, ClientError, TimeoutError, OSError):
                # A missing model catalogue must not hide measured usage or compaction state.
                pass
            return web.json_response(
                self.data.clean(context_usage(info, messages, models, default_model, inbox))
            )

    async def compact(self, request):
        ui = self.dashboard
        body = await ui.body(request)
        if body.get("confirm") != "compact":
            raise web.HTTPBadRequest(text="请确认压缩会话上下文")
        request_id = body.get("request_id")
        if not isinstance(request_id, str) or not re.fullmatch(
            r"msg_[A-Za-z0-9_-]{1,100}", request_id
        ):
            raise ValueError("压缩请求编号无效")
        session_id = request.match_info["id"]
        async with ui.control_lock, self.data.remote_limit:
            client = self.data.client()
            if not await self.data.allowed_session(client, session_id):
                raise KeyError(session_id)
            root_id, visited = session_id, set()
            while True:
                if root_id in visited or len(visited) >= 50:
                    raise ProtocolError("OpenCode 会话父级无效")
                visited.add(root_id)
                root = await client.get_session(root_id)
                if not root.get("parentID"):
                    break
                root_id = root["parentID"]
            entries, _ = await asyncio.to_thread(self.data.session_index)
            conversation = (root.get("metadata") or {}).get("qq_bridge_context") or entries.get(
                root_id, {}
            ).get("conversation")
            parts = (conversation or "").split(":")
            if len(parts) != 3 or parts[1] not in {"private", "group"}:
                raise web.HTTPForbidden(text="无法确认会话所属聊天")
            context = Context(
                int(parts[0]), int(parts[2]), int(parts[2]) if parts[1] == "group" else None
            )
            for active_id in await client.active():
                if await client.belongs_to(active_id, root_id):
                    raise web.HTTPConflict(text="会话或子任务仍在执行，请等待结束后压缩")
            inbox = await client.inbox(session_id)
            if inbox:
                raise web.HTTPConflict(text="会话已有待处理请求，请等待完成后再压缩")
            # Recheck after network I/O, directly before admission. Incoming work is never removed.
            if ui.store.conversation_jobs(context):
                raise web.HTTPConflict(text="这个聊天还有未完成任务，请等待完成后压缩")
            try:
                async with asyncio.timeout(20):
                    receipt = await client.request(
                        "POST",
                        f"/api/session/{path_id(session_id)}/compact",
                        body={"id": request_id},
                    )
            except ApiError as exc:
                if exc.status in {404, 405, 501}:
                    raise web.HTTPNotImplemented(text="当前 OpenCode 不支持手动压缩") from exc
                if exc.status == 409:
                    raise web.HTTPConflict(text="OpenCode 未接受压缩，请刷新会话状态") from exc
                raise
            except (ClientError, TimeoutError, OSError, ProtocolError) as exc:
                ui.audit("compaction_unconfirmed", session_id)
                raise web.HTTPServiceUnavailable(
                    text="压缩请求结果尚未确认，请刷新状态；不要重复提交"
                ) from exc
            if (
                not isinstance(receipt, dict)
                or not isinstance(receipt.get("id"), str)
                or receipt.get("type") != "compaction"
                or receipt.get("sessionID") != session_id
            ):
                raise web.HTTPServiceUnavailable(text="压缩回执未确认，请刷新状态；不要重复提交")
            self.data.cache.clear()
            ui.audit("compaction_requested", session_id)
        return web.json_response({"status": "accepted", "id": receipt["id"]}, status=202)
