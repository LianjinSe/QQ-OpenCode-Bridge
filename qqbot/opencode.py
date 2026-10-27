from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from typing import Any
from urllib.parse import quote

import aiohttp

from . import messages as copy
from .config import Config
from .delivery import DELIVERY_ENTRY_KEY
from .models import Context
from .policy import IDENTITY_ENTRY_KEY, identity_for, metadata_for, permissions_for

log = logging.getLogger(__name__)


class ApiError(RuntimeError):
    def __init__(self, status: int, operation: str):
        self.status = status
        super().__init__(f"OpenCode {operation} 失败（HTTP {status}）")


class ProtocolError(RuntimeError):
    pass


def path_id(value: str) -> str:
    return quote(value, safe="")


class OpenCode:
    def __init__(self, session: aiohttp.ClientSession, config: Config, add_secret=lambda x: None):
        self.http, self.config, self.add_secret = session, config, add_secret
        self.url = ""
        self.headers: dict[str, str] = {}
        self.available = False
        self.parents: dict[str, str | None] = {}

    def discover(self) -> None:
        if self.config.opencode_url:
            url, password = self.config.opencode_url, self.config.opencode_password
            username = self.config.opencode_username
        else:
            try:
                info = json.loads(self.config.service_file.read_text())
                url, password, username = info["url"], info.get("password", ""), "opencode"
                if not isinstance(url, str) or not isinstance(password, str):
                    raise ValueError
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise ProtocolError("无法读取 OpenCode 服务注册文件") from exc
        if not url.startswith(("http://", "https://")):
            raise ProtocolError("OpenCode 服务地址无效")
        self.url = url.rstrip("/")
        self.headers = {}
        if password:
            self.add_secret(password)
            authorization = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
            self.headers["Authorization"] = authorization
            self.add_secret(authorization)

    async def ensure(self, *, allow_start: bool = True) -> dict:
        try:
            self.discover()
            info = await self.request("GET", "/api/info", unwrap=False)
        except (OSError, aiohttp.ClientError, TimeoutError, ApiError, ProtocolError):
            self.available = False
            if not allow_start or not self.config.autostart or self.config.opencode_url:
                raise
            process = await asyncio.create_subprocess_exec(
                self.config.opencode_binary,
                "service",
                "start",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                env={
                    key: value
                    for key, value in os.environ.items()
                    if key not in {"SILICONFLOW_API_KEY", "MEMORY_DATABASE_URL"}
                },
            )
            try:
                async with asyncio.timeout(30):
                    await process.wait()
            except TimeoutError:
                process.kill()
                await process.wait()
                raise ProtocolError("OpenCode 后台服务启动超时") from None
            if process.returncode:
                raise ProtocolError("OpenCode 后台服务启动失败") from None
            self.discover()
            info = await self.request("GET", "/api/info", unwrap=False)
        if not isinstance(info, dict) or not str(info.get("version", "")).startswith("2."):
            self.available = False
            raise ProtocolError("桥接服务需要 OpenCode v2，当前服务版本不兼容")
        spec = await self.request("GET", "/openapi.json", unwrap=False)
        required = {
            "/api/session",
            "/api/session/{sessionID}/prompt",
            "/api/session/{sessionID}/message",
            "/api/experimental/session/{sessionID}/wait",
            "/api/session/{sessionID}/permission/{requestID}/reply",
            "/api/session/{sessionID}/form/{formID}/reply",
            "/api/experimental/session/{sessionID}/instructions/entries/{key}",
        }
        if not isinstance(spec, dict) or not required <= spec.get("paths", {}).keys():
            self.available = False
            raise ProtocolError("OpenCode v2 API 缺少桥接所需接口")
        self.available = True
        self.parents.clear()
        return info

    async def request(
        self, method: str, path: str, *, body=None, params=None, unwrap=True, wait=False
    ) -> Any:
        timeout = aiohttp.ClientTimeout(
            total=None if wait else 30, sock_connect=10, sock_read=None if wait else 30
        )
        try:
            async with self.http.request(
                method,
                self.url + path,
                headers=self.headers,
                json=body,
                params=params,
                timeout=timeout,
                allow_redirects=False,
            ) as response:
                if response.status >= 300:
                    if response.status in {401, 502, 503, 504}:
                        self.available = False
                    raise ApiError(response.status, method + " " + path.split("/")[2])
                if response.status == 204:
                    return None
                try:
                    payload = await response.json()
                except (ValueError, aiohttp.ContentTypeError) as exc:
                    raise ProtocolError("OpenCode 返回了无效的 API 响应") from exc
                if unwrap:
                    if not isinstance(payload, dict) or "data" not in payload:
                        raise ProtocolError("OpenCode v2 响应缺少 data")
                    return payload["data"]
                return payload
        except (aiohttp.ClientError, TimeoutError, OSError):
            self.available = False
            raise

    async def get_session(self, session_id: str) -> dict:
        return await self.request("GET", "/api/session/" + path_id(session_id))

    async def create_session(self, session_id: str, context: Context) -> dict:
        model = None
        if self.config.model:
            provider, name = self.config.model.split("/", 1)
            model = {"providerID": provider, "id": name}
        body = {
            "id": session_id,
            "title": "QQ " + context.conversation_key,
            "agent": "build",
            "location": {"directory": str(self.config.workdir.resolve())},
            "metadata": metadata_for(self.config, context),
            "permissions": permissions_for(self.config, context),
        }
        if model is not None:
            body["model"] = model
        return await self.request("POST", "/api/session", body=body)

    async def sync_context(
        self, session_id: str, context: Context, job_id: str | None = None
    ) -> None:
        session = await self.get_session(session_id)
        if session.get("metadata", {}).get(
            "qq_bridge_context"
        ) != context.conversation_key or session.get("location", {}).get("directory") != str(
            self.config.workdir.resolve()
        ):
            raise ProtocolError("OpenCode 会话的来源或工作目录不匹配")
        await self.request(
            "PATCH",
            f"/api/session/{path_id(session_id)}",
            body={
                "metadata": {
                    **session.get("metadata", {}),
                    **metadata_for(self.config, context),
                    "qq_bridge_job_id": job_id,
                },
                "permissions": permissions_for(self.config, context),
            },
        )
        await self.request(
            "PUT",
            f"/api/experimental/session/{path_id(session_id)}/instructions/entries/"
            + IDENTITY_ENTRY_KEY,
            body={"value": identity_for(self.config, context)},
        )
        await self.clear_delivery_instructions(session_id)

    async def clear_delivery_instructions(self, session_id: str) -> None:
        """Retire persisted delivery prompts when reusing an existing session."""
        try:
            await self.request(
                "DELETE",
                f"/api/experimental/session/{path_id(session_id)}/instructions/entries/"
                + DELIVERY_ENTRY_KEY,
            )
        except ApiError as exc:
            if exc.status != 404:
                raise

    async def prepare_shared(self, root: str, context: Context, job_id: str) -> bool:
        """Only cross task boundaries after the old tree is idle and settled."""
        active = await self.active()
        if any([await self.belongs_to(sid, root) for sid in active]):
            return False
        pending, forms = await self.interactions(root)
        for request in pending:
            await self.permission(request["sessionID"], request["id"], "reject")
        for form in forms:
            await self.cancel_form(form["sessionID"], form["id"])
        pending, forms = await self.interactions(root)
        if pending or forms:
            return False
        # All descendants, not just active ones: old children may be reused later.
        queue, seen = [root], {root}
        while queue:
            parent = queue.pop()
            cursor = None
            cursors = set()
            while True:
                params = {"parentID": parent, "limit": "100"}
                if cursor:
                    params["cursor"] = cursor
                page = await self.request("GET", "/api/session", params=params, unwrap=False)
                if not isinstance(page, dict) or not isinstance(page.get("data"), list):
                    raise ProtocolError("无法确认子会话权限")
                for child in page["data"]:
                    sid = child["id"]
                    if child.get("parentID") != parent or sid in seen:
                        raise ProtocolError("子会话归属无效")
                    seen.add(sid)
                    queue.append(sid)
                    await self.request(
                        "PATCH",
                        f"/api/session/{path_id(sid)}",
                        body={
                            "permissions": permissions_for(self.config, context),
                            "metadata": {
                                **child.get("metadata", {}),
                                **metadata_for(self.config, context),
                                "qq_bridge_job_id": job_id,
                            },
                        },
                    )
                    await self.request(
                        "PUT",
                        f"/api/experimental/session/{path_id(sid)}"
                        f"/instructions/entries/{IDENTITY_ENTRY_KEY}",
                        body={"value": identity_for(self.config, context)},
                    )
                    await self.clear_delivery_instructions(sid)
                cursor = page.get("cursor", {}).get("next")
                if not cursor:
                    break
                if cursor in cursors:
                    raise ProtocolError("子会话分页未前进")
                cursors.add(cursor)
        return True

    async def prompt(
        self, session_id: str, prompt_id: str, text: str, files: list[dict], *, delivery="queue"
    ) -> dict:
        return await self.request(
            "POST",
            f"/api/session/{path_id(session_id)}/prompt",
            body={
                "id": prompt_id,
                "text": text,
                "files": files,
                "metadata": {"source": "qq-bridge"},
                "delivery": delivery,
                "resume": True,
            },
        )

    async def admitted(self, session_id: str, prompt_id: str) -> bool:
        try:
            await self.request(
                "GET", f"/api/session/{path_id(session_id)}/message/{path_id(prompt_id)}"
            )
            return True
        except ApiError as exc:
            if exc.status != 404:
                raise
        return any(x["id"] == prompt_id for x in await self.inbox(session_id))

    async def inbox(self, session_id: str) -> list[dict]:
        return await self.request("GET", f"/api/session/{path_id(session_id)}/inbox")

    async def wait(self, session_id: str) -> None:
        await self.request(
            "POST", f"/api/experimental/session/{path_id(session_id)}/wait", wait=True
        )

    async def active(self) -> dict:
        return await self.request("GET", "/api/session/active")

    async def turn(self, session_id: str, prompt_id: str) -> tuple[dict | None, list[dict]]:
        """Read backwards to this exact user message, respecting pagination."""
        result, cursor = [], None
        while True:
            params = {"limit": "100"}
            if cursor:
                params["cursor"] = cursor
            else:
                params["order"] = "desc"
            page = await self.request(
                "GET",
                f"/api/session/{path_id(session_id)}/message",
                params=params,
                unwrap=False,
            )
            for message in page["data"]:
                if message["id"] == prompt_id:
                    return message, list(reversed(result))
                result.append(message)
            cursor = page.get("cursor", {}).get("next")
            if not cursor:
                return None, []

    async def belongs_to(self, session_id: str, root: str) -> bool:
        visited = set()
        while session_id != root:
            if session_id in visited or len(visited) > 100:
                return False
            visited.add(session_id)
            if session_id not in self.parents:
                try:
                    info = await self.get_session(session_id)
                except ApiError as exc:
                    if exc.status == 404:
                        return False
                    raise
                self.parents[session_id] = info.get("parentID")
            session_id = self.parents[session_id]
            if session_id is None:
                return False
        return True

    async def interactions(self, root: str) -> tuple[list[dict], list[dict]]:
        params = {"location[directory]": str(self.config.workdir.resolve())}
        permissions, forms = await asyncio.gather(
            self.request("GET", "/api/permission/request", params=params),
            self.request("GET", "/api/form", params=params),
        )
        owned = []
        for collection in (permissions, forms):
            filtered = []
            for item in collection:
                if await self.belongs_to(item["sessionID"], root):
                    filtered.append(item)
            owned.append(filtered)
        return owned[0], owned[1]

    async def permission_input(self, request: dict) -> dict | None:
        source = request.get("source", {})
        if source.get("type") == "tool":
            try:
                message = await self.request(
                    "GET",
                    f"/api/session/{path_id(request['sessionID'])}/message/"
                    + path_id(source["messageID"]),
                )
            except ApiError as exc:
                if exc.status == 404:
                    return None
                raise
            tool = next(
                (
                    item
                    for item in message.get("content", [])
                    if item.get("type") == "tool" and item.get("id") == source.get("id")
                ),
                None,
            )
            value = (tool or {}).get("state", {}).get("input")
            return value if isinstance(value, dict) else None
        # Used by explicitly created API requests; never infer from scanner fragments.
        metadata = request.get("metadata", {})
        return metadata if isinstance(metadata, dict) else None

    async def permission(self, session_id: str, remote_id: str, decision: str) -> None:
        await self.request(
            "POST",
            f"/api/session/{path_id(session_id)}/permission/{path_id(remote_id)}/reply",
            body={"decision": decision},
        )

    async def answer(self, session_id: str, remote_id: str, answers: dict) -> None:
        await self.request(
            "POST",
            f"/api/session/{path_id(session_id)}/form/{path_id(remote_id)}/reply",
            body={"answer": answers},
        )

    async def cancel_form(self, session_id: str, remote_id: str) -> None:
        await self.request(
            "DELETE", f"/api/session/{path_id(session_id)}/form/{path_id(remote_id)}"
        )

    async def stop_tree(self, root: str) -> bool:
        active = await self.active()
        children = [sid for sid in active if sid != root and await self.belongs_to(sid, root)]
        for sid in [*children, root]:
            try:
                await self.request(
                    "POST",
                    f"/api/session/{path_id(sid)}/interrupt",
                    params={"resume": "false"},
                    unwrap=False,
                )
                inbox = await self.inbox(sid)
            except ApiError as exc:
                if exc.status == 404:
                    continue
                raise
            for item in inbox:
                await self.request(
                    "DELETE", f"/api/session/{path_id(sid)}/inbox/{path_id(item['id'])}"
                )
        active = await self.active()
        return not any([await self.belongs_to(sid, root) for sid in active])


def assistant_text(message: dict) -> str:
    return "\n".join(
        part["text"]
        for part in message.get("content", [])
        if part.get("type") == "text" and isinstance(part.get("text"), str)
    ).strip()


MANIFEST_JSON = re.compile(r'^[ \t]*\{\s*"files"\s*:\s*\[[^\]]*\][^{}]*\}[ \t]*$', re.MULTILINE)
STRAY_TAG = re.compile(r"</qq-delivery>[ \t]*", re.IGNORECASE)


def public_reply(text: str) -> str:
    """Hide complete or unfinished delivery manifests in intermediate replies."""
    cleaned = re.sub(r"<qq-delivery\b.*?(?:</qq-delivery>|$)", "", text, flags=re.DOTALL)
    # 标签和清单可能被拆到不同文本块：单独出现的清单 JSON 或残尾标签也要清掉
    cleaned = MANIFEST_JSON.sub("", cleaned)
    cleaned = STRAY_TAG.sub("", cleaned)
    return cleaned.strip()


def text_outputs(messages: list[dict]) -> list[tuple[str, int, str, bool]]:
    """Project public text blocks, including the block currently being streamed."""
    assistants = [message for message in messages if message.get("type") == "assistant"]
    outputs = []
    for index, message in enumerate(assistants):
        last = index == len(assistants) - 1
        timing = message.get("time", {})
        complete = bool(
            not last or timing.get("streamed") or timing.get("completed") or message.get("finish")
        )
        content = message.get("content", [])
        for part_index, part in enumerate(content):
            if part.get("type") != "text" or not isinstance(part.get("text"), str):
                continue
            text = part["text"]
            # A complete final manifest must be validated before its caption is sent.
            if last and "<qq-delivery" in text:
                continue
            outputs.append(
                (message["id"], part_index, text, complete or part_index < len(content) - 1)
            )
    return outputs


def reply_segments(
    text: str, start: int, chunk_size: int, *, complete: bool
) -> list[tuple[int, str]]:
    """Return completed paragraphs and long chunks with offsets into the original text."""
    opening = "<qq-delivery"
    end = text.find(opening)
    if end < 0:
        end = len(text)
        # A marker can arrive across updates, including across a QQ chunk boundary.
        for length in range(min(len(opening) - 1, end), 0, -1):
            if text.endswith(opening[:length]):
                end -= length
                complete = False
                break
        # 没有标签的裸清单 JSON 也按内部标记处理，不当作聊天正文
        bare = MANIFEST_JSON.search(text, start)
        if bare is not None and bare.start() < end:
            end = bare.start()
            complete = True
    else:
        complete = True
    if end <= start:
        return []
    replies = []
    position = start

    def append_until(stop: int) -> None:
        nonlocal position
        while stop - position >= chunk_size:
            next_position = position + chunk_size
            replies.append((next_position, text[position:next_position]))
            position = next_position

    for boundary in re.finditer(r"\r?\n[ \t]*\r?\n", text[start:end]):
        stop = start + boundary.start()
        append_until(stop)
        next_position = start + boundary.end()
        replies.append((next_position, text[position:stop].strip("\r\n")))
        position = next_position
    append_until(end)
    if complete and position < end:
        replies.append((end, text[position:end].strip("\r\n")))
    return replies


def final_reply(messages: list[dict], outcome: str | None = None) -> str:
    assistants = [m for m in messages if m.get("type") == "assistant"]
    if outcome == "failed" or (outcome is None and assistants and assistants[-1].get("error")):
        return copy.provider_failure_reply(assistants[-1].get("error") if assistants else None)
    if outcome == "interrupted":
        return copy.INTERRUPTED
    if assistants:
        text = assistant_text(assistants[-1])
        if text:
            return text
    return copy.NO_TEXT
