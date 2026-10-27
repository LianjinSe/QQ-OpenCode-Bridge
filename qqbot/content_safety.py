"""Shared redaction helpers for user-visible and persisted content."""

from __future__ import annotations

import json
import re

SECRET = re.compile(r"(?i)(sk-[a-z0-9_-]{20,}|(?:api[_ -]?key|密码|password|token)\s*[:：=]\s*\S+)")


def redact_evidence(text: str) -> str:
    def scrub(value):
        if isinstance(value, dict):
            return {
                key: "[敏感凭据已省略]"
                if re.search(r"(?i)password|secret|token|cookie|authorization|api[_-]?key", key)
                else scrub(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return SECRET.sub("[敏感凭据已省略]", value) if isinstance(value, str) else value

    try:
        result = json.dumps(scrub(json.loads(text)), ensure_ascii=False)
    except (ValueError, TypeError):
        result = SECRET.sub("[敏感凭据已省略]", text)
    return re.sub(
        r'(?i)((?:authorization|cookie|password|secret|token|api[_-]?key)["\s]*[:=]\s*)'
        r'("[^"\n]*"|[^\n,;}]+)',
        r"\1[敏感凭据已省略]",
        result,
    )
