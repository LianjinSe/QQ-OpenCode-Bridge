from __future__ import annotations

import asyncio

import pytest

from qqbot.onebot import DeliveryUnknown, OneBot


class WebSocket:
    closed = False

    async def send_json(self, payload):
        self.payload = payload


def connected_bot():
    bot = OneBot(None, "ws://unused", "unused")
    bot.ws = WebSocket()
    return bot


async def test_normal_stream_completion_unregisters_request():
    bot = connected_bot()
    async with bot.stream_request("download", {}) as frames:
        request = bot.requests[bot.ws.payload["echo"]]
        request.queue.put_nowait({"retcode": 0, "data": {"type": "stream"}})
        request.queue.put_nowait({"retcode": 0, "data": {"type": "response"}})
        result = [frame async for frame in frames]
    assert len(result) == 2
    assert not bot.requests


async def test_early_consumer_exit_unregisters_request():
    bot = connected_bot()
    async with bot.stream_request("download", {}) as frames:
        request = bot.requests[bot.ws.payload["echo"]]
        request.queue.put_nowait({"retcode": 0, "data": {"type": "stream"}})
        assert (await anext(frames))["data"]["type"] == "stream"
    assert not bot.requests
    assert not request.queue._getters


async def test_cancelled_wait_releases_queue_getter_and_request():
    bot = connected_bot()
    async with bot.stream_request("download", {}) as frames:
        request = bot.requests[bot.ws.payload["echo"]]
        pending = asyncio.create_task(anext(frames))
        while not request.queue._getters:
            await asyncio.sleep(0)
        assert request.queue._getters
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
    assert not bot.requests
    assert not request.queue._getters


async def test_timeout_and_disconnect_are_unknown_and_cleanup():
    bot = connected_bot()
    async with bot.stream_request("download", {}) as frames:
        request = bot.requests[bot.ws.payload["echo"]]
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.01):
                await anext(frames)
    assert not bot.requests
    assert not request.queue._getters

    async with bot.stream_request("download", {}) as frames:
        request = bot.requests[bot.ws.payload["echo"]]
        pending = asyncio.create_task(anext(frames))
        await asyncio.sleep(0)
        bot._fail_requests()
        with pytest.raises(DeliveryUnknown):
            await pending
    assert not bot.requests
    assert not request.queue._getters


async def test_missing_terminal_frame_does_not_claim_success():
    bot = connected_bot()
    async with bot.stream_request("download", {}) as frames:
        request = bot.requests[bot.ws.payload["echo"]]
        request.queue.put_nowait({"retcode": 0, "data": {"type": "stream"}})
        request.future.set_result(None)
        assert (await anext(frames))["data"]["type"] == "stream"
        with pytest.raises(DeliveryUnknown):
            await anext(frames)
    assert not bot.requests
