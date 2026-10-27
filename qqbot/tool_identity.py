"""Resolve an active native tool call to its real QQ root task."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .job_state import ACTIVE_TOOL_STATUSES
from .models import Context


@dataclass(frozen=True)
class TaskIdentityContext:
    config: object
    store: object
    opencode: object


async def resolve_task(identity: TaskIdentityContext, session_id: str):
    """Resolve and revalidate the real root task for an OpenCode session."""
    return await _active_task(identity.store, identity.config, identity.opencode, session_id)


async def _active_task(store, config, opencode, session_id):
    if not isinstance(session_id, str) or not 1 <= len(session_id) <= 200:
        raise PermissionError
    rows = store.active_tool_jobs()
    for row in rows:
        snapshot = dict(row)
        if row["session_id"] != session_id:
            try:
                if not await opencode.belongs_to(session_id, row["session_id"]):
                    continue
            except Exception:
                raise PermissionError from None
        current = store.job(row["id"])
        if (
            not current
            or current["cancel_requested"]
            or current["status"] not in {state.value for state in ACTIVE_TOOL_STATUSES}
            or current["session_id"] != snapshot["session_id"]
            or current["target"] != snapshot["target"]
        ):
            raise PermissionError
        context = Context(**json.loads(snapshot["target"]))
        if (context.group_id is None and context.user_id not in config.allowed_users) or (
            context.group_id is not None and context.group_id not in config.allowed_groups
        ):
            raise PermissionError
        return current, context
    raise PermissionError
