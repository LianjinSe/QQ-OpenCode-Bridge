"""Small policy helpers shared by memory tools and the memory coordinator."""

from __future__ import annotations

import re
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Asia/Shanghai")
RECALL = re.compile(r"记得|记忆|回忆|之前|以前|上次|原话|聊天记录|日记|说过|聊过|还记着")
RECALL_REQUEST = re.compile(
    r"你.{0,8}记得|你.{0,8}记着|回顾|查查|查一下|查找|找找|找一下|看看|讲讲|说说|告诉我|"
    r"吗|么|什么|如何|怎么|哪里|哪天|哪次|多少|何时|谁|[？?]"
)


def requests_recall(text):
    return bool(RECALL.search(text) and RECALL_REQUEST.search(text))
