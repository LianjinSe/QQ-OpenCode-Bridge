"""Read models for the admin UI; production databases are always opened read-only."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

import psycopg2
from aiohttp import ClientError

from .content_safety import redact_evidence
from .opencode import ApiError, OpenCode, ProtocolError, path_id

UNFINISHED = (
    "queued",
    "preparing",
    "submitting",
    "running",
    "waiting",
    "cancelling",
    "reply_ready",
    "delivering",
    "steering",
    "steered",
)


@contextmanager
def readonly(path: Path):
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def duration(stamp, *, start="created"):
    if not isinstance(stamp, dict):
        return None
    begin, end = stamp.get(start), stamp.get("completed")
    if not all(isinstance(value, (int, float)) for value in (begin, end)):
        return None
    return max(0, end - begin)


def metrics(messages):
    result = {
        "tools": 0,
        "tool_errors": 0,
        "tool_running": 0,
        "reasoning_ms": None,
        "reasoning_missing": 0,
        "model_ms": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "cache_read_tokens": 0,
        "model_calls": 0,
    }
    names = Counter()
    reasoning = []
    for message in messages:
        if message.get("type") != "assistant":
            continue
        result["model_calls"] += 1
        result["model_ms"] += duration(message.get("time")) or 0
        tokens = message.get("tokens") or {}
        for field in ("input", "output", "reasoning"):
            value = tokens.get(field, 0)
            if isinstance(value, (int, float)):
                result[field + "_tokens"] += value
        result["cache_read_tokens"] += (tokens.get("cache") or {}).get("read", 0)
        for part in message.get("content", []):
            if part.get("type") == "tool":
                result["tools"] += 1
                names[part.get("name", "unknown")] += 1
                status = (part.get("state") or {}).get("status")
                result["tool_errors"] += status == "error"
                result["tool_running"] += status not in {"completed", "error"}
            elif part.get("type") == "reasoning":
                elapsed = duration(part.get("time"))
                if elapsed is None:
                    result["reasoning_missing"] += 1
                else:
                    reasoning.append(elapsed)
    if reasoning:
        result["reasoning_ms"] = sum(reasoning)
    result["tool_names"] = dict(names.most_common())
    return result


class DashboardData:
    def __init__(self, config, onebot, opencode, knowledge=None, memory=None):
        self.config, self.onebot, self.opencode = config, onebot, opencode
        self.knowledge, self.memory = knowledge, memory
        self.cache = {}
        self.remote_limit = asyncio.Semaphore(2)
        self.history = lambda: []
        self.knowledge_health_lock = Lock()

    def knowledge_status(self):
        service = self.knowledge
        result = {"enabled": self.config.knowledge_enabled, "ready": False, "error": False}
        if not result["enabled"] or service is None:
            return result
        if service.backend_error:
            return {**result, "error": True}
        catalogue = service.root / "catalogue.sqlite3"
        if not catalogue.is_file():
            return result
        try:
            with readonly(catalogue) as db:
                db.execute("SELECT 1 FROM libraries LIMIT 1")
        except (sqlite3.Error, OSError):
            return {**result, "error": True}
        # The overview refreshes frequently. Probe only the local PostgreSQL connection,
        # never initialize a vector store or invoke an embedding/chat model here.
        with self.knowledge_health_lock:
            cached = self.cache.get("knowledge-health")
            if cached and time.monotonic() - cached[0] < 30:
                ready = cached[1]
            else:
                try:
                    connection = psycopg2.connect(
                        self.config.memory_database_url,
                        connect_timeout=2,
                        options="-c statement_timeout=1000",
                    )
                    try:
                        connection.set_session(readonly=True, autocommit=True)
                        with connection.cursor() as cursor:
                            cursor.execute("SELECT 1")
                            ready = cursor.fetchone() == (1,)
                    finally:
                        connection.close()
                except psycopg2.Error:
                    ready = False
                self.cache["knowledge-health"] = (time.monotonic(), ready)
        return {**result, "ready": ready, "error": not ready}

    def clean(self, value):
        """Redact configured credentials as well as credential-shaped fields."""
        secrets = sorted(
            {
                self.config.napcat_token,
                self.config.opencode_password,
                self.config.memory_api_key,
                self.config.memory_database_url,
                *self.opencode.headers.values(),
            },
            key=len,
            reverse=True,
        )

        def scrub(item):
            if isinstance(item, dict):
                return {
                    key: "[敏感凭据已省略]"
                    if re.search(
                        r"(?i)(?:^|_)(?:password|secret|cookie|authorization|api_key|"
                        r"access_token|refresh_token|token)(?:$|_)",
                        key,
                    )
                    else scrub(content)
                    for key, content in item.items()
                }
            if isinstance(item, list):
                return [scrub(content) for content in item]
            if isinstance(item, str):
                for secret in secrets:
                    if secret:
                        item = item.replace(secret, "[敏感凭据已省略]")
                return redact_evidence(item)
            return item

        return scrub(value)

    def overview(self):
        with readonly(self.config.state_db) as db:
            counts = dict(db.execute("SELECT status,COUNT(*) FROM jobs GROUP BY status"))
            outbox = dict(db.execute("SELECT status,COUNT(*) FROM outbox GROUP BY status"))
            pending = db.execute(
                "SELECT COUNT(*) FROM interactions WHERE state='pending'"
            ).fetchone()[0]
            conversations = db.execute("SELECT COUNT(DISTINCT conversation) FROM jobs").fetchone()[
                0
            ]
        memory = {"enabled": self.config.memory_enabled, "entries": 0, "archive": 0, "work": 0}
        backend = getattr(self.memory, "backend", None)
        memory["ready"] = bool(backend and getattr(backend, "memory", None) is not None)
        if self.config.memory_enabled and self.config.memory_db.is_file():
            with readonly(self.config.memory_db) as db:
                owner = self.memory_owner()
                memory.update(
                    entries=db.execute(
                        "SELECT COUNT(*) FROM entries WHERE owner=? AND state='active' "
                        "AND (expires IS NULL OR expires>?)",
                        (owner, time.time()),
                    ).fetchone()[0],
                    archive=db.execute(
                        "SELECT COUNT(*) FROM archive WHERE owner=? AND suppressed=0", (owner,)
                    ).fetchone()[0],
                    work=db.execute(
                        "SELECT COUNT(*) FROM work WHERE owner=? "
                        "AND state IN ('ready','running','failed')",
                        (owner,),
                    ).fetchone()[0],
                )
        return {
            "jobs": counts,
            "unfinished": sum(counts.get(s, 0) for s in UNFINISHED),
            "outbox": outbox,
            "pending_interactions": pending,
            "conversations": conversations,
            "memory": memory,
            "knowledge": self.knowledge_status(),
        }

    def conversations(self, query="", before=None, limit=40):
        with readonly(self.config.state_db) as db:
            rows = db.execute(
                "SELECT conversation,MAX(created) AS updated,COUNT(*) AS jobs FROM jobs "
                "WHERE steer_parent_id IS NULL AND conversation IN "
                "(SELECT conversation FROM jobs WHERE instr(lower(text),lower(?))>0 "
                "OR instr(conversation,?)>0 OR instr(source_payload,?)>0) "
                "GROUP BY conversation ORDER BY updated DESC,conversation LIMIT ? OFFSET ?",
                (query, query, query, limit + 1, before or 0),
            ).fetchall()
            result = []
            for row in rows[:limit]:
                item = dict(row)
                latest = dict(
                    db.execute(
                        "SELECT * FROM jobs WHERE conversation=? AND steer_parent_id IS NULL "
                        "ORDER BY created DESC,id DESC LIMIT 1",
                        (row["conversation"],),
                    ).fetchone()
                )
                target = json.loads(latest["target"])
                item.update(
                    target=target,
                    kind="group" if target.get("group_id") else "private",
                    title=(
                        f"群聊 {target['group_id']}"
                        if target.get("group_id")
                        else f"私聊 {target['user_id']}"
                    ),
                    preview=(latest["memory_source_text"] or latest["text"])[:160],
                    status=latest["status"],
                    latest_job=latest["id"],
                    current_session_id=(
                        current[0]
                        if (
                            current := db.execute(
                                "SELECT session_id FROM group_sessions WHERE conversation=?"
                                if target.get("group_id")
                                else "SELECT session_id FROM sessions WHERE context=?",
                                (row["conversation"],),
                            ).fetchone()
                        )
                        else None
                    ),
                )
                result.append(item)
        return self.clean({"items": result, "more": len(rows) > limit})

    @staticmethod
    def job_summary(row):
        item = dict(row)
        return {
            key: item[key]
            for key in (
                "id",
                "conversation",
                "status",
                "created",
                "elapsed",
                "result",
                "error",
                "session_id",
                "prompt_id",
                "cancel_requested",
                "steer_parent_id",
            )
        } | {
            "text": item["memory_source_text"] or item["text"],
            "target": json.loads(item["target"]),
            "attachments": json.loads(item["attachments"]),
        }

    def jobs(self, conversation=None, *, before=None, unfinished=False, limit=30):
        clauses, args = ["steer_parent_id IS NULL"], []
        if conversation:
            clauses.append("conversation=?")
            args.append(conversation)
        if unfinished:
            clauses.append("status IN (" + ",".join("?" for _ in UNFINISHED) + ")")
            args.extend(UNFINISHED)
        with readonly(self.config.state_db) as db:
            if before:
                boundary = db.execute("SELECT created FROM jobs WHERE id=?", (before,)).fetchone()
                if boundary is None:
                    raise ValueError("分页任务不存在")
                clauses.append("(created<? OR (created=? AND id<?))")
                args.extend([boundary[0], boundary[0], before])
            rows = db.execute(
                "SELECT * FROM jobs WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created DESC,id DESC LIMIT ?",
                [*args, limit + 1],
            ).fetchall()
            items = []
            for row in rows[:limit]:
                item = self.job_summary(row)
                item["steers"] = [
                    self.job_summary(steer)
                    for steer in db.execute(
                        "SELECT * FROM jobs WHERE steer_parent_id=? ORDER BY created,rowid",
                        (row["id"],),
                    )
                ]
                items.append(item)
        return self.clean(
            {
                "items": items,
                "next": items[-1]["id"] if len(rows) > limit else None,
            }
        )

    def local_job(self, job_id):
        with readonly(self.config.state_db) as db:
            job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if job is None:
                raise KeyError(job_id)
            steers = db.execute(
                "SELECT * FROM jobs WHERE steer_parent_id=? ORDER BY created,id", (job_id,)
            ).fetchall()
            events = [
                dict(row)
                for row in db.execute(
                    "SELECT stage,reason,created,event_id FROM diagnostic_events "
                    "WHERE job_id=? ORDER BY id",
                    (job_id,),
                )
            ]
            deliveries = [
                dict(row)
                for row in db.execute(
                    "SELECT id,kind,status,created,message_id,text FROM outbox "
                    "WHERE job_id=? ORDER BY id",
                    (job_id,),
                )
            ]
            interactions = [
                dict(row)
                for row in db.execute(
                    "SELECT code,kind,state,created,payload FROM interactions WHERE job_id=? "
                    "ORDER BY created",
                    (job_id,),
                )
            ]
        result = self.job_summary(job)
        result.update(
            steers=[self.job_summary(row) for row in steers],
            events=events,
            deliveries=deliveries,
            interactions=interactions,
            submitted_text=job["submitted_text"],
        )
        return self.clean(result)

    def client(self):
        # UI failures must not mutate the worker client's availability or parent cache.
        client = OpenCode(self.opencode.http, self.config)
        client.discover()
        return client

    async def job_detail(self, job_id):
        local = await asyncio.to_thread(self.local_job, job_id)
        local.update(messages=[], metrics=metrics([]), remote_error=None, complete=False)
        if not local["session_id"]:
            return local
        key = (job_id, local["status"], len(local["steers"]))
        cached = self.cache.get(key)
        if cached and time.monotonic() - cached[0] < 3:
            return local | cached[1]
        async with self.remote_limit, asyncio.timeout(25):
            client = self.client()
            prompt_ids = {local["prompt_id"], *(row["prompt_id"] for row in local["steers"])}
            found, messages, cursor, visited = False, [], None, set()
            for _ in range(100):
                params = {"limit": "100", **({"cursor": cursor} if cursor else {"order": "desc"})}
                page = await client.request(
                    "GET",
                    f"/api/session/{path_id(local['session_id'])}/message",
                    params=params,
                    unwrap=False,
                )
                if not isinstance(page, dict) or not isinstance(page.get("data"), list):
                    raise ProtocolError("OpenCode 消息列表无效")
                for message in page["data"]:
                    messages.append(message)
                    if message.get("id") == local["prompt_id"]:
                        found = True
                        break
                cursor = page.get("cursor", {}).get("next")
                if found or not cursor:
                    break
                if cursor in visited:
                    raise ProtocolError("OpenCode 消息分页未前进")
                visited.add(cursor)
            if not found:
                local["remote_error"] = "未找到本轮原始提交，记录可能已删除或超过读取上限。"
                return local
            turn = []
            for message in reversed(messages):
                if message.get("type") == "user" and message.get("id") not in prompt_ids:
                    break
                turn.append(message)
            remote = {
                "messages": [self.message(message) for message in turn],
                "metrics": metrics(turn),
                "complete": True,
            }
            if len(self.cache) >= 8:
                self.cache.pop(next(iter(self.cache)))
            self.cache[key] = (time.monotonic(), self.clean(remote))
            return local | self.clean(remote)

    @staticmethod
    def message(message):
        result = {
            key: message.get(key)
            for key in (
                "id",
                "type",
                "time",
                "text",
                "model",
                "agent",
                "finish",
                "tokens",
                "error",
                "description",
                "summary",
                "command",
                "output",
            )
        }
        result["files"] = [
            {key: item.get(key) for key in ("name", "filename", "mime", "type", "path")}
            for item in message.get("files", [])
            if isinstance(item, dict)
        ]
        parts = []
        for part in message.get("content", []):
            kind = part.get("type")
            if kind == "tool":
                state = part.get("state") or {}
                parts.append(
                    {
                        "type": kind,
                        "id": part.get("id"),
                        "name": part.get("name"),
                        "time": part.get("time"),
                        "duration_ms": duration(
                            part.get("time"),
                            start="ran" if (part.get("time") or {}).get("ran") else "created",
                        ),
                        "status": state.get("status"),
                        "input": state.get("input"),
                        "output": [
                            {
                                key: item.get(key)
                                for key in ("type", "text", "path", "name", "mimeType")
                                if key in item
                            }
                            for item in state.get("content", [])
                            if isinstance(item, dict)
                        ],
                        "error": state.get("error"),
                    }
                )
            elif kind in {"text", "reasoning"}:
                parts.append(
                    {
                        "type": kind,
                        "text": part.get("text", ""),
                        "time": part.get("time"),
                        "duration_ms": duration(part.get("time")),
                    }
                )
            else:
                parts.append(
                    {key: part.get(key) for key in ("type", "name", "path", "text") if key in part}
                )
        result["content"] = parts
        return result

    async def allowed_session(self, client, session_id):
        with readonly(self.config.state_db) as db:
            roots = {
                row[0]
                for row in db.execute(
                    "SELECT DISTINCT session_id FROM jobs WHERE session_id IS NOT NULL "
                    "UNION SELECT session_id FROM sessions"
                )
            }
        roots.update(item["id"] for item in self.history())
        current, visited = session_id, set()
        while current and current not in visited and len(visited) < 50:
            if current in roots:
                return True
            visited.add(current)
            info = await client.get_session(current)
            if not info.get("parentID") and (info.get("metadata") or {}).get("qq_bridge_context"):
                return True
            current = info.get("parentID")
        return False

    def session_index(self):
        entries, mappings = {}, {}
        with readonly(self.config.state_db) as db:
            for row in db.execute(
                "SELECT session_id,conversation,MIN(created) AS created,MAX(created) AS updated,"
                "COUNT(*) AS tasks,MAX(memory_isolated) AS isolated,MIN(target) AS target "
                "FROM jobs WHERE session_id IS NOT NULL AND steer_parent_id IS NULL "
                "GROUP BY session_id,conversation"
            ):
                item = dict(row)
                item["id"] = item.pop("session_id")
                item["target"] = json.loads(item["target"])
                entries[item["id"]] = item
            for row in db.execute(
                "SELECT context AS conversation,session_id FROM sessions "
                "WHERE context LIKE '%:private:%' UNION ALL "
                "SELECT conversation,session_id FROM group_sessions"
            ):
                mappings[row["conversation"]] = row["session_id"]
            conversations = {row[0] for row in db.execute("SELECT DISTINCT conversation FROM jobs")}
            for conversation in conversations:
                mappings.setdefault(conversation, None)
            for item in self.history():
                entries.setdefault(item["id"], item | {"tasks": 0, "updated": 0, "created": 0})
            result = []
            for conversation, session_id in mappings.items():
                parts = conversation.split(":")
                if len(parts) != 3 or parts[1] not in {"private", "group"}:
                    continue
                target = {"self_id": int(parts[0]), "user_id": int(parts[2]), "group_id": None}
                if parts[1] == "group":
                    target.update(
                        group_id=int(parts[2]), user_id=self.config.superadmin_user_id or 1
                    )
                result.append(
                    {
                        "conversation": conversation,
                        "session_id": session_id,
                        "target": target,
                        "title": ("群聊 " if target["group_id"] else "私聊 ") + parts[2],
                    }
                )
                if session_id:
                    entries.setdefault(
                        session_id,
                        {
                            "id": session_id,
                            "conversation": conversation,
                            "target": target,
                            "tasks": 0,
                            "updated": 0,
                            "created": 0,
                        },
                    )
        return entries, result

    async def sessions(self, *, fresh=False):
        cached = self.cache.get("session-index")
        if not fresh and cached and time.monotonic() - cached[0] < 10:
            return cached[1]
        entries, mappings = await asyncio.to_thread(self.session_index)
        warning, complete = None, True
        try:
            async with self.remote_limit, asyncio.timeout(25):
                client = self.client()
                for archived in ("false", "true"):
                    cursor, visited = None, set()
                    for _ in range(100):
                        params = {
                            "limit": "100",
                            "parentID": "null",
                            "archived": archived,
                        }
                        if cursor:
                            params["cursor"] = cursor
                        page = await client.request(
                            "GET", "/api/session", params=params, unwrap=False
                        )
                        for info in page["data"]:
                            if info.get("parentID"):
                                continue
                            conversation = (info.get("metadata") or {}).get("qq_bridge_context")
                            local = entries.get(info["id"])
                            if not local and not conversation:
                                continue
                            item = local or {
                                "id": info["id"],
                                "conversation": conversation,
                                "tasks": 0,
                            }
                            stamp = info.get("time") or {}
                            item.update(
                                title=info.get("title", info["id"]),
                                archived=archived == "true",
                                updated=stamp.get("updated", item.get("updated", 0) * 1000) / 1000,
                                created=stamp.get("created", item.get("created", 0) * 1000) / 1000,
                            )
                            entries[info["id"]] = item
                        cursor = page.get("cursor", {}).get("next")
                        if not cursor:
                            break
                        if cursor in visited:
                            raise ProtocolError("OpenCode 会话分页未前进")
                        visited.add(cursor)
                    else:
                        complete = False
                        warning = "会话索引超过单次读取上限，当前显示已加载记录。"
        except (OSError, ApiError, ProtocolError, TimeoutError, ValueError, ClientError):
            complete = False
            warning = "OpenCode 会话索引暂不可用，先显示桥接保留的全部本地会话。"
        current = {mapping["conversation"]: mapping["session_id"] for mapping in mappings}
        for item in entries.values():
            item["current"] = current.get(item["conversation"]) == item["id"]
            item["isolated"] = bool(item.get("isolated"))
            item["title"] = item.get("title") or item["id"]
            item["eligible"] = not item["isolated"] and (
                ":private:" in item["conversation"] or item["current"] or item.get("tasks", 0) > 0
            )
        # Include bridge-labelled roots even if no surviving job references them.
        known = {mapping["conversation"] for mapping in mappings}
        for item in entries.values():
            conversation = item["conversation"]
            if conversation in known:
                continue
            parts = conversation.split(":")
            if len(parts) != 3 or parts[1] not in {"private", "group"}:
                continue
            mappings.append(
                {
                    "conversation": conversation,
                    "session_id": None,
                    "title": ("群聊 " if parts[1] == "group" else "私聊 ") + parts[2],
                    "target": {
                        "self_id": int(parts[0]),
                        "user_id": int(parts[2])
                        if parts[1] == "private"
                        else self.config.superadmin_user_id or 1,
                        "group_id": int(parts[2]) if parts[1] == "group" else None,
                    },
                }
            )
            known.add(conversation)
        result = self.clean(
            {
                "items": sorted(
                    entries.values(), key=lambda item: item.get("updated", 0), reverse=True
                ),
                "mappings": mappings,
                "complete": complete,
                "warning": warning,
            }
        )
        self.cache["session-index"] = (time.monotonic(), result)
        return result

    async def session_messages(self, session_id, cursor=None):
        async with self.remote_limit, asyncio.timeout(25):
            client = self.client()
            if not await self.allowed_session(client, session_id):
                raise KeyError(session_id)
            params = {"limit": "50", **({"cursor": cursor} if cursor else {"order": "desc"})}
            info, page, children = await asyncio.gather(
                client.get_session(session_id),
                client.request(
                    "GET",
                    f"/api/session/{path_id(session_id)}/message",
                    params=params,
                    unwrap=False,
                ),
                self.children(client, session_id),
            )
            return self.clean(
                {
                    "id": session_id,
                    "title": info.get("title", session_id),
                    "messages": [self.message(m) for m in reversed(page["data"])],
                    "next": page.get("cursor", {}).get("next"),
                    "children": [
                        {key: child.get(key) for key in ("id", "title", "parentID")}
                        for child in children
                        if child.get("parentID") == session_id
                    ],
                    "metrics": metrics(page["data"]),
                    "metrics_scope": "当前加载页",
                }
            )

    @staticmethod
    async def children(client, session_id):
        result, cursor, visited = [], None, set()
        for _ in range(100):
            params = {"parentID": session_id, "limit": "100"}
            if cursor:
                params["cursor"] = cursor
            page = await client.request("GET", "/api/session", params=params, unwrap=False)
            result.extend(page["data"])
            cursor = page.get("cursor", {}).get("next")
            if not cursor:
                return result
            if cursor in visited:
                raise ProtocolError("OpenCode 子会话分页未前进")
            visited.add(cursor)
        raise ProtocolError("OpenCode 子会话数量超过读取上限")

    def memory_owner(self):
        return f"qq:{self.onebot.self_id}:{self.config.memory_owner_user_id}"

    def memories(self, *, query="", kind="", subject="", offset=0, limit=40):
        if not self.config.memory_enabled or not self.config.memory_db.is_file():
            return {"items": [], "total": 0, "enabled": False}
        clauses = ["owner=?", "state IN ('active','pending')", "instr(lower(content),lower(?))>0"]
        args = [self.memory_owner(), query]
        for field, value in (("kind", kind), ("subject", subject)):
            if value:
                clauses.append(field + "=?")
                args.append(value)
        with readonly(self.config.memory_db) as db:
            where = " AND ".join(clauses)
            total = db.execute("SELECT COUNT(*) FROM entries WHERE " + where, args).fetchone()[0]
            rows = db.execute(
                "SELECT id,content,kind,scope,subject,fact_key,pinned,expires,state,created,"
                "sources,evidence "
                "FROM entries WHERE " + where + " ORDER BY created DESC,id LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                item["expired"] = bool(item["expires"] and item["expires"] < time.time())
                item["sources"] = json.loads(item["sources"])
                item["evidence"] = json.loads(item["evidence"])
                item["source_excerpts"] = []
                for source_id in item["sources"][:8]:
                    source = db.execute(
                        "SELECT id,scope,group_id,user_text,assistant_text,created FROM archive "
                        "WHERE id=? AND owner=? AND suppressed=0",
                        (source_id, self.memory_owner()),
                    ).fetchone()
                    if source:
                        item["source_excerpts"].append(dict(source))
                items.append(item)
        return self.clean({"items": items, "total": total, "enabled": True})
