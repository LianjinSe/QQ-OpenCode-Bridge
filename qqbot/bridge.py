from __future__ import annotations

import asyncio
import json
import logging

import aiohttp

from . import messages as copy
from .commands import CommandHandler
from .config import Config
from .conversation import ConversationManager
from .delivery_tools import DeliveryTools
from .events import EventRecorder
from .knowledge import Knowledge
from .memory import PersonalMemory
from .models import Context
from .napcat_tools import NapCatTools
from .onebot import DeliveryUnknown, OneBot, Unavailable
from .opencode import ApiError, OpenCode, ProtocolError
from .router import MessageRouter
from .runner import TaskRunner
from .sender import OutboxSender
from .store import Store
from .tool_identity import TaskIdentityContext, resolve_task
from .typing_status import TypingIndicator
from .webui import AdminDashboard

log = logging.getLogger(__name__)

NETWORK_ERRORS = (aiohttp.ClientError, OSError, TimeoutError, Unavailable, DeliveryUnknown)
STATUS_LABELS = copy.STATUS_LABELS


class Bridge:
    def __init__(self, config: Config, store: Store, onebot: OneBot, opencode: OpenCode):
        self.config, self.store, self.onebot, self.opencode = config, store, onebot, opencode
        self.jobs_ready = asyncio.Event()
        self.outbox_ready = asyncio.Event()
        self.control_lock = asyncio.Lock()
        try:
            self.events = EventRecorder(store=store)
            self.conversations = ConversationManager(config=config, store=store)
            identity = TaskIdentityContext(config, store, opencode)
            self.memory = PersonalMemory(
                config,
                store,
                opencode,
                self.reply,
                identity_resolver=lambda session_id: resolve_task(identity, session_id),
            )
            self.knowledge = Knowledge(
                config,
                config.state_db,
                identity_resolver=lambda session_id: resolve_task(identity, session_id),
            )
            self.napcat_tools = NapCatTools(config, onebot, store, identity)
            self.delivery_tools = DeliveryTools(config, store, onebot, identity)
            self.typing = TypingIndicator(config=config, store=store, onebot=onebot)
            self.commands = CommandHandler(
                config=config,
                store=store,
                onebot=onebot,
                opencode=opencode,
                events=self.events,
                memory=self.memory,
                reply=self.reply,
                jobs_ready=self.jobs_ready,
            )
            self.runner = TaskRunner(
                config=config,
                store=store,
                onebot=onebot,
                opencode=opencode,
                events=self.events,
                typing=self.typing,
                conversations=self.conversations,
                memory=self.memory,
                delivery_tools=self.delivery_tools,
                reply=self.reply,
                jobs_ready=self.jobs_ready,
                outbox_ready=self.outbox_ready,
                control_lock=self.control_lock,
            )
            self.output = OutboxSender(
                config=config,
                store=store,
                onebot=onebot,
                reply=self.reply,
                outbox_ready=self.outbox_ready,
                typing=self.typing,
                events=self.events,
            )
            self.router = MessageRouter(
                config=config,
                store=store,
                onebot=onebot,
                events=self.events,
                command=self.command,
                memory=self.memory,
                reply=self.reply,
                jobs_ready=self.jobs_ready,
                control_lock=self.control_lock,
            )
            self.webui = (
                AdminDashboard(
                    config,
                    store,
                    onebot,
                    opencode,
                    self.knowledge,
                    self.memory,
                    self.control_lock,
                    self.jobs_ready,
                )
                if config.webui_enabled
                else None
            )
        except BaseException:
            # Constructors may open persistent stores before a later component fails.
            # Attempt every cleanup without replacing the exception that broke assembly.
            for service in (
                getattr(self, "memory", None),
                getattr(self, "knowledge", None),
                getattr(self, "napcat_tools", None),
            ):
                state_store = getattr(service, "store", None)
                close_storage = getattr(service, "close_storage", None)
                close_store = getattr(state_store, "close", None)
                close = close_storage or close_store
                if close is None:
                    continue
                try:
                    close()
                except BaseException:
                    log.exception("构造失败时关闭组件存储失败：%s", type(service).__name__)
            raise

    def reply(self, context: Context, text: str, key: str, job_id: str | None = None) -> None:
        self.store.put_outbox(context, text, key, self.config.reply_chunk_size, job_id)
        self.outbox_ready.set()

    async def close(self) -> None:
        """Close every owned asynchronous resource, continuing after individual failures."""
        for resource in (
            self.webui,
            self.delivery_tools,
            self.napcat_tools,
            self.knowledge,
            self.memory,
        ):
            if resource is None:
                continue
            close = getattr(resource, "close", None)
            if close is None:
                continue
            try:
                await close()
            except Exception:
                log.exception("关闭桥接组件失败：%s", type(resource).__name__)
        try:
            await self.onebot.disconnect()
        except Exception:
            log.exception("关闭 NapCat 连接失败")

    async def run(self) -> None:
        self.config.workdir.mkdir(parents=True, exist_ok=True, mode=0o700)
        await self.delivery_tools.start()
        self.store.cleanup(self.config)
        for item in self.store.failed_media():
            uncertain = item["status"] == "uncertain"
            self.reply(
                Context(**json.loads(item["target"])),
                copy.DELIVERY_UNCERTAIN if uncertain else copy.DELIVERY_FAILED,
                f"delivery-{'uncertain' if uncertain else 'failed'}:{item['id']}",
            )
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(self.onebot.run(), name="napcat")
            tasks.create_task(self.event_loop(), name="events")
            tasks.create_task(self.worker(), name="jobs")
            tasks.create_task(self.sender(), name="outbox")
            tasks.create_task(self.maintenance(), name="maintenance")
            tasks.create_task(self.typing.run(), name="typing-status")
            tasks.create_task(self.memory.run(), name="personal-memory")
            tasks.create_task(self.knowledge.run(), name="document-knowledge")
            tasks.create_task(self.napcat_tools.run(), name="napcat-native-tools")
            tasks.create_task(self.delivery_tools.run(), name="attachment-tools")
            if self.webui:
                tasks.create_task(self.webui.run(), name="admin-webui")

    async def event_loop(self) -> None:
        while True:
            event = await self.onebot.events.get()
            try:
                await self.onebot.ready.wait()
                await self.handle_event(event)
            except asyncio.CancelledError:
                raise
            except NETWORK_ERRORS:
                log.warning("处理控制指令时服务连接不可用")
            except (ApiError, ProtocolError, ValueError, KeyError):
                log.exception("事件处理失败")
            finally:
                self.onebot.events.task_done()

    async def handle_event(self, event):
        await self.router.handle_event(event)

    async def command(self, context, event_id, command, args):
        await self.commands.command(context, event_id, command, args)

    async def sender(self):
        await self.output.sender()

    async def worker(self):
        await self.runner.worker()

    async def execute(self, job_id):
        await self.runner.execute(job_id)

    async def maintenance(self):
        while True:
            await asyncio.sleep(60)
            self.store.cleanup(self.config)
