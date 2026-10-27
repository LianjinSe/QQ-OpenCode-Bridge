from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from contextlib import suppress
from urllib.parse import urlsplit

import aiohttp

from .bridge import NETWORK_ERRORS, Bridge
from .config import Config, ConfigError
from .logging_utils import configure_logging
from .onebot import OneBot
from .opencode import ApiError, OpenCode, ProtocolError
from .store import Store

log = logging.getLogger(__name__)


async def serve(config: Config, check: bool = False) -> None:
    formatter = configure_logging(
        config.log_level,
        config.napcat_token,
        config.opencode_password,
        config.memory_api_key,
        config.memory_database_url,
        urlsplit(config.memory_database_url).password or "",
    )
    async with aiohttp.ClientSession() as http:
        onebot = OneBot(http, config.napcat_url, config.napcat_token)
        opencode = OpenCode(http, config, formatter.add_secret)
        if check:
            info = await opencode.ensure(allow_start=False)
            log.info("OpenCode API 检查通过，版本=%s", info["version"])
            try:
                await onebot.connect()
                if not onebot.online:
                    raise RuntimeError("NapCat QQ 当前离线")
                log.info("NapCat 认证、登录信息及在线状态检查通过")
            finally:
                await onebot.disconnect()
            return
        try:
            info = await opencode.ensure()
            log.info("已连接 OpenCode %s", info["version"])
        except (ApiError, ProtocolError, *NETWORK_ERRORS):
            log.warning("OpenCode 暂不可用，已接收任务会等待服务恢复")
        store = Store(config.state_db, initialize=False)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        registered_signals = []
        bridge = None
        task = None
        stopping = None
        try:
            store.initialize()
            for signum in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(signum, stop.set)
                registered_signals.append(signum)
            bridge = Bridge(config, store, onebot, opencode)
            task = asyncio.create_task(bridge.run())
            stopping = asyncio.create_task(stop.wait())
            done, _ = await asyncio.wait({task, stopping}, return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                await task
        finally:
            for pending in (task, stopping):
                if pending is not None:
                    pending.cancel()
            await asyncio.gather(
                *(pending for pending in (task, stopping) if pending is not None),
                return_exceptions=True,
            )
            if bridge is not None:
                await bridge.close()
            else:
                await onebot.disconnect()
            store.close()
            for signum in registered_signals:
                loop.remove_signal_handler(signum)


def main() -> None:
    parser = argparse.ArgumentParser(description="NapCat / QQ ↔ OpenCode v2 桥接服务")
    parser.add_argument("--env-file", default=".env", help="环境变量配置文件（默认 .env）")
    parser.add_argument("--check", action="store_true", help="只检查连接，不提交任务或启动服务")
    args = parser.parse_args()
    try:
        config = Config.from_env(args.env_file)
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        raise SystemExit(2) from None
    try:
        asyncio.run(serve(config, args.check))
    except KeyboardInterrupt:
        pass
    except Exception:
        log.exception("桥接服务启动或运行失败")
        raise SystemExit(1) from None


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        main()
