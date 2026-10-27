from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress

import aiohttp

from . import messages as copy
from .delivery import DeliveryCancelled, DeliveryError, read_snapshot
from .models import Context
from .onebot import ActionError, AttachmentError, DeliveryUnknown, Unavailable

log = logging.getLogger(__name__)

NETWORK_ERRORS = (aiohttp.ClientError, OSError, TimeoutError, Unavailable, DeliveryUnknown)
STATUS_LABELS = copy.STATUS_LABELS


class OutboxSender:
    def __init__(self, *, config, store, onebot, reply, outbox_ready, typing, events):
        self.config, self.store, self.onebot = config, store, onebot
        self.reply, self.outbox_ready = reply, outbox_ready
        self.typing, self.events = typing, events

    def text_delay(self, text: str) -> float:
        return min(
            self.config.text_typing_max_delay,
            max(
                self.config.text_typing_min_delay,
                len(text) / self.config.text_typing_chars_per_second,
            ),
        )

    async def sender(self) -> None:
        while True:
            await self.onebot.ready.wait()
            item = self.store.next_outbox(self.onebot.self_id)
            if item is None or not self.onebot.online:
                self.outbox_ready.clear()
                with suppress(TimeoutError):
                    async with asyncio.timeout(1):
                        await self.outbox_ready.wait()
                continue
            if item["job_id"] is not None and self.store.job(item["job_id"])["cancel_requested"]:
                self.store.update_outbox(item["id"], "blocked")
                continue
            context = Context(**json.loads(item["target"]))
            if item["kind"] == "text":
                # Keep the item ready during the simulated typing delay: no QQ request
                # has been sent, so a restart can safely resume this message.
                await asyncio.sleep(self.text_delay(item["text"]))
                if (
                    item["job_id"] is not None
                    and self.store.job(item["job_id"])["cancel_requested"]
                ):
                    self.store.update_outbox(item["id"], "blocked")
                    continue
                if (
                    not self.onebot.ready.is_set()
                    or not self.onebot.online
                    or context.self_id != self.onebot.self_id
                ):
                    continue
            media = item["kind"] in {"image", "video", "audio", "file"}
            uploading = media
            self.store.update_outbox(item["id"], "uploading" if uploading else "sending")
            retry_delay = 0.2
            try:
                if item["kind"] == "text":
                    result = await self.onebot.send_text(
                        context, item["text"], bool(item["first_chunk"])
                    )
                elif item["kind"] == "poke":
                    if item["job_id"] is None or self.store.job(item["job_id"])["status"] != "done":
                        self.store.update_outbox(item["id"], "blocked")
                        continue
                    result = await self.onebot.send_poke(context)
                else:
                    payload = json.loads(item["payload"])
                    data = await asyncio.to_thread(
                        read_snapshot, payload, self.config, item["job_id"]
                    )
                    remote_path = await self.onebot.upload_file(
                        data,
                        payload["name"],
                        self.config.download_timeout,
                        lambda job_id=item["job_id"]: bool(
                            self.store.job(job_id)["cancel_requested"]
                        ),
                    )
                    if self.store.job(item["job_id"])["cancel_requested"]:
                        raise DeliveryCancelled("回传已取消")
                    self.store.update_outbox(item["id"], "sending")
                    uploading = False
                    result = await self.onebot.send_media(
                        context,
                        remote_path,
                        payload["name"],
                        item["kind"],
                        self.config.download_timeout,
                    )
                self.store.update_outbox(
                    item["id"], "sent", result.get("message_id", result.get("file_id"))
                )
                if item["kind"] != "poke":
                    self.typing.message_sent(context)
            except Unavailable:
                self.store.update_outbox(item["id"], "ready")
            except DeliveryCancelled:
                self.store.update_outbox(item["id"], "blocked")
            except (DeliveryUnknown, TimeoutError):
                if uploading:
                    self.store.update_outbox(item["id"], "ready")
                    retry_delay = 2
                else:
                    self.store.update_outbox(item["id"], "uncertain")
                    log.warning("QQ 回复发送结果不确定，outbox=%s", item["id"])
                    if media:
                        self.reply(
                            context, copy.DELIVERY_UNCERTAIN, f"delivery-uncertain:{item['id']}"
                        )
            except (
                ActionError,
                AttachmentError,
                DeliveryError,
                OSError,
                ValueError,
                KeyError,
            ) as exc:
                self.store.update_outbox(item["id"], "failed")
                log.warning(
                    "QQ 出站动作失败，kind=%s，outbox=%s，原因=%s", item["kind"], item["id"], exc
                )
                if media:
                    self.reply(context, copy.DELIVERY_FAILED, f"delivery-failed:{item['id']}")
            if item["job_id"] is not None:
                state = self.store.outbox_status(item["id"])
                self.events.job(item["job_id"], "delivery", "outbox_" + state)
                self.store.finish_delivery(item["job_id"])
            await asyncio.sleep(retry_delay)
