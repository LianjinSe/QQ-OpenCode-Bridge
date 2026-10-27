from __future__ import annotations

import logging

import aiohttp

from . import messages as copy
from .forward import (
    CardLinkUnavailable,
    ForwardError,
    ForwardLimitError,
    chat_attachment,
    chat_prompt,
)
from .models import excluded, normalize, unique_attachments
from .onebot import ActionError, AttachmentError, DeliveryUnknown, Unavailable
from .policy import is_superadmin

log = logging.getLogger(__name__)

NETWORK_ERRORS = (aiohttp.ClientError, OSError, TimeoutError, Unavailable, DeliveryUnknown)
STATUS_LABELS = copy.STATUS_LABELS


class MessageRouter:
    def __init__(
        self, *, config, store, onebot, events, command, memory, reply, jobs_ready, control_lock
    ):
        self.config, self.store, self.onebot = config, store, onebot
        self.events, self.command, self.memory = events, command, memory
        self.reply, self.jobs_ready, self.control_lock = reply, jobs_ready, control_lock

    async def handle_event(self, event: dict) -> None:
        incoming = normalize(event)
        if incoming is None or incoming.context.self_id != self.onebot.self_id:
            return
        context = incoming.context

        def record(stage, reason):
            self.events.record(context, incoming.event_id, stage, reason)

        record("received", "message_received")
        if context.group_id is None and context.user_id not in self.config.allowed_users:
            record("filtered", "user_not_allowed")
            return
        if context.group_id is not None and context.group_id not in self.config.allowed_groups:
            record("filtered", "group_not_allowed")
            return
        if not self.store.claim_event(context, incoming.event_id):
            record("filtered", "duplicate_event")
            return
        if excluded(incoming.command_text, self.config.excluded_prefixes):
            self.store.clear_staging(context)
            record("filtered", "excluded_prefix")
            return
        text = incoming.text.strip()
        parts = incoming.command_text.split(maxsplit=1)
        command = parts[0].casefold() if parts else ""
        arguments = parts[1] if len(parts) > 1 else ""
        commands = {
            "/help",
            "/status",
            "/cancel",
            "/new",
            "/approve",
            "/reject",
            "/answer",
            "/trace",
        }
        admin_decision = (
            context.group_id is not None
            and is_superadmin(self.config, context)
            and command in {"/approve", "/reject"}
        )
        if incoming.notice:
            record("filtered", "notice_ignored")
            return
        triggered = context.group_id is None or incoming.mentioned or admin_decision
        if command in commands:
            if triggered:
                record("command", "control_command")
                async with self.control_lock:
                    await self.command(context, incoming.event_id, command, arguments)
            else:
                record("filtered", "command_without_mention")
            return
        if triggered and self.config.memory_enabled:
            if await self.memory.control(incoming):
                record("command", "memory_control")
                return
        if not triggered:
            self.store.record_group(incoming)
            self.store.cleanup(self.config)
            record("background", "not_mentioned")
            return
        # Reply-only mentions must acquire a default instruction BEFORE reading the quote.
        if incoming.reply_id is not None and incoming.mentioned and not incoming.body_text:
            text = "看看这个"

        def background(reason):
            self.store.record_group(incoming)
            self.store.cleanup(self.config)
            record("filtered", reason)

        # Files and merged-forward cards are handled only when subsequently quoted.
        if incoming.forwards or any(item.kind == "file" for item in incoming.attachments):
            background("attachment_waiting_for_quote")
            return
        if (
            context.group_id is None
            and not text
            and incoming.attachments
            and all(item.kind == "image" for item in incoming.attachments)
        ):
            record("filtered", "private_image_waiting_for_text")
            return
        key = f"in:{context.key}:{incoming.event_id}"
        # Legacy staging is not used; earlier attachments must be explicitly quoted.
        attachments = list(incoming.attachments)
        if incoming.reply_id is not None and text:
            try:
                quoted = await self.onebot.reply_content(
                    context,
                    incoming.reply_id,
                    trusted_bot_reply=self.store.sent_to(context, incoming.reply_id),
                )
                attachments += quoted.attachments
                if quoted.chat_records:
                    attachments.append(chat_attachment(quoted.chat_records))
                text = chat_prompt(text, quoted.chat_records, quoted.quoted_text, quoted.card_links)
                record("quote", "quote_loaded")
            except CardLinkUnavailable:
                background("card_link_unavailable")
                self.reply(context, copy.CARD_LINK_UNAVAILABLE, key)
                return
            except ForwardLimitError:
                background("quote_limit")
                self.reply(context, copy.FORWARD_LIMIT, key)
                return
            except (ForwardError, ActionError, AttachmentError, *NETWORK_ERRORS):
                background("quote_unavailable")
                self.reply(context, copy.QUOTE_UNAVAILABLE, key)
                return
        attachments = unique_attachments(attachments)
        if (
            len(attachments) > self.config.max_attachments
            or sum(item.size or 0 for item in attachments) > self.config.max_attachment_bytes
        ):
            self.store.clear_staging(context)
            background("attachment_limit")
            self.reply(context, copy.ATTACHMENT_LIMIT, key)
            return
        if not text and not attachments:
            background("empty_message")
            return
        unfinished = self.store.conversation_jobs(context)
        parent = next(
            (
                job
                for job in unfinished
                if context.group_id is None
                and not job["cancel_requested"]
                and job["status"] in {"preparing", "submitting", "running", "waiting"}
            ),
            None,
        )
        pending_steers = len(self.store.steers(parent["id"], pending_only=True)) if parent else 0
        if len(unfinished) + pending_steers >= self.config.max_queued_per_context:
            background("queue_full")
            self.reply(context, copy.QUEUE_FULL, key)
            return
        job_id = self.store.enqueue(
            context,
            text or "请查看附件并说明内容。",
            attachments,
            incoming=incoming,
            config=self.config,
            steer_parent_id=parent["id"] if parent else None,
        )
        self.memory.capture(job_id, context, incoming.text)
        self.store.cleanup(self.config)
        self.events.job(
            job_id,
            "steering" if parent else "queued",
            "steer_created" if parent else "task_created",
        )
        self.store.clear_staging(context)
        if not parent and any(job["status"] != "queued" for job in unfinished):
            self.reply(context, copy.QUEUED, key)
        self.jobs_ready.set()
