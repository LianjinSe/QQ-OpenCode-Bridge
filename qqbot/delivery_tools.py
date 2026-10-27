"""Native attachment submission, bound to an active QQ task and durable snapshots."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import time

import jsonschema
from aiohttp import web

from .delivery import DeliveryError, directory, snapshot_files
from .tool_identity import resolve_task

log = logging.getLogger(__name__)
SCHEMA = {
    "type": "object",
    "properties": {
        "files": {
            "type": "array",
            "minItems": 1,
            "maxItems": 50,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1, "maxLength": 4096},
                    "name": {"type": "string", "minLength": 1, "maxLength": 200},
                    "kind": {"enum": ["auto", "image", "video", "audio", "file"]},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["files"],
    "additionalProperties": False,
}


class DeliveryTools:
    def __init__(self, config, store, onebot, identity):
        self.config, self.store, self.onebot, self.identity_context = (
            config,
            store,
            onebot,
            identity,
        )
        self.root = self.config.state_db.parent / "delivery-tools"
        self.socket, self.token_path = self.root / "tools.sock", self.root / "tools.token"
        self.token = ""
        self.runner = None
        self.db = None
        self.lock = asyncio.Lock()

    async def start(self):
        if self.runner is not None:
            return
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.resolve() != self.root:
            raise RuntimeError("附件工具目录不能是符号链接")
        self.root.chmod(0o700)
        path = self.root / "requests.sqlite3"
        if path.is_symlink() or self.token_path.is_symlink():
            raise RuntimeError("附件工具文件不能是符号链接")
        self.db = sqlite3.connect(path)
        path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS requests (
                key TEXT PRIMARY KEY, job_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                artifacts TEXT NOT NULL, receipt TEXT NOT NULL, created REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS requests_job ON requests(job_id,created);
        """)
        self.token = secrets.token_urlsafe(32)
        fd = os.open(self.token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(self.token)
        app = web.Application(client_max_size=65536)
        app.add_routes([web.post("/call", self.handle), web.post("/context", self.handle)])
        self.runner = web.AppRunner(app, access_log=None, shutdown_timeout=3)
        await self.runner.setup()
        self.socket.unlink(missing_ok=True)
        await web.UnixSite(self.runner, str(self.socket)).start()
        self.socket.chmod(0o600)
        log.info("统一附件发送工具已就绪")

    async def run(self):
        try:
            await self.start()
            await asyncio.Future()
        finally:
            await self.close()

    async def close(self):
        if self.runner:
            await self.runner.cleanup()
            self.runner = None
            self.socket.unlink(missing_ok=True)
        if self.db:
            self.db.close()
            self.db = None

    def artifacts(self, job_id):
        if self.db is None:
            return []
        return [
            artifact
            for row in self.db.execute(
                "SELECT artifacts FROM requests WHERE job_id=? ORDER BY created,rowid", (job_id,)
            )
            for artifact in json.loads(row["artifacts"])
        ]

    async def context(self, session_id):
        job, context = await resolve_task(self.identity_context, session_id)
        if context.self_id != self.onebot.self_id:
            raise PermissionError
        input_dir = self.config.workdir.resolve() / ".qq-attachments" / job["id"]
        steer_dirs = [
            str(input_dir.parent / item["id"])
            for item in self.store.steers(job["id"])
            if item["admitted"]
            and item["status"] == "steered"
            and not item["cancel_requested"]
            and item["target"] == job["target"]
        ]
        return {
            "available": True,
            "output_dir": str(directory(self.config, job["id"])),
            "input_dir": str(input_dir),
            "steer_input_dirs": steer_dirs,
            "max_files": self.config.max_attachments,
            "max_bytes": self.config.max_attachment_bytes,
            "immediate": self.config.delivery_immediate,
            "image_generation_enabled": self.config.image_generation_enabled,
            "image_timeout": min(self.config.image_timeout, self.config.execution_timeout),
        }

    async def submit(self, session_id, call_id, arguments):
        jsonschema.validate(arguments, SCHEMA)
        if not isinstance(call_id, str) or not 1 <= len(call_id) <= 200:
            raise ValueError("工具调用编号无效")
        job, context = await resolve_task(self.identity_context, session_id)
        if context.self_id != self.onebot.self_id:
            raise PermissionError("当前 QQ 与任务不匹配")
        key = hashlib.sha256(json.dumps([job["id"], session_id, call_id]).encode()).hexdigest()
        fingerprint = hashlib.sha256(
            json.dumps(arguments, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        async with self.lock:
            current, current_context = await resolve_task(self.identity_context, session_id)
            if current["id"] != job["id"] or current_context != context:
                raise PermissionError("任务归属已变化")
            if self.db is None:
                raise DeliveryError("附件工具尚未就绪")
            previous = self.db.execute("SELECT * FROM requests WHERE key=?", (key,)).fetchone()
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise DeliveryError("同一工具调用编号不能更换附件参数")
                return {**json.loads(previous["receipt"]), "replayed": True}
            existing = tuple(self.artifacts(job["id"]))
            steers = tuple(
                item["id"]
                for item in self.store.steers(job["id"])
                if item["admitted"]
                and item["status"] == "steered"
                and not item["cancel_requested"]
                and item["target"] == job["target"]
            )
            artifacts = await asyncio.to_thread(
                snapshot_files,
                arguments["files"],
                self.config,
                job["id"],
                request_id=key,
                input_job_ids=steers,
                existing=existing,
            )
            current, current_context = await resolve_task(self.identity_context, session_id)
            if (
                current["id"] != job["id"]
                or current_context != context
                or context.self_id != self.onebot.self_id
            ):
                raise PermissionError("任务归属已变化")
            receipt = {
                "ok": True,
                "status": "queued",
                "request_id": key,
                "files": [{k: a[k] for k in ("name", "kind", "size")} for a in artifacts],
                "total_files": len(existing) + len(artifacts),
                "deduplicated": not artifacts,
                "message": "文件快照已保存，尚未发送。任务成功结束后先交付附件再发送正文；"
                "取消或执行失败不发送。不要提前声称已发送，不要重复调用或输出内部清单。",
            }
            if getattr(self.config, "delivery_immediate", False) and artifacts:
                # 即时模式：立刻入队发送，正文仍等任务结束。
                for artifact in artifacts:
                    artifact["immediate"] = True
                self.store.enqueue_media(job["id"], context, artifacts, request_id=key)
                receipt["message"] = (
                    "文件已进入发送队列，正在发往聊天。任务结束时再发送正文；"
                    "不要声称已经送达，不要重复调用或输出内部清单。"
                )
            with self.db:
                self.db.execute(
                    "INSERT INTO requests VALUES (?,?,?,?,?,?)",
                    (
                        key,
                        job["id"],
                        fingerprint,
                        json.dumps(artifacts),
                        json.dumps(receipt, ensure_ascii=False),
                        time.time(),
                    ),
                )
            return receipt

    async def handle(self, request):
        if not self.token or not hmac.compare_digest(
            request.headers.get("Authorization", "").encode(), ("Bearer " + self.token).encode()
        ):
            return web.json_response({"ok": False}, status=401)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError
            if request.path == "/context":
                return web.json_response(await self.context(body.get("session_id")))
            if body.get("name") != "send_files":
                raise ValueError
            result = await self.submit(
                body.get("session_id"), body.get("call_id"), body.get("arguments")
            )
            return web.json_response(result)
        except PermissionError:
            return web.json_response(
                {"ok": False, "status": "denied", "message": "当前任务不可提交附件。"}, status=403
            )
        except (DeliveryError, OSError) as exc:
            log.warning("附件工具未能准备文件，类型=%s", type(exc).__name__)
            return web.json_response(
                {
                    "ok": False,
                    "status": "failed",
                    "message": "附件未能准备，未加入交付队列。请核对本轮文件、类型和大小。",
                },
                status=400,
            )
        except (ValueError, TypeError, jsonschema.ValidationError):
            return web.json_response({"ok": False, "status": "invalid_arguments"}, status=400)
        except Exception:
            log.warning("附件工具未取得排队确认")
            return web.json_response(
                {
                    "ok": False,
                    "status": "unconfirmed",
                    "message": "未取得排队确认；只能用原调用编号和相同参数查询，不能声称已发送。",
                },
                status=503,
            )
