"""Explicit session forks; preserve originals and never repeat an uncertain creation."""

from __future__ import annotations

import asyncio
import re
import time

from aiohttp import ClientError, web

from .models import Context
from .opencode import ApiError, ProtocolError, path_id
from .policy import IDENTITY_ENTRY_KEY, metadata_for, permissions_for


class SessionConsole:
    def __init__(self, dashboard):
        self.dashboard = dashboard

    def routes(self):
        return [
            web.post("/api/sessions/{id}/fork", self.fork),
            web.get("/api/sessions/{id}/settings", self.settings),
            web.post("/api/sessions/{id}/model", self.model),
            web.post("/api/sessions/{id}/properties", self.properties),
        ]

    async def managed(self, session_id):
        ui = self.dashboard
        inventory = await ui.data.sessions(fresh=True)
        item = next((s for s in inventory["items"] if s["id"] == session_id), None)
        if item is None:
            raise KeyError(session_id)
        mapping = next(
            (m for m in inventory["mappings"] if m["conversation"] == item["conversation"]), None
        )
        if mapping is None:
            raise web.HTTPConflict(text="这个历史会话没有可管理的 QQ 映射，仍可查看和导出记录")
        client = ui.data.client()
        info = await client.get_session(session_id)
        if (
            info.get("parentID")
            or info.get("metadata", {}).get("qq_bridge_context") != item["conversation"]
            or info.get("location", {}).get("directory") != str(ui.config.workdir.resolve())
        ):
            raise web.HTTPForbidden(text="会话来源或工作目录不匹配")
        return client, info, item, mapping

    async def models(self, client):
        raw = await client.request(
            "GET", "/api/model", params={"location[directory]": str(self.dashboard.config.workdir)}
        )
        if not isinstance(raw, list):
            raise ProtocolError("模型目录响应无效")
        return [
            {
                "id": m["id"],
                "providerID": m["providerID"],
                "name": m.get("name", m["id"]),
                "limit": {k: m.get("limit", {}).get(k) for k in ("context", "output")},
                "variants": [
                    v["id"]
                    for v in m.get("variants", [])
                    if isinstance(v, dict) and isinstance(v.get("id"), str)
                ],
            }
            for m in raw
            if isinstance(m, dict)
            and m.get("enabled", True)
            and isinstance(m.get("id"), str)
            and isinstance(m.get("providerID"), str)
        ]

    async def settings(self, request):
        ui = self.dashboard
        async with asyncio.timeout(25):
            client, info, item, mapping = await self.managed(request.match_info["id"])
            catalog = await self.models(client)
            current = info.get("model")
            if current is None:
                default = await client.request(
                    "GET",
                    "/api/model/default",
                    params={"location[directory]": str(ui.config.workdir)},
                )
                current = {k: default.get(k) for k in ("id", "providerID")} if default else None
            return web.json_response(
                ui.data.clean(
                    {
                        "id": info["id"],
                        "title": info.get("title", info["id"]),
                        "selection": {
                            k: info["model"].get(k)
                            for k in ("id", "providerID", "variant")
                            if k in info["model"]
                        }
                        if info.get("model")
                        else None,
                        "model": {k: current.get(k) for k in ("id", "providerID", "variant")}
                        if current
                        else None,
                        "models": catalog,
                        "conversation": item["conversation"],
                        "expected_current": mapping["session_id"],
                        "current": mapping["session_id"] == info["id"],
                        "scope": "group_isolated"
                        if item.get("isolated")
                        else "group_shared"
                        if mapping["target"].get("group_id")
                        else "private",
                        "archived": bool(
                            info.get("archived") or info.get("time", {}).get("archived")
                        ),
                    }
                )
            )

    async def model(self, request):
        ui = self.dashboard
        body = await ui.body(request)
        ref = body.get("model")
        if (
            body.get("confirm") != "model"
            or not isinstance(ref, dict)
            or set(ref) - {"id", "providerID", "variant"}
            or not all(
                isinstance(ref.get(k), str) and 0 < len(ref[k]) <= 200 for k in ("id", "providerID")
            )
            or (
                "variant" in ref
                and (not isinstance(ref["variant"], str) or len(ref["variant"]) > 200)
            )
        ):
            raise ValueError("模型参数无效")
        async with ui.control_lock, asyncio.timeout(25):
            client, info, _, mapping = await self.managed(request.match_info["id"])
            catalog = await self.models(client)
            selected = next(
                (
                    m
                    for m in catalog
                    if m["id"] == ref.get("id") and m["providerID"] == ref.get("providerID")
                ),
                None,
            )
            if selected is None or ref.get("variant", "default") not in {
                "default",
                *selected["variants"],
            }:
                raise web.HTTPBadRequest(text="请选择当前可用的模型及其实际提供的思考档位")
            if info.get("model") != body.get("expected_model"):
                raise web.HTTPConflict(text="会话模型已有变化，请刷新后重试")
            context = Context(**mapping["target"])
            await self.idle(
                client, context, {info["id"], mapping["session_id"]}, body.get("expected_current")
            )
            latest = await client.get_session(info["id"])
            if latest.get("model") != body.get("expected_model"):
                raise web.HTTPConflict(text="会话模型已有变化，请刷新后重试")
            if (
                latest.get("metadata", {}).get("qq_bridge_context") != context.conversation_key
                or latest.get("location", {}).get("directory") != str(ui.config.workdir.resolve())
                or ui.store.conversation_jobs(context)
                or ui.store.session(context) != body.get("expected_current")
            ):
                raise web.HTTPConflict(text="会话来源、任务或映射已有变化，请刷新后重试")
            try:
                await client.request(
                    "POST", f"/api/session/{path_id(info['id'])}/model", body={"model": ref}
                )
            except (ClientError, TimeoutError, OSError, ProtocolError) as exc:
                raise web.HTTPServiceUnavailable(
                    text="模型切换结果未确认，请刷新查看，不要重复提交"
                ) from exc
            ui.data.cache.clear()
            ui.audit("session_model_changed", info["id"])
        return web.json_response({"ok": True})

    async def properties(self, request):
        ui = self.dashboard
        body = await ui.body(request)
        if body.get("confirm") != "properties":
            raise web.HTTPBadRequest(text="请确认修改会话")
        changes = {}
        if "title" in body:
            if not isinstance(body["title"], str) or not 1 <= len(body["title"].strip()) <= 120:
                raise ValueError("会话名称应为 1 至 120 个字符")
            changes["title"] = body["title"].strip()
        if "archived" in body:
            if type(body["archived"]) is not bool:
                raise ValueError("归档参数无效")
            changes["archived"] = body["archived"]
        if not changes:
            raise ValueError("没有需要修改的属性")
        async with ui.control_lock, asyncio.timeout(25):
            client, info, _, mapping = await self.managed(request.match_info["id"])
            if changes.get("archived") and mapping["session_id"] == info["id"]:
                raise web.HTTPConflict(text="请先切换到其他会话，再归档当前会话")
            await self.idle(
                client,
                Context(**mapping["target"]),
                {info["id"], mapping["session_id"]},
                body.get("expected_current"),
            )
            try:
                await client.request("PATCH", f"/api/session/{path_id(info['id'])}", body=changes)
            except (ClientError, TimeoutError, OSError, ProtocolError) as exc:
                raise web.HTTPServiceUnavailable(text="会话修改结果未确认，请刷新查看") from exc
            ui.data.cache.clear()
            ui.audit("session_properties_changed", info["id"])
        return web.json_response({"ok": True})

    async def idle(self, client, context, session_ids, expected):
        ui = self.dashboard
        active = await client.active()
        for session_id in session_ids - {None}:
            if await client.inbox(session_id):
                raise web.HTTPConflict(text="会话还有待处理请求，请等待完成后操作")
            for active_id in active:
                if await client.belongs_to(active_id, session_id):
                    raise web.HTTPConflict(text="会话或子任务仍在执行，请等待结束后操作")
        # Recheck local state after all remote reads, without another await before the write.
        if ui.store.conversation_jobs(context):
            raise web.HTTPConflict(text="这个聊天还有未完成任务，请等待完成后操作")
        if ui.store.session(context) != expected:
            raise web.HTTPConflict(text="当前映射已有变化，请刷新后重试")

    async def fork(self, request):
        ui = self.dashboard
        body = await ui.body(request)
        source_id, conversation = request.match_info["id"], body.get("conversation")
        request_id, expected = body.get("request_id"), body.get("expected_current")
        title = body.get("title", "")
        before = body.get("before")
        if body.get("confirm") != "fork":
            raise web.HTTPBadRequest(text="请确认创建分支并切换映射")
        if (
            not isinstance(request_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", request_id)
            or not isinstance(conversation, str)
            or (expected is not None and not isinstance(expected, str))
            or (
                before is not None
                and (
                    not isinstance(before, str)
                    or not re.fullmatch(r"msg[A-Za-z0-9_-]{1,150}", before)
                )
            )
            or not isinstance(title, str)
            or len(title) > 120
        ):
            raise ValueError("分支参数无效")
        async with ui.control_lock:
            operation = ui.auth.fork_request(request_id)
            if operation and operation.get("expected_current", source_id) != expected:
                raise web.HTTPConflict(text="请求编号对应的原映射不同，请刷新后重试")
            if operation and any(
                operation.get(key) != value
                for key, value in {
                    "conversation": conversation,
                    "source_id": source_id,
                    "title": title,
                    "before": before,
                }.items()
            ):
                raise web.HTTPConflict(text="请求编号已经用于另一次分支操作")
            if operation and operation["status"] in {"pending", "uncertain", "failed"}:
                raise web.HTTPConflict(text="上次分支请求未确认或未完成，请刷新查看；不会再次创建")
            inventory = await ui.data.sessions(fresh=True)
            mapping = next(
                (m for m in inventory["mappings"] if m["conversation"] == conversation), None
            )
            source = next((s for s in inventory["items"] if s["id"] == source_id), None)
            if not mapping or not source:
                raise KeyError(source_id)
            if source["conversation"] != conversation or not source["eligible"]:
                raise web.HTTPForbidden(
                    text="只能从同一聊天可复用的会话创建分支，不能复制私密群聊上下文"
                )
            context = Context(**mapping["target"])
            if operation and operation["status"] == "switched":
                return web.json_response(
                    {
                        "session_id": operation["session_id"],
                        "switched": ui.store.session(context) == operation["session_id"],
                        "replayed": True,
                    }
                )
            client = ui.data.client()
            if operation is None:
                await self.idle(client, context, {source_id, mapping["session_id"]}, expected)
                info = await client.get_session(source_id)
                if (
                    info.get("parentID")
                    or info.get("metadata", {}).get("qq_bridge_context") != conversation
                    or info.get("location", {}).get("directory") != str(ui.config.workdir.resolve())
                ):
                    raise web.HTTPForbidden(text="会话来源或工作目录不匹配")
                # Account for a new task or /new that arrived during the last network read.
                if ui.store.conversation_jobs(context) or ui.store.session(context) != expected:
                    raise web.HTTPConflict(text="聊天任务或映射已有变化，请刷新后重试")
                if before:
                    try:
                        message = await client.request(
                            "GET", f"/api/session/{path_id(source_id)}/message/{path_id(before)}"
                        )
                    except ApiError as exc:
                        if exc.status == 404:
                            raise web.HTTPBadRequest(
                                text="分支起点消息不存在或不属于所选会话"
                            ) from exc
                        raise
                    if not isinstance(message, dict) or message.get("id") != before:
                        raise web.HTTPBadRequest(text="分支起点不属于所选会话")
                    if ui.store.conversation_jobs(context) or ui.store.session(context) != expected:
                        raise web.HTTPConflict(text="聊天任务或映射已有变化，请刷新后重试")
                ui.auth.fork_request(
                    request_id,
                    status="pending",
                    conversation=conversation,
                    source_id=source_id,
                    title=title,
                    before=before,
                    expected_current=expected,
                    created=time.time(),
                )
                try:
                    async with asyncio.timeout(20):
                        fork = await client.request(
                            "POST",
                            f"/api/session/{path_id(source_id)}/fork",
                            body={"before": before} if before else {},
                        )
                except ApiError as exc:
                    ui.auth.fork_request(request_id, status="failed")
                    if exc.status in {404, 405, 501}:
                        raise web.HTTPNotImplemented(
                            text="OpenCode 不支持分支或源会话已不存在"
                        ) from exc
                    if exc.status == 400:
                        raise web.HTTPBadRequest(
                            text="OpenCode 未接受分支请求；空会话不能创建分支"
                        ) from exc
                    raise
                except (ClientError, TimeoutError, OSError, ProtocolError) as exc:
                    ui.auth.fork_request(request_id, status="uncertain")
                    ui.data.cache.clear()
                    ui.audit("session_fork_unconfirmed", source_id)
                    raise web.HTTPServiceUnavailable(
                        text="分支创建结果未确认，映射未切换；请刷新查看，不要再次创建"
                    ) from exc
                if (
                    not isinstance(fork, dict)
                    or not isinstance(fork.get("id"), str)
                    or not re.fullmatch(r"ses[A-Za-z0-9_-]{1,150}", fork["id"])
                    or fork["id"] == source_id
                    or (fork.get("fork") or {}).get("sessionID") != source_id
                    or fork.get("parentID")
                    or fork.get("location", {}).get("directory") != str(ui.config.workdir.resolve())
                ):
                    ui.auth.fork_request(request_id, status="uncertain")
                    ui.data.cache.clear()
                    ui.audit("session_fork_unconfirmed", source_id)
                    raise web.HTTPServiceUnavailable(text="分支回执未确认，映射未切换；请刷新查看")
                operation = ui.auth.fork_request(
                    request_id, status="created", session_id=fork["id"]
                )
                ui.data.cache.clear()
            session_id = operation["session_id"]
            if ui.store.session(context) == session_id:
                ui.auth.fork_request(request_id, status="switched")
                return web.json_response(
                    {"session_id": session_id, "switched": True, "replayed": True}
                )
            # A fork copies the previous initiator's metadata and permissions. Reset only the
            # new branch; the next QQ task will supply its own real identity as usual.
            safe_context = (
                Context(context.self_id, 0, context.group_id) if context.group_id else context
            )
            try:
                fork = await client.get_session(session_id)
                if (
                    (fork.get("fork") or {}).get("sessionID") != source_id
                    or fork.get("parentID")
                    or fork.get("location", {}).get("directory") != str(ui.config.workdir.resolve())
                ):
                    raise ProtocolError("分支来源或工作目录已有变化")
                await client.request(
                    "PATCH",
                    f"/api/session/{path_id(session_id)}",
                    body={
                        "title": title.strip() or (source["title"] + " · 分支")[:120],
                        "metadata": {
                            **{
                                k: v
                                for k, v in fork.get("metadata", {}).items()
                                if not k.startswith("qq_bridge_")
                            },
                            **metadata_for(ui.config, safe_context),
                            "qq_bridge_job_id": None,
                        },
                        "permissions": permissions_for(ui.config, safe_context),
                        "archived": False,
                    },
                )
                try:
                    await client.request(
                        "DELETE",
                        f"/api/experimental/session/{path_id(session_id)}/instructions/entries/{IDENTITY_ENTRY_KEY}",
                    )
                except ApiError as exc:
                    if exc.status != 404:
                        raise
                ui.auth.remember_branch(conversation, source_id, session_id)
                await self.idle(client, context, {source_id, session_id, expected}, expected)
            except (ApiError, ProtocolError, ClientError, TimeoutError, OSError, web.HTTPConflict):
                ui.data.cache.clear()
                ui.audit("session_fork_created", source_id + " => " + session_id)
                return web.json_response(
                    {
                        "session_id": session_id,
                        "switched": False,
                        "message": (
                            "分支已创建；聊天任务、映射或服务状态发生变化，"
                            "尚未切换，请刷新后选择该分支。"
                        ),
                    },
                    status=201,
                )
            # No await between the final idle check and mapping update.
            ui.store.switch_session(context, session_id)
            ui.auth.fork_request(request_id, status="switched")
            ui.data.cache.clear()
            ui.audit("session_fork_switched", source_id + " => " + session_id)
        return web.json_response({"session_id": session_id, "switched": True}, status=201)
