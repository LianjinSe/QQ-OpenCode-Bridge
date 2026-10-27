import asyncio
import json
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web
from conftest import eventually, message, start_server

from qqbot.models import Attachment, Context, attachment_from_segment
from qqbot.onebot import AttachmentError, OneBot

IMAGE = b"\x89PNG\r\n\x1a\nimage"
IMAGE_URL = "https://multimedia.nt.qq.com.cn/download?fileid=picture&rkey=test"


def route_image_download(monkeypatch, session, local_url):
    get = session.get

    def download(url, **kwargs):
        assert url == IMAGE_URL
        assert kwargs["allow_redirects"] is False
        assert kwargs["auto_decompress"] is False
        return get(local_url, **kwargs)

    monkeypatch.setattr(session, "get", download)


async def test_forward_image_url_survives_queueing_and_bypasses_media_api(harness, monkeypatch):
    async def image(request):
        return web.Response(body=IMAGE, content_type="image/png")

    server, url = await start_server(image)
    try:
        async with harness() as (bridge, nap, op):
            route_image_download(monkeypatch, bridge.onebot.session, url)
            segment = {
                "type": "image",
                "data": {"file": "picture.png", "url": IMAGE_URL, "file_size": str(len(IMAGE))},
            }
            card = {
                "type": "forward",
                "data": {"content": [{"sender": {"user_id": 12}, "message": [segment]}]},
            }
            await nap.emit(message(attachments=[card], mid=101))
            await nap.emit(message("总结", reply=101))
            await eventually(lambda: bool(op.prompts))
            job = bridge.store.latest(Context(777, 11))
            assert json.loads(job["attachments"])[0]["url"] == IMAGE_URL
            paths = json.loads(job["files"])
            assert len(paths) == 2
            assert await asyncio.to_thread(Path(paths[0]).read_bytes) == IMAGE
            assert Path(paths[1]).name == "引用聊天记录.json"
            assert json.loads(await asyncio.to_thread(Path(paths[1]).read_text))
            assert len(op.prompts[0]["files"]) == 2
            assert not any(a["action"] == "download_file_stream" for a in nap.actions)
    finally:
        await server.cleanup()


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("http", "图片链接下载失败"),
        ("redirect", "图片链接下载失败"),
        ("size-header", "附件超过大小限制"),
        ("size-stream", "附件超过大小限制"),
        ("mismatch", "附件下载不完整"),
        ("truncated", "附件下载超时或数据损坏"),
        ("timeout", "附件下载超时或数据损坏"),
    ],
)
async def test_image_download_rejects_failed_incomplete_or_oversized_content(
    tmp_path, monkeypatch, fault, reason
):
    async def image(request):
        if fault == "http":
            return web.Response(status=403)
        if fault == "redirect":
            return web.Response(status=302, headers={"Location": "/unexpected"})
        if fault == "timeout":
            await asyncio.sleep(0.1)
        if fault == "size-stream":
            response = web.StreamResponse()
            response.enable_chunked_encoding()
            await response.prepare(request)
            await response.write(IMAGE)
            await response.write_eof()
            return response
        if fault == "truncated":
            response = web.StreamResponse(headers={"Content-Length": str(len(IMAGE) + 1)})
            response.force_close()
            await response.prepare(request)
            await response.write(IMAGE)
            await response.write_eof()
            return response
        return web.Response(body=IMAGE)

    server, url = await start_server(image)
    try:
        async with aiohttp.ClientSession() as session:
            route_image_download(monkeypatch, session, url)
            bot = OneBot(session, "ws://unused", "")
            item = Attachment("picture", kind="image", url=IMAGE_URL)
            if fault == "mismatch":
                item = Attachment("picture", size=len(IMAGE) + 1, kind="image", url=IMAGE_URL)
            remaining = len(IMAGE) - 1 if fault.startswith("size-") else 1000
            with pytest.raises(AttachmentError, match=reason):
                await bot.download(item, tmp_path, remaining, 0.02 if fault == "timeout" else 1)
            assert not list(tmp_path.iterdir())
    finally:
        await server.cleanup()


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/image",
        "https://multimedia.nt.qq.com.cn.example.org/image",
        "https://user:password@multimedia.nt.qq.com.cn/image",
        "https://multimedia.nt.qq.com.cn:8443/image",
        "https://[invalid/image",
    ],
)
def test_image_segments_ignore_urls_outside_qq_image_cdn(url):
    image = attachment_from_segment("image", {"file": "picture", "url": url})
    assert image.reference == "picture"
    assert image.url is None
