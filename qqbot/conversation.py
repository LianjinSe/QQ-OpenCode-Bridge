from __future__ import annotations

import json

from .models import Context
from .opencode import ProtocolError


class ConversationManager:
    def __init__(self, *, config, store):
        self.config = config
        self.store = store

    def compose(self, job: dict) -> tuple[str, int]:
        if job["submitted_text"] is not None:
            return job["submitted_text"], job["submit_cursor"] or 0
        context = Context(**json.loads(job["target"]))
        if context.group_id is None or job["generation"] is None:
            return job["text"], 0
        state = self.store.group_state_for_compose(context)
        if state["generation"] != job["generation"]:
            raise ProtocolError("任务的群会话代次已失效")
        rows = [
            r
            for r in json.loads(job["background_snapshot"] or "[]")
            if job.get("memory_isolated") or r["seq"] > state["cursor"]
        ]
        budget = self.config.group_background_max_chars
        selected = []
        used = 0
        omitted = False
        for row in reversed(rows):
            record = json.loads(row["payload"])
            entry = json.dumps(record, ensure_ascii=False)
            remaining = budget - used
            if remaining <= 0:
                omitted = True
                break
            if len(entry) > remaining:
                # Keep attribution and an explicit truncation marker for long messages.
                marker = "…[本条背景已截断]"
                selected.append(entry[: max(0, remaining - len(marker))] + marker[:remaining])
                omitted = True
                break
            selected.append(entry)
            used += len(entry) + 1
        source = json.loads(job["source_payload"] or "{}")
        actor = {
            "QQ": context.user_id,
            "昵称": source.get("nickname", ""),
            "时间": source.get("time"),
            "消息编号": job["source_event"],
        }
        sections = []
        if omitted:
            sections.append("[背景超过字符预算，已省略或截断较早内容]")
        if selected:
            sections.append("群聊背景：\n" + "\n".join(reversed(selected)))
        sections.append("本次任务发起人：" + json.dumps(actor, ensure_ascii=False))
        sections.append("本次要求（包含明确引用的资料）：\n" + job["text"])
        return "\n\n".join(sections), job["background_cutoff"] or state["cursor"]
