from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .models import Context

log = logging.getLogger(__name__)


class EventRecorder:
    def __init__(self, *, store):
        self.store = store

    def record(
        self, context: Context, event_id: str, stage: str, reason: str, job_id: str | None = None
    ) -> None:
        # Only stable reason codes enter this table/log, never message or tool contents.
        started = self.store.record_diagnostic(
            context.conversation_key, event_id, context.user_id, stage, reason, job_id, time.time()
        )
        if started is None:
            return
        log.info(
            "event=%s conversation=%s job=%s stage=%s reason=%s elapsed_ms=%d",
            event_id,
            context.conversation_key,
            job_id or "-",
            stage,
            reason,
            int((time.time() - started) * 1000),
        )

    def job(self, job_id: str, stage: str, reason: str) -> None:
        job = self.store.job(job_id)
        self.record(
            Context(**json.loads(job["target"])),
            job["source_event"] or job_id,
            stage,
            reason,
            job_id,
        )

    def render(self, context: Context, event_id: str) -> str:
        rows = self.store.trace(context, event_id)
        if not rows:
            return "未找到这条消息的处理记录，可能未收到或已经超过保留期。"
        lines = [f"消息 {event_id} 的处理记录（北京时间）："]
        for row in rows:
            stamp = datetime.fromtimestamp(row["created"], ZoneInfo("Asia/Shanghai"))
            lines.append(
                f"{stamp:%m-%d %H:%M:%S} {row['stage']} / {row['reason']}"
                + (f"；任务 {row['job_id']}" if row["job_id"] else "")
            )
        return "\n".join(lines)
