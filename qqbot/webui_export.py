"""Authenticated, sanitized transcript downloads; never submit model work."""

from __future__ import annotations

import asyncio
import json

from aiohttp import web

from .opencode import ApiError, ProtocolError, path_id

MAX_EXPORT = 32 * 1024 * 1024


class ExportConsole:
    def __init__(self, dashboard):
        self.dashboard = dashboard

    def routes(self):
        return [web.get("/api/sessions/{id}/export", self.export)]

    async def export(self, request):
        ui, session_id = self.dashboard, request.match_info["id"]
        format = request.query.get("format", "markdown")
        scope = request.query.get("scope", "text")
        if (
            format not in {"markdown", "json"}
            or scope not in {"text", "full"}
            or (format == "markdown" and scope == "full")
        ):
            raise ValueError("导出格式无效")
        async with ui.data.remote_limit, asyncio.timeout(30):
            client = ui.data.client()
            if not await ui.data.allowed_session(client, session_id):
                raise KeyError(session_id)
            try:
                transfer = await client.request(
                    "GET",
                    f"/api/experimental/session/{path_id(session_id)}/export",
                    params={"sanitize": "true"},
                )
            except ApiError as exc:
                if exc.status in {404, 405, 501}:
                    raise web.HTTPNotImplemented(
                        text="当前 OpenCode 不支持会话导出，或会话已不存在"
                    ) from exc
                raise
            if (
                not isinstance(transfer, dict)
                or not isinstance(transfer.get("messages"), list)
                or not isinstance(transfer.get("info"), dict)
                or transfer["info"].get("id") != session_id
            ):
                raise ProtocolError("OpenCode 导出响应无效")
            info = transfer["info"]
            messages = []
            for item in transfer["messages"]:
                if scope == "full":
                    message = ui.data.message(item)
                    for key in ("status", "reason"):
                        if key in item:
                            message[key] = item[key]
                    messages.append(message)
                elif item.get("type") in {"user", "assistant"}:
                    text = (
                        item.get("text", "")
                        if item["type"] == "user"
                        else "\n\n".join(
                            part.get("text", "")
                            for part in item.get("content", [])
                            if part.get("type") == "text"
                        )
                    )
                    if text:
                        messages.append({"id": item.get("id"), "type": item["type"], "text": text})
            result = ui.data.clean(
                {
                    "session": {
                        key: info.get(key) for key in ("id", "title", "model", "time", "fork")
                    },
                    "scope": scope,
                    "messages": messages,
                }
            )
            if format == "json":
                content = json.dumps(result, ensure_ascii=False, indent=2)
                extension, mime = "json", "application/json"
            else:
                content = "# " + (result["session"]["title"] or session_id) + "\n\n"
                content += "会话：" + session_id + "\n\n"
                content += "\n\n---\n\n".join(
                    "## " + ("用户" if m["type"] == "user" else "助手") + "\n\n" + m["text"]
                    for m in result["messages"]
                )
                extension, mime = "md", "text/markdown"
            data = content.encode("utf-8")
            if len(data) > MAX_EXPORT:
                raise web.HTTPRequestEntityTooLarge(max_size=MAX_EXPORT, actual_size=len(data))
            ui.audit("session_exported", session_id)
            return web.Response(
                body=data,
                content_type=mime,
                charset="utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="session-{scope}.{extension}"',
                    "X-Export-Scope": scope,
                },
            )
