from __future__ import annotations

import asyncio
import logging
import time

import aiohttp

from .models import Context
from .onebot import ActionError, DeliveryUnknown, Unavailable

log = logging.getLogger(__name__)


class TypingIndicator:
    """Keep private-chat typing status in step with the serial task worker."""

    def __init__(self, *, config, store, onebot):
        self.config, self.store, self.onebot = config, store, onebot
        self.changed = asyncio.Event()
        self.current: Context | None = None
        self.connection = None
        self.last_refresh = float("-inf")
        self.retry_after = 0.0
        self.force_refresh = False
        self.failure_logged = False

    def wake(self) -> None:
        self.changed.set()

    def message_sent(self, context: Context) -> None:
        # QQ may clear typing when a progress message arrives. Restore it if still busy.
        if context == self.current:
            self.force_refresh = True
            self.wake()

    async def send(self, context: Context, active: bool) -> bool:
        try:
            success = await self.onebot.set_typing(context, active)
        except (
            aiohttp.ClientError,
            OSError,
            TimeoutError,
            ActionError,
            Unavailable,
            DeliveryUnknown,
        ):
            if not self.failure_logged:
                log.warning("更新私聊输入状态失败；任务和消息发送继续正常执行")
                self.failure_logged = True
            return False
        if success:
            self.failure_logged = False
        return success

    async def sync(self) -> None:
        desired = (
            self.store.typing_context(self.onebot.self_id)
            if self.config.typing_status_enabled
            else None
        )
        if not self.onebot.ready.is_set() or not self.onebot.online:
            self.connection = None
            return
        reconnected = self.connection is not self.onebot.ws
        self.connection = self.onebot.ws
        if self.current != desired:
            previous, self.current = self.current, desired
            if previous is not None:
                await self.send(previous, False)
            self.last_refresh = float("-inf")
            self.retry_after = 0.0
        if desired is None:
            self.force_refresh = False
            return
        now = time.monotonic()
        if now < self.retry_after and not reconnected:
            return
        if (
            reconnected
            or self.force_refresh
            or now - self.last_refresh >= self.config.typing_refresh_interval
        ):
            self.force_refresh = False
            self.last_refresh = now
            if await self.send(desired, True):
                self.retry_after = 0.0
            else:
                self.retry_after = now + max(30, self.config.typing_refresh_interval)

    async def run(self) -> None:
        try:
            while True:
                self.changed.clear()
                await self.sync()
                try:
                    async with asyncio.timeout(min(0.5, self.config.typing_refresh_interval)):
                        await self.changed.wait()
                except TimeoutError:
                    pass
        finally:
            if self.current is not None:
                await self.send(self.current, False)
                self.current = None
