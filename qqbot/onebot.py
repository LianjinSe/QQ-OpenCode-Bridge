from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import re
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiohttp

from .delivery import DeliveryCancelled
from .forward import ForwardReader
from .models import Attachment, Context, ReplyContent, identifier, qq_image_url, segments

log = logging.getLogger(__name__)


class Unavailable(ConnectionError):
    """No request was sent."""


class DeliveryUnknown(ConnectionError):
    """The remote side may have acted on the request."""


class ActionError(RuntimeError):
    def __init__(self, action: str, retcode: Any):
        super().__init__(f"OneBot {action} 失败（retcode={retcode}）")


class AttachmentError(ValueError):
    pass


@dataclass
class Request:
    future: asyncio.Future
    queue: asyncio.Queue | None = None


class OneBot:
    def __init__(self, session: aiohttp.ClientSession, url: str, token: str):
        self.session, self.url, self.token = session, url, token
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self.requests: dict[str, Request] = {}
        self.events: asyncio.Queue[dict] = asyncio.Queue(maxsize=512)
        self.ready = asyncio.Event()
        self.self_id = 0
        self.online = False

    async def run(self) -> None:
        delay = 1
        while True:
            try:
                await self.connect()
                delay = 1
                assert self.reader is not None
                await self.reader
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, OSError, TimeoutError, ActionError, Unavailable):
                log.warning("NapCat 连接不可用，等待重连")
            finally:
                await self.disconnect()
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    async def connect(self) -> None:
        self.ws = await self.session.ws_connect(
            self.url,
            headers={"Authorization": f"Bearer {self.token}"},
            heartbeat=30,
            max_msg_size=2 * 1024 * 1024,
        )
        self.reader = asyncio.create_task(self._receive(), name="onebot-receiver")
        try:
            info = await self.call("get_login_info", {})
            self.self_id = int(info["user_id"])
            status = await self.call("get_status", {})
            self.online = bool(status.get("online", False))
            self.ready.set()
            log.info("已连接 NapCat，QQ=%s，online=%s", self.self_id, self.online)
        except BaseException:
            await self.disconnect()
            raise

    async def disconnect(self) -> None:
        self.ready.clear()
        self.online = False
        ws, self.ws = self.ws, None
        if ws is not None:
            await ws.close()
        reader = getattr(self, "reader", None)
        if reader is not None and reader is not asyncio.current_task():
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        self._fail_requests()

    def _fail_requests(self) -> None:
        for request in self.requests.values():
            if not request.future.done():
                request.future.set_exception(DeliveryUnknown("OneBot 连接中断"))
        self.requests.clear()

    async def _receive(self) -> None:
        assert self.ws is not None
        try:
            async for message in self.ws:
                if message.type == aiohttp.WSMsgType.ERROR:
                    break
                if message.type != aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    payload = json.loads(message.data)
                except (ValueError, TypeError):
                    continue
                if not isinstance(payload, dict):
                    continue
                echo = payload.get("echo")
                request = self.requests.get(str(echo)) if echo is not None else None
                if request is not None:
                    if request.queue is not None:
                        try:
                            request.queue.put_nowait(payload)
                        except asyncio.QueueFull:
                            if not request.future.done():
                                request.future.set_exception(AttachmentError("附件接收缓冲区溢出"))
                        data = payload.get("data", {})
                        if (
                            payload.get("retcode") not in (0, None)
                            or isinstance(data, dict)
                            and data.get("type") in {"response", "error"}
                        ) and not request.future.done():
                            request.future.set_result(None)
                    elif not request.future.done():
                        request.future.set_result(payload)
                    continue
                if payload.get("meta_event_type") == "heartbeat":
                    self.online = bool(payload.get("status", {}).get("online", False))
                try:
                    self.events.put_nowait(payload)
                except asyncio.QueueFull:
                    log.error("入站事件队列已满，丢弃事件")
        finally:
            self.ready.clear()
            self.online = False
            self._fail_requests()

    async def _send(self, action: str, params: dict, request: Request) -> str:
        ws = self.ws
        if ws is None or ws.closed:
            raise Unavailable("NapCat 尚未连接")
        echo = uuid.uuid4().hex
        self.requests[echo] = request
        try:
            await ws.send_json({"action": action, "params": params, "echo": echo})
        except (aiohttp.ClientError, OSError, ConnectionError) as exc:
            self.requests.pop(echo, None)
            raise DeliveryUnknown("发送请求时连接中断") from exc
        return echo

    async def call(self, action: str, params: dict, response_timeout: float = 15) -> Any:
        future = asyncio.get_running_loop().create_future()
        echo = await self._send(action, params, Request(future))
        try:
            try:
                payload = await asyncio.wait_for(future, response_timeout)
            except TimeoutError as exc:
                raise DeliveryUnknown(f"OneBot {action} 响应超时") from exc
            if payload.get("status") != "ok" or payload.get("retcode") != 0:
                raise ActionError(action, payload.get("retcode"))
            data = payload.get("data")
            return {} if data is None else data
        finally:
            self.requests.pop(echo, None)

    @asynccontextmanager
    async def stream_request(self, action: str, params: dict, *, queue_size: int = 128):
        """Yield an async frame iterator for one streamed OneBot response.

        The iterator owns its echo registration and unregisters it on completion,
        cancellation, timeout by its caller, or connection teardown.
        """
        future = asyncio.get_running_loop().create_future()
        request = Request(future, asyncio.Queue(maxsize=queue_size))
        echo = await self._send(action, params, request)

        async def frames():
            while True:
                get = asyncio.create_task(request.queue.get())
                try:
                    done, _ = await asyncio.wait({get, future}, return_when=asyncio.FIRST_COMPLETED)
                    if get in done:
                        frame = get.result()
                    elif future.exception():
                        raise future.exception()
                    elif not request.queue.empty():
                        frame = request.queue.get_nowait()
                    else:
                        raise DeliveryUnknown("流未完整结束")
                finally:
                    if not get.done():
                        get.cancel()
                        await asyncio.gather(get, return_exceptions=True)
                yield frame
                data = frame.get("data", {})
                if data.get("type") in {"response", "error"}:
                    return

        try:
            yield frames()
        finally:
            self.requests.pop(echo, None)

    async def send_text(self, context: Context, text: str, first_chunk: bool = True) -> dict:
        segments = []
        if context.group_id is not None and first_chunk:
            segments.extend(
                [
                    {"type": "at", "data": {"qq": str(context.user_id)}},
                    {"type": "text", "data": {"text": " "}},
                ]
            )
        segments.append({"type": "text", "data": {"text": text}})
        if context.group_id is None:
            return await self.call(
                "send_private_msg", {"user_id": str(context.user_id), "message": segments}
            )
        return await self.call(
            "send_group_msg", {"group_id": str(context.group_id), "message": segments}
        )

    async def set_typing(self, context: Context, active: bool) -> bool:
        if (
            context.group_id is not None
            or context.self_id != self.self_id
            or not self.ready.is_set()
            or not self.online
        ):
            return False
        result = await self.call(
            "set_input_status",
            {"user_id": str(context.user_id), "event_type": 1 if active else 0},
            response_timeout=3,
        )
        if isinstance(result, dict) and result.get("result") not in (None, 0, "0"):
            raise ActionError("set_input_status", result["result"])
        return True

    async def send_poke(self, context: Context) -> dict:
        if context.self_id != self.self_id or not self.ready.is_set() or not self.online:
            raise Unavailable("戳一戳所属 QQ 尚未连接")
        params = {"user_id": str(context.user_id)}
        if context.group_id is not None:
            params["group_id"] = str(context.group_id)
        return await self.call("send_poke", params, response_timeout=5)

    async def reply_content(
        self, context: Context, reply_id: str, *, trusted_bot_reply: bool = False
    ) -> ReplyContent:
        async with asyncio.timeout(30):
            return await self._reply_content(context, reply_id, trusted_bot_reply=trusted_bot_reply)

    async def _reply_content(
        self, context: Context, reply_id: str, *, trusted_bot_reply: bool = False
    ) -> ReplyContent:
        message = await self.call("get_msg", {"message_id": reply_id})
        if not isinstance(message, dict) or not isinstance(message.get("sender"), dict):
            raise AttachmentError("被回复消息的数据无效")
        try:
            sender_id = identifier(message["sender"].get("user_id"))
        except ValueError:
            raise AttachmentError("被回复消息的发送者无效") from None
        if (
            isinstance(message.get("message_id"), bool)
            or str(message.get("message_id")) != reply_id
        ):
            raise AttachmentError("被回复消息编号不匹配")
        if context.group_id is not None:
            try:
                group_id = identifier(message.get("group_id"))
            except ValueError:
                raise AttachmentError("被回复消息的群号无效") from None
            if message.get("message_type") != "group" or group_id != context.group_id:
                raise AttachmentError("被回复消息不属于当前群")
        else:
            if message.get("message_type") != "private" or message.get("group_id") is not None:
                raise AttachmentError("被回复消息不属于当前私聊")
            # NapCat get_msg does not identify the recipient of bot-sent private messages.
            # Only a locally confirmed delivery to this peer can establish that boundary.
            if sender_id != context.user_id and not (
                sender_id == self.self_id and trusted_bot_reply
            ):
                raise AttachmentError("无法确认被回复消息属于当前私聊")
        body = message.get("message")
        if not isinstance(body, (list, str)) or not body:
            raise AttachmentError("被回复消息的内容无效")
        return await ForwardReader(self.call).read_quoted(
            {**message, "message": segments(body) if isinstance(body, str) else body}
        )

    async def upload_file(
        self,
        data: bytes,
        name: str,
        upload_timeout: float,
        cancelled: Callable[[], bool] = lambda: False,
    ) -> str:
        stream_id = uuid.uuid4().hex
        sha256 = hashlib.sha256(data).hexdigest()
        chunk_size = 65536
        chunks = (len(data) + chunk_size - 1) // chunk_size
        if not chunks:
            raise AttachmentError("回传文件不能为空")
        suffix = Path(name).suffix
        suffix = suffix if re.fullmatch(r"\.[a-zA-Z0-9]{1,12}", suffix) else ".bin"
        filename = f"qq-{stream_id}{suffix}"
        async with asyncio.timeout(upload_timeout):
            for index in range(chunks):
                if cancelled():
                    raise DeliveryCancelled("回传已取消")
                result = await self.call(
                    "upload_file_stream",
                    {
                        "stream_id": stream_id,
                        "chunk_data": base64.b64encode(
                            data[index * chunk_size : (index + 1) * chunk_size]
                        ).decode(),
                        "chunk_index": index,
                        "total_chunks": chunks,
                        "file_size": len(data),
                        "expected_sha256": sha256,
                        "filename": filename,
                        "file_retention": 600000,
                    },
                )
                if (
                    not isinstance(result, dict)
                    or result.get("stream_id") != stream_id
                    or result.get("status") != "chunk_received"
                    or result.get("received_chunks") != index + 1
                    or result.get("total_chunks") != chunks
                ):
                    raise AttachmentError("回传上传分块确认无效")
            result = await self.call(
                "upload_file_stream", {"stream_id": stream_id, "is_complete": True}
            )
            if (
                not isinstance(result, dict)
                or result.get("type") != "response"
                or result.get("status") != "file_complete"
                or result.get("stream_id") != stream_id
                or result.get("file_size") != len(data)
                or result.get("sha256") != sha256
                or not isinstance(result.get("file_path"), str)
                or not result["file_path"].startswith("/")
            ):
                raise AttachmentError("回传上传完成确认无效")
            return result["file_path"]

    async def send_media(
        self, context: Context, path: str, name: str, kind: str, response_timeout: float
    ) -> dict:
        if context.self_id != self.self_id:
            raise Unavailable("回传任务所属 QQ 与当前登录账号不同")
        if kind in {"image", "video", "audio"}:
            action = "send_private_msg" if context.group_id is None else "send_group_msg"
            target = (
                {"user_id": str(context.user_id)}
                if context.group_id is None
                else {"group_id": str(context.group_id)}
            )
            return await self.call(
                action,
                {
                    **target,
                    "message": [
                        {
                            "type": "record" if kind == "audio" else kind,
                            "data": {"file": "file://" + path},
                        }
                    ],
                },
                response_timeout=response_timeout,
            )
        action = "upload_private_file" if context.group_id is None else "upload_group_file"
        target = (
            {"user_id": str(context.user_id)}
            if context.group_id is None
            else {"group_id": str(context.group_id)}
        )
        return await self.call(
            action, {**target, "file": path, "name": name}, response_timeout=response_timeout
        )

    async def download(
        self, item: Attachment, directory: Path, remaining: int, download_timeout: float
    ) -> Path:
        # Only server-issued attachment identifiers enter this path, never chat text.
        if item.size is not None and item.size > remaining:
            raise AttachmentError("附件超过大小限制")
        if not item.reference or len(item.reference) > 4096:
            raise AttachmentError("附件标识无效")
        if item.reference.startswith(("/", "\\")) or re.match(r"^[a-zA-Z]:", item.reference):
            raise AttachmentError("拒绝将文件路径当作 QQ 附件标识")
        await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True, mode=0o700)
        stem = re.sub(r"[^\w.\-]", "_", Path(item.name.replace("\\", "/")).name)[:120]
        stem = stem.strip(".") or item.kind
        destination = directory / f"{uuid.uuid4().hex[:12]}-{stem}"
        url = qq_image_url(item.url) if item.kind == "image" else None
        if url is not None:
            return await self._download_image(item, url, destination, remaining, download_timeout)
        partial = destination.with_name(destination.name + ".part")
        future = asyncio.get_running_loop().create_future()
        request = Request(future, asyncio.Queue(maxsize=512))
        echo = await self._send(
            "download_file_stream", {"file_id": item.reference, "chunk_size": 65536}, request
        )
        received, index, advertised, chunk_count = 0, 0, None, None
        try:
            async with asyncio.timeout(download_timeout):
                with partial.open("xb") as output:
                    while True:
                        assert request.queue is not None
                        get = asyncio.create_task(request.queue.get())
                        try:
                            done, _ = await asyncio.wait(
                                {get, future}, return_when=asyncio.FIRST_COMPLETED
                            )
                            if get not in done:
                                if future.exception() is not None:
                                    raise future.exception()
                                if request.queue.empty():
                                    raise AttachmentError("附件流提前结束")
                                frame = request.queue.get_nowait()
                            else:
                                frame = get.result()
                        finally:
                            if not get.done():
                                get.cancel()
                                await asyncio.gather(get, return_exceptions=True)
                        if frame.get("retcode") != 0:
                            raise AttachmentError("NapCat 附件下载失败")
                        data = frame.get("data", {})
                        if not isinstance(data, dict) or data.get("type") == "error":
                            raise AttachmentError("附件流无效")
                        if data.get("data_type") == "file_info":
                            advertised = int(data["file_size"])
                            if advertised < 0 or advertised > remaining:
                                raise AttachmentError("附件超过大小限制")
                        elif data.get("data_type") == "file_chunk":
                            if int(data.get("index", -1)) != index:
                                raise AttachmentError("附件分块顺序错误")
                            chunk = base64.b64decode(data.get("data", ""), validate=True)
                            if len(chunk) != int(data.get("size", -1)):
                                raise AttachmentError("附件分块长度错误")
                            if received + len(chunk) > remaining:
                                raise AttachmentError("附件超过大小限制")
                            output.write(chunk)
                            received += len(chunk)
                            index += 1
                        elif data.get("type") == "response":
                            if data.get("data_type") != "file_complete":
                                raise AttachmentError("附件流没有完成标记")
                            chunk_count = int(data.get("total_chunks", -1))
                            if int(data.get("total_bytes", -1)) != received:
                                raise AttachmentError("附件总长度错误")
                            break
                    if advertised is None or advertised != received or chunk_count != index:
                        raise AttachmentError("附件下载不完整")
                partial.replace(destination)
                return destination
        except AttachmentError:
            raise
        except (TimeoutError, ValueError, KeyError, binascii.Error) as exc:
            raise AttachmentError("附件下载超时或数据损坏，请重新发送") from exc
        finally:
            self.requests.pop(echo, None)
            if not future.done():
                future.cancel()
            else:
                # Retrieve an exception even if a queued chunk was processed first.
                future.exception()
            partial.unlink(missing_ok=True)

    async def _download_image(
        self, item: Attachment, url: str, destination: Path, remaining: int, download_timeout: float
    ) -> Path:
        # Forward images can have a working CDN URL while QQ's media download times out.
        partial = destination.with_name(destination.name + ".part")
        received = 0
        try:
            async with asyncio.timeout(download_timeout):
                async with self.session.get(
                    url, allow_redirects=False, auto_decompress=False
                ) as response:
                    if response.status != 200:
                        raise AttachmentError("图片链接下载失败")
                    if response.content_length is not None and response.content_length > remaining:
                        raise AttachmentError("附件超过大小限制")
                    with partial.open("xb") as output:
                        async for chunk in response.content.iter_chunked(65536):
                            received += len(chunk)
                            if received > remaining:
                                raise AttachmentError("附件超过大小限制")
                            output.write(chunk)
                    if (
                        not received
                        or (item.size is not None and received != item.size)
                        or (
                            response.content_length is not None
                            and received != response.content_length
                        )
                    ):
                        raise AttachmentError("附件下载不完整")
            partial.replace(destination)
            return destination
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise AttachmentError("附件下载超时或数据损坏，请重新发送") from exc
        finally:
            partial.unlink(missing_ok=True)
