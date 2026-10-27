"""Authenticated local tools over the bridge's existing Mem0 and policy ledger."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import stat
from datetime import datetime

import jsonschema
from aiohttp import web

from .memory_policy import requests_recall
from .memory_service import MemoryAccessDenied, public_entry
from .tool_identity import TaskIdentityContext, resolve_task

log = logging.getLogger(__name__)


def object_schema(properties, required):
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


TEXT = {"type": "string", "minLength": 1, "maxLength": 2000}
IDENTIFIER = {"type": "string", "minLength": 1, "maxLength": 200}
REFERENCES = {"type": "array", "items": IDENTIFIER, "maxItems": 6, "uniqueItems": True}
SCHEMAS = {
    "search": object_schema({"query": TEXT}, ["query"]),
    "history": object_schema({"query": TEXT}, ["query"]),
    "evidence": object_schema({"query": TEXT, "source_ids": REFERENCES}, ["query"]),
    "remember": object_schema(
        {"content": TEXT, "evidence": TEXT, "evidence_ids": REFERENCES}, ["content", "evidence"]
    ),
    "update": object_schema(
        {"id": IDENTIFIER, "content": TEXT, "evidence": TEXT, "evidence_ids": REFERENCES},
        ["id", "content", "evidence"],
    ),
    "forget": object_schema({"id": IDENTIFIER, "evidence": TEXT}, ["id", "evidence"]),
    "diary": object_schema({"day": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}}, ["day"]),
}


class MemoryTools:
    def __init__(self, memory):
        self.memory = memory
        self.bridge_store = memory.bridge_store
        self.identity = TaskIdentityContext(memory.config, self.bridge_store, memory.opencode)
        self.store = memory.store
        self.evidence = memory.evidence
        self.writer = memory.write_service
        self.socket = memory.config.memory_db.with_name("memory-tools.sock")
        self.token_path = memory.config.memory_db.with_name("memory-tools.token")
        self.token = ""
        self.runner = None

    async def start(self):
        if self.runner is not None:
            return
        self.socket.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.token_path.exists():
            fd = os.open(self.token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(secrets.token_urlsafe(48))
        if self.token_path.is_symlink():
            raise RuntimeError("记忆工具认证文件不能是符号链接")
        os.chmod(self.token_path, 0o600)
        self.token = self.token_path.read_text().strip()
        if len(self.token) < 32:
            raise RuntimeError("记忆工具认证信息无效")
        if self.socket.exists():
            if not stat.S_ISSOCK(self.socket.lstat().st_mode):
                raise RuntimeError("记忆工具地址已被其他文件占用")
            self.socket.unlink()
        app = web.Application(client_max_size=16384)
        app.router.add_post("/context", self.handle)
        app.router.add_post("/call", self.handle)
        self.runner = web.AppRunner(app, access_log=None, shutdown_timeout=3)
        await self.runner.setup()
        await web.UnixSite(self.runner, str(self.socket)).start()
        os.chmod(self.socket, 0o600)
        log.info("本地记忆工具服务已就绪")

    async def run(self):
        await self.start()
        try:
            await asyncio.Event().wait()
        finally:
            await self.close()

    async def close(self):
        if self.runner is not None:
            runner, self.runner = self.runner, None
            await runner.cleanup()
            self.socket.unlink(missing_ok=True)

    async def job_for(self, session_id):
        try:
            if self.memory.identity_resolver is None:
                job, context = await resolve_task(self.identity, session_id)
            else:
                job, context = await self.memory.identity_resolver(session_id)
        except PermissionError:
            raise MemoryAccessDenied() from None
        if not self.memory.owns(context):
            raise MemoryAccessDenied()
        if context.group_id is not None and not job["memory_isolated"]:
            raise MemoryAccessDenied()
        return job, context

    def private_allowed(self, job, context):
        return context.group_id is None or requests_recall(job["memory_source_text"] or job["text"])

    async def handle(self, request):
        authorization = request.headers.get("Authorization", "")
        if not self.token or not hmac.compare_digest(authorization, "Bearer " + self.token):
            return web.json_response({"ok": False, "status": "unauthorized"}, status=401)
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError()
            job, context = await self.job_for(data.get("session_id"))
            if request.path == "/context":
                result = {"ok": True, "available": True}
            else:
                result = await self.dispatch(job, context, data)
                current, current_context = await self.job_for(data.get("session_id"))
                if current["id"] != job["id"] or current_context != context:
                    raise MemoryAccessDenied()
            return web.json_response(result, headers={"Cache-Control": "no-store"})
        except MemoryAccessDenied:
            return web.json_response(
                {"ok": False, "available": False, "status": "unavailable"}, status=403
            )
        except (ValueError, TypeError, jsonschema.ValidationError):
            return web.json_response({"ok": False, "status": "invalid_arguments"}, status=400)
        except Exception as exc:
            log.warning("记忆工具暂不可用，类型=%s", type(exc).__name__)
            return web.json_response(
                {"ok": False, "status": "unavailable", "message": "这次未能完成，不要确认成功。"},
                status=503,
            )

    def public_entry(self, row):
        return public_entry(self.store, row)

    async def dispatch(self, job, context, data):
        name, arguments = data.get("name"), data.get("arguments")
        if name not in SCHEMAS:
            raise ValueError()
        jsonschema.validate(arguments, SCHEMAS[name])
        owner = self.memory.owner(context)
        private = self.private_allowed(job, context)
        if name in {"search", "history", "diary", "evidence"}:
            if self.memory.pending(owner):
                return {
                    "ok": False,
                    "status": "pending",
                    "message": "记忆正在更新，暂不返回旧内容。",
                }
            if name == "search":
                async with asyncio.timeout(self.memory.config.memory_search_timeout):
                    rows = await self.memory.recall(owner, arguments["query"], private=private)
                return {"ok": True, "memories": [self.public_entry(row) for row in rows]}
            if name == "evidence":
                return await self.evidence.find(job, context, arguments, private)
            if name == "history":
                rows = self.store.history_search(owner, private, arguments["query"])
                return {
                    "ok": True,
                    "conversations": [
                        {
                            "source_id": row["id"],
                            "time": row["created"],
                            "user": self.redact(row["user_text"][:1000]),
                            "assistant": self.redact(row["assistant_text"][:500]),
                        }
                        for row in rows
                    ],
                }
            day = arguments["day"]
            datetime.strptime(day, "%Y-%m-%d")
            rows = [
                row
                for row in self.store.entries(owner, private=private, kinds=["diary"], limit=100000)
                if row["fact_key"].startswith("diary:" + day + ":")
            ]
            if rows:
                return {
                    "ok": True,
                    "day": day,
                    "diary": [self.public_entry(row) for row in rows[:3]],
                }
            # Group requests cannot cause summaries of private archives to be returned.
            return {"ok": True, "day": day, "diary": [], "message": "尚无可用日记。"}

        call_id = data.get("call_id")
        jsonschema.validate(call_id, IDENTIFIER)
        source = self.store.source(job["id"])
        if not source or source["owner"] != owner:
            raise MemoryAccessDenied()
        evidence_ids = arguments.get("evidence_ids", [])
        proofs = self.evidence.resolve(evidence_ids, job["id"], owner, private)
        if proofs is None:
            return {
                "ok": False,
                "status": "invalid_evidence",
                "message": "来源已失效或超出本次可见范围。",
            }
        if arguments["evidence"] not in source["user_text"]:
            steer_source = next(
                (
                    candidate
                    for item in reversed(self.bridge_store.steers(job["id"]))
                    if context.group_id is None
                    and item["context"] == context.key
                    and item["status"] == "steered"
                    and (candidate := self.store.source(item["id"]))
                    and candidate["owner"] == owner
                    and arguments["evidence"] in candidate["user_text"]
                ),
                None,
            )
            if steer_source is not None:
                source = steer_source
            elif not any(arguments["evidence"] in proof["text"] for proof in proofs):
                return {
                    "ok": False,
                    "status": "no_evidence",
                    "message": (
                        "请引用当前用户原话，或先用 memory_evidence 获取历史/工具证据，"
                        "再传 evidence_ids。"
                    ),
                }
        from .content_safety import SECRET

        if SECRET.search(arguments.get("content", "")) or SECRET.search(arguments["evidence"]):
            return {"ok": False, "status": "sensitive", "message": "不保存密码或密钥。"}
        key = (
            "memory-tool:"
            + hashlib.sha256(
                json.dumps([job["id"], data["session_id"], call_id]).encode()
            ).hexdigest()
        )
        signature = hashlib.sha256(
            json.dumps([name, arguments], sort_keys=True).encode()
        ).hexdigest()
        row = self.store.work_by_dedupe(key)
        if row and json.loads(row["payload"]).get("signature") != signature:
            raise ValueError()
        if row is None:
            self.store.enqueue(
                owner,
                "control",
                {
                    "tool": name,
                    "arguments": arguments,
                    "context": context.to_dict(),
                    "private": private,
                    "source": source["id"],
                    "root_job": job["id"],
                    "evidence_ids": evidence_ids,
                    "key": key,
                    "signature": signature,
                },
                key,
            )
            row = self.store.work_by_dedupe(key)
        async with asyncio.timeout(2 * self.memory.config.memory_timeout + 15):
            while True:
                current = self.store.work_item(row["id"])
                if current is None:
                    raise MemoryAccessDenied()
                if current["state"] == "done":
                    return json.loads(current["result"] or '{"ok":false,"status":"unconfirmed"}')
                if current["state"] == "failed":
                    return {
                        "ok": False,
                        "status": "failed",
                        "message": "未完成，可用 /memory retry 重试。",
                    }
                await asyncio.sleep(0.1)

    async def process(self, work):
        return await self.writer.process(work)

    @staticmethod
    def redact(text):
        from .content_safety import redact_evidence

        return redact_evidence(text)
