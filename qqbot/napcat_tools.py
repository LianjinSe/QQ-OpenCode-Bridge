"""Task-bound administrator access to NapCat's installed OneBot action catalogue."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import time
import uuid
from pathlib import Path

import jsonschema
from aiohttp import web

from . import delivery
from .content_safety import SECRET
from .onebot import ActionError, DeliveryUnknown, Unavailable
from .policy import is_superadmin
from .tool_identity import resolve_task

log = logging.getLogger(__name__)
DOWNLOADS = {
    "download_file_stream",
    "download_file_image_stream",
    "download_file_record_stream",
    "test_download_stream",
}
CREDENTIAL = re.compile(
    r"(?i)cookie|token|skey|rkey|clientkey|credential|ticket|password|secret|authorization|bkn|api.?key"
)
SYSTEM_READ = {
    "get_version_info",
    "get_status",
    "get_login_info",
    "can_send_image",
    "can_send_record",
}


def compact_schema(value, *, root=False):
    if isinstance(value, dict):
        if "$id" in value and not root:
            return {"$ref": "#/$defs/" + value["$id"]}
        return {k: compact_schema(v) for k, v in value.items() if k != "$id"}
    if isinstance(value, list):
        return [compact_schema(v) for v in value]
    return value


def prepare_params(schema, value):
    """Match NapCat TypeBox's documented numeric-ID coercion and defaults."""
    if (
        schema.get("type") == "string"
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    ):
        return str(value)
    if isinstance(value, dict) and schema.get("type") == "object":
        properties = schema.get("properties", {})
        result = {key: prepare_params(properties.get(key, {}), v) for key, v in value.items()}
        for key, field in properties.items():
            if key not in result and "default" in field:
                result[key] = field["default"]
        return result
    if isinstance(value, list) and "items" in schema:
        return [prepare_params(schema["items"], v) for v in value]
    return value


def json_schema(value):
    """TypeBox Undefined means an omitted JSON property, never a JSON value."""
    if isinstance(value, dict):
        if value.get("type") == "undefined":
            return {"not": {}}
        return {k: json_schema(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_schema(v) for v in value]
    return value


class NapCatTools:
    def __init__(self, config, onebot, store, identity):
        self.config, self.onebot, self.store, self.identity_context = (
            config,
            onebot,
            store,
            identity,
        )
        self.enabled = self.config.napcat_tools_enabled
        self.root = self.config.state_db.parent / "napcat-tools"
        self.socket, self.token_path = self.root / "tools.sock", self.root / "tools.token"
        self.token = ""
        self.runner = None
        self.db = None
        self.lock = asyncio.Lock()
        self.checked_socket = None
        self.vault, self.results = {}, {}
        self.catalogue = (
            json.loads(Path(__file__).with_name("napcat_catalogue.json").read_text())
            if self.enabled
            else {"version": "", "actions": {}, "definitions": {}}
        )
        if self.enabled:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.root.chmod(0o700)
            (self.root / "artifacts").mkdir(exist_ok=True, mode=0o700)
            try:
                self.db = sqlite3.connect(self.root / "calls.sqlite3")
                (self.root / "calls.sqlite3").chmod(0o600)
                self.db.row_factory = sqlite3.Row
                self.db.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=FULL;
                CREATE TABLE IF NOT EXISTS calls (
                    key TEXT PRIMARY KEY, job_id TEXT NOT NULL, action TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, state TEXT NOT NULL, result TEXT,
                    created REAL NOT NULL, updated REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS call_fingerprint
                    ON calls(job_id,action,fingerprint,state);
                CREATE TABLE IF NOT EXISTS artifacts (
                    ref TEXT PRIMARY KEY, job_id TEXT NOT NULL, path TEXT NOT NULL,
                    name TEXT NOT NULL, bytes INTEGER NOT NULL, created REAL NOT NULL
                );
                UPDATE calls SET state='uncertain' WHERE state='pending';
                """)
                self.db.commit()
            except BaseException:
                self.close_storage()
                raise

    async def identity(self, session_id):
        job, context = await resolve_task(self.identity_context, session_id)
        if context.self_id != self.onebot.self_id:
            raise PermissionError("当前登录 QQ 与任务不匹配")
        return job, context

    async def start(self):
        try:
            self.token = secrets.token_urlsafe(32)
            fd = os.open(self.token_path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(self.token)
            app = web.Application(client_max_size=256 * 1024)
            app.add_routes([web.post("/call", self.handle), web.post("/context", self.handle)])
            self.runner = web.AppRunner(app, access_log=None)
            await self.runner.setup()
            self.socket.unlink(missing_ok=True)
            await web.UnixSite(self.runner, str(self.socket)).start()
            self.socket.chmod(0o600)
        except BaseException:
            await self.close_socket()
            self.token_path.unlink(missing_ok=True)
            self.close_storage()
            raise

    async def run(self):
        if not self.enabled:
            return
        try:
            await self.start()
            log.info("NapCat 原生能力工具已启用；接口目录版本=%s", self.catalogue["version"])
            while True:
                await asyncio.sleep(60)
                self.cleanup()
        finally:
            await self.close_socket()

    async def close_socket(self):
        if self.runner:
            await self.runner.cleanup()
            self.runner = None
            self.socket.unlink(missing_ok=True)

    async def close(self):
        await self.close_socket()
        self.token_path.unlink(missing_ok=True)
        self.close_storage()
        self.vault.clear()
        self.results.clear()

    def close_storage(self):
        """Synchronously release SQLite during partial Bridge construction cleanup."""
        if self.db:
            self.db.close()
            self.db = None

    def cleanup(self):
        now = time.time()
        for cache in (self.vault, self.results):
            for key in list(cache):
                if cache[key]["expires"] < now:
                    del cache[key]
        # Raw downloads are task staging, not permanent tool-history archives.
        for row in self.db.execute(
            "SELECT * FROM artifacts WHERE created<?", (now - 86400,)
        ).fetchall():
            job = self.store.job(row["job_id"])
            if job and job["status"] in {"submitting", "running", "waiting"}:
                continue
            path = Path(row["path"])
            if path.parent == self.root / "artifacts":
                path.unlink(missing_ok=True)
            self.db.execute("DELETE FROM artifacts WHERE ref=?", (row["ref"],))
        self.db.execute("DELETE FROM calls WHERE updated<? AND state!='pending'", (now - 604800,))
        self.db.commit()

    def lookup(self, action):
        if not isinstance(action, str) or action not in self.catalogue["actions"]:
            raise ValueError("接口不在已核实目录中，请先用 napcat_list 查找")
        return self.catalogue["actions"][action]

    def check_scope(self, action, params, context):
        if not is_superadmin(self.config, context):
            raise PermissionError("实际调用仅允许真实超级管理员任务")
        if context.group_id is None:
            return
        if action in SYSTEM_READ:
            return
        info = self.lookup(action)
        group_action = any("群" in tag for tag in info.get("tags", [])) or action in {
            "send_poke",
            "group_poke",
            "send_group_msg",
            "send_group_forward_msg",
            "send_group_sign",
        }
        if (
            not group_action
            or "group_id" not in info.get("payload", {}).get("properties", {})
            or str(params.get("group_id", "")) != str(context.group_id)
        ):
            raise PermissionError("群内只操作当前群；账号、私聊和跨群能力请由主人私聊调用")

    async def version(self):
        socket = getattr(self.onebot, "ws", None)
        if socket is not None and socket is self.checked_socket:
            return
        info = await self.onebot.call("get_version_info", {})
        if str(info.get("app_version", "")).lstrip("v") != self.catalogue["version"]:
            raise ValueError("NapCat 版本与接口目录不同，请先同步文档和参数 schema")
        self.checked_socket = socket

    def box(self, job_id, value, *, kind="credential", command=None):
        ref = "secret_" + uuid.uuid4().hex
        if len(self.vault) >= 64:
            del self.vault[next(iter(self.vault))]
        self.vault[ref] = {
            "job_id": job_id,
            "value": value,
            "expires": time.time() + 600,
            "kind": kind,
            "command": command,
        }
        return {"$napcat_secret": ref}

    def resolve(self, job_id, value, *, action, field=(), command=None):
        if isinstance(value, dict):
            if "$napcat_secret" in value:
                item = self.vault.get(value["$napcat_secret"])
                if (
                    set(value) != {"$napcat_secret"}
                    or not item
                    or item["job_id"] != job_id
                    or item["expires"] < time.time()
                ):
                    raise PermissionError("凭据引用已过期或不属于当前任务")
                allowed_url = (
                    item["kind"] == "download_url"
                    and action
                    in DOWNLOADS | {"download_file", "get_image", "get_record", "get_file"}
                    and field in {("file",), ("url",)}
                )
                allowed_packet = (
                    item["kind"] == "packet"
                    and action == "send_packet"
                    and field == ("data",)
                    and command is not None
                    and command == item["command"]
                )
                if not (allowed_url or allowed_packet):
                    raise PermissionError("敏感引用只能用于匹配的下载或原始包参数，不能发送到聊天")
                return item["value"]
            return {
                k: self.resolve(job_id, v, action=action, field=(*field, k), command=command)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [
                self.resolve(job_id, v, action=action, field=(*field, i), command=command)
                for i, v in enumerate(value)
            ]
        return value

    def scrub(self, job_id, value):
        if isinstance(value, dict):
            return {
                k: self.box(job_id, v) if CREDENTIAL.search(k) else self.scrub(job_id, v)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [self.scrub(job_id, v) for v in value]
        if isinstance(value, str):
            if re.search(r"(?i)[?&](?:rkey|skey|clientkey|token|ticket)=", value):
                return self.box(job_id, value, kind="download_url")
            for secret in (
                self.config.napcat_token,
                self.config.memory_api_key,
                self.config.opencode_password,
            ):
                if secret:
                    value = value.replace(secret, "[敏感凭据已省略]")
            for item in self.vault.values():
                secret = item["value"]
                if isinstance(secret, str) and len(secret) >= 8:
                    value = value.replace(secret, "[敏感凭据已省略]")
            return SECRET.sub("[敏感凭据已省略]", value)
        return value

    def pack(self, job_id, action, value, *, command=None):
        if action == "send_packet" or (
            CREDENTIAL.search(action) and not isinstance(value, (dict, list))
        ):
            value = self.box(
                job_id,
                value,
                kind="packet" if action == "send_packet" else "credential",
                command=command,
            )
        else:
            value = self.scrub(job_id, value)
        text = json.dumps(value, ensure_ascii=False)
        if len(text) <= 16000:
            return {"data": value}
        ref = "result_" + uuid.uuid4().hex
        if len(self.results) >= 8:
            del self.results[next(iter(self.results))]
        self.results[ref] = {"job_id": job_id, "value": text, "expires": time.time() + 600}
        return {"result_ref": ref, "characters": len(text), "preview": text[:4000]}

    def finish(self, key, result):
        # Keep a minimal outcome receipt, never the full friend/message/tool transcript.
        receipt = {k: v for k, v in result.items() if k != "data" and k != "preview"}
        if isinstance(result.get("data"), dict):
            receipt["data"] = {
                k: v
                for k, v in result["data"].items()
                if k
                in {
                    "message_id",
                    "file_ref",
                    "name",
                    "bytes",
                    "napcat_path",
                    "path",
                    "sha256",
                }
            }
        self.db.execute(
            "UPDATE calls SET state=?,result=?,updated=? WHERE key=?",
            (result["status"], json.dumps(receipt, ensure_ascii=False), time.time(), key),
        )
        self.db.commit()

    async def execute(self, body, job, context):
        name, args = body["name"], body["arguments"]
        action = (
            args.get("action")
            if name == "call"
            else "upload_file_stream"
            if name == "upload"
            else "export"
        )
        info = self.lookup(action) if name == "call" else None
        if info and not info["available"]:
            raise ValueError("此接口仅在新版文档中出现，本机尚未注册；未发送请求")
        params = (
            self.resolve(
                job["id"],
                args.get("params", {}),
                action=action,
                command=args.get("params", {}).get("cmd"),
            )
            if name == "call"
            else args
        )
        if name == "call":
            schema = json_schema(info.get("payload") or {"type": "object"})
            params = prepare_params(schema, params)
            if next(jsonschema.Draft7Validator(schema).iter_errors(params), None):
                raise ValueError("参数不符合本机 schema，请先用 napcat_describe 核对")
            self.check_scope(action, params, context)
        elif not is_superadmin(self.config, context):
            raise PermissionError("实际调用仅允许真实超级管理员任务")
        call_id = body.get("call_id")
        if not isinstance(call_id, str) or not 1 <= len(call_id) <= 200:
            raise ValueError("工具调用 ID 无效")
        key = hashlib.sha256(
            json.dumps([job["id"], body["session_id"], call_id]).encode()
        ).hexdigest()
        fingerprint = hashlib.sha256(
            json.dumps([name, params], sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        async with self.lock:
            previous = self.db.execute("SELECT * FROM calls WHERE key=?", (key,)).fetchone()
            if previous:
                if previous["fingerprint"] != fingerprint or previous["action"] != action:
                    raise ValueError("同一工具调用 ID 不能更换操作或参数")
                if previous["state"] != "not_sent":
                    return {
                        **(
                            json.loads(previous["result"])
                            if previous["result"]
                            else {
                                "ok": False,
                                "status": "uncertain",
                                "action": action,
                            }
                        ),
                        "replayed": True,
                        "receipt_only": True,
                    }
            uncertain = self.db.execute(
                "SELECT 1 FROM calls WHERE job_id=? AND action=? AND fingerprint=? "
                "AND state IN ('pending','uncertain')",
                (job["id"], action, fingerprint),
            ).fetchone()
            if uncertain:
                return {
                    "ok": False,
                    "status": "uncertain",
                    "error": "相同操作已有未确认结果，禁止自动重发",
                }
            current, current_context = await self.identity(body["session_id"])
            if current["id"] != job["id"] or current_context != context:
                raise PermissionError("任务归属已变化")
            if name != "export":
                await self.version()
            current, current_context = await self.identity(body["session_id"])
            if current["id"] != job["id"] or current_context != context:
                raise PermissionError("任务归属已变化")
            now = time.time()
            self.db.execute(
                "INSERT OR REPLACE INTO calls VALUES (?,?,?,?,?,NULL,?,?)",
                (key, job["id"], action, fingerprint, "pending", now, now),
            )
            self.db.commit()
            try:
                if name == "call":
                    data = (
                        await self.stream(action, params, job)
                        if action in DOWNLOADS
                        else await self.onebot.call(action, params, response_timeout=30)
                    )
                elif name == "upload":
                    data = await self.upload(job, args["path"])
                else:
                    data = self.export(job, args["file_ref"])
                result = {
                    "ok": True,
                    "status": "confirmed",
                    "action": action,
                    **self.pack(job["id"], action, data, command=params.get("cmd")),
                }
            except Unavailable:
                result = {"ok": False, "status": "not_sent", "error": "NapCat 未连接，请稍后再试"}
            except (DeliveryUnknown, TimeoutError, OSError, asyncio.CancelledError) as exc:
                result = {
                    "ok": False,
                    "status": "uncertain",
                    "action": action,
                    "error": "结果未确认，可能已经执行；不要自动重试",
                }
                self.finish(key, result)
                if isinstance(exc, asyncio.CancelledError):
                    raise
                return result
            except ActionError as exc:
                result = {"ok": False, "status": "failed", "action": action, "error": str(exc)}
            except (ValueError, PermissionError) as exc:
                result = {"ok": False, "status": "failed", "error": str(exc)}
            self.finish(key, result)
            return result

    async def upload(self, job, path):
        root = delivery.directory(self.config, job["id"])
        incoming = self.config.workdir.resolve() / ".qq-attachments" / job["id"]
        candidate = Path(path)
        candidate = candidate if candidate.is_absolute() else root / candidate
        allowed = incoming if candidate.resolve().is_relative_to(incoming) else root
        data = await asyncio.to_thread(
            delivery.read_file, candidate, allowed, self.config.max_attachment_bytes
        )

        def cancelled():
            return bool(self.store.job(job["id"])["cancel_requested"])

        result = await self.onebot.upload_file(
            data, candidate.name, self.config.download_timeout, cancelled
        )
        return {"napcat_path": result, "bytes": len(data), "name": candidate.name}

    def export(self, job, ref):
        row = self.db.execute(
            "SELECT * FROM artifacts WHERE ref=? AND job_id=?", (ref, job["id"])
        ).fetchone()
        if not row:
            raise ValueError("文件引用不存在或不属于当前任务")
        data = delivery.read_file(
            Path(row["path"]), self.root / "artifacts", self.config.max_attachment_bytes
        )
        delivery.prepare_directory(self.config, job["id"])
        target = delivery.directory(self.config, job["id"]) / (
            uuid.uuid4().hex + Path(row["name"]).suffix
        )
        with target.open("xb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
        return {"path": str(target), "name": row["name"], "bytes": len(data)}

    async def stream(self, action, params, job):
        target = self.root / "artifacts" / uuid.uuid4().hex
        received, index, advertised, result_frames, name = 0, 0, None, [], "napcat-download.bin"
        try:
            async with asyncio.timeout(self.config.download_timeout):
                with target.open("xb") as output:
                    os.fchmod(output.fileno(), 0o600)
                    async with self.onebot.stream_request(
                        action, {**params, "chunk_size": 65536}, queue_size=128
                    ) as frame_iter:
                        async for frame in frame_iter:
                            if frame.get("retcode") != 0:
                                raise ActionError(action, frame.get("retcode"))
                            data = frame.get("data", {})
                            if data.get("type") == "error":
                                raise ValueError("文件流返回错误")
                            kind = data.get("data_type")
                            if kind == "file_info":
                                if advertised is not None:
                                    raise ValueError("文件流重复声明大小")
                                advertised = int(data["file_size"])
                                if not 0 <= advertised <= self.config.max_attachment_bytes:
                                    raise ValueError("文件流超过大小限制")
                                staged = self.db.execute(
                                    "SELECT coalesce(sum(bytes),0) FROM artifacts WHERE job_id=?",
                                    (job["id"],),
                                ).fetchone()[0]
                                if staged + advertised > self.config.max_attachment_bytes:
                                    raise ValueError("本轮下载文件总大小超过限制")
                                name = re.sub(
                                    r"[\x00-\x1f/\\]", "_", str(data.get("file_name") or name)
                                )[:100]
                            elif kind == "file_chunk":
                                chunk = base64.b64decode(data.get("data", ""), validate=True)
                                if (
                                    advertised is None
                                    or int(data.get("index", -1)) != index
                                    or len(chunk) != data.get("size")
                                ):
                                    raise ValueError("文件分块顺序或长度错误")
                                received += len(chunk)
                                if received > advertised:
                                    raise ValueError("文件流超过声明大小")
                                output.write(chunk)
                                index += 1
                            else:
                                if len(result_frames) < 100:
                                    result_frames.append(data)
                            if data.get("type") == "response":
                                if advertised is not None:
                                    if (
                                        received != advertised
                                        or data.get("total_bytes") != received
                                        or data.get("total_chunks") != index
                                    ):
                                        raise ValueError("文件流缺少完整结束确认")
                                    ref = "file_" + uuid.uuid4().hex
                                    output.flush()
                                    os.fsync(output.fileno())
                                    self.db.execute(
                                        "INSERT INTO artifacts VALUES (?,?,?,?,?,?)",
                                        (ref, job["id"], str(target), name, received, time.time()),
                                    )
                                    self.db.commit()
                                    return {"file_ref": ref, "name": name, "bytes": received}
                                if action != "test_download_stream":
                                    raise ValueError("文件流缺少文件信息，不能确认下载完成")
                                return {"frames": result_frames}
        finally:
            if not self.db.execute(
                "SELECT 1 FROM artifacts WHERE path=?", (str(target),)
            ).fetchone():
                target.unlink(missing_ok=True)

    async def handle(self, request):
        if not self.token or not hmac.compare_digest(
            request.headers.get("Authorization", "").encode(), ("Bearer " + self.token).encode()
        ):
            return web.json_response({"ok": False}, status=401)
        try:
            body = await request.json()
            job, context = await self.identity(body.get("session_id"))
            if request.path == "/context":
                return web.json_response(
                    {"available": True, "administrator": is_superadmin(self.config, context)}
                )
            name, args = body.get("name"), body.get("arguments")
            schemas = {
                "list": {
                    "query": {"type": "string", "maxLength": 200},
                    "offset": {"type": "integer", "minimum": 0},
                },
                "describe": {"action": {"type": "string", "maxLength": 100}},
                "schema": {"name": {"type": "string", "maxLength": 100}},
                "call": {
                    "action": {"type": "string", "maxLength": 100},
                    "params": {"type": "object"},
                },
                "upload": {"path": {"type": "string", "maxLength": 1000}},
                "export": {"file_ref": {"type": "string", "maxLength": 100}},
                "result": {
                    "ref": {"type": "string", "maxLength": 100},
                    "offset": {"type": "integer", "minimum": 0},
                },
            }
            if name not in schemas:
                raise ValueError("工具不存在")
            required = (
                [] if name == "list" else ["ref"] if name == "result" else list(schemas[name])
            )
            jsonschema.validate(
                args,
                {
                    "type": "object",
                    "properties": schemas[name],
                    "required": required,
                    "additionalProperties": False,
                },
            )
            if name == "list":
                q, offset = args.get("query", "").casefold(), args.get("offset", 0)
                items = [
                    {
                        "action": a,
                        "description": d["description"],
                        "available": d["available"],
                        "tags": d.get("tags", []),
                    }
                    for a, d in self.catalogue["actions"].items()
                    if q in (a + d["description"] + " ".join(d.get("tags", []))).casefold()
                ]
                result = {
                    "version": self.catalogue["version"],
                    "items": items[offset : offset + 25],
                    "total": len(items),
                    "next": offset + 25 if len(items) > offset + 25 else None,
                }
            elif name == "describe":
                result = {"action": args["action"], **compact_schema(self.lookup(args["action"]))}
            elif name == "schema":
                value = self.catalogue["definitions"].get(args["name"])
                if value is None:
                    raise ValueError("公共数据类型不存在")
                result = {"name": args["name"], "schema": value}
            elif name == "result":
                item = self.results.get(args["ref"])
                if (
                    not is_superadmin(self.config, context)
                    or not item
                    or item["job_id"] != job["id"]
                    or item["expires"] < time.time()
                ):
                    raise PermissionError("结果引用已过期或不属于当前任务")
                offset, text = args.get("offset", 0), item["value"]
                result = {
                    "text": text[offset : offset + 8000],
                    "next": offset + 8000 if len(text) > offset + 8000 else None,
                }
            else:
                result = await self.execute(body, job, context)
            return web.json_response({"ok": True, **result})
        except PermissionError as exc:
            return web.json_response({"ok": False, "error": str(exc) or "无权调用"}, status=403)
        except (ValueError, KeyError, TypeError, AttributeError, jsonschema.ValidationError):
            return web.json_response(
                {"ok": False, "error": "参数、接口或版本不匹配，请核对本机接口说明"}, status=400
            )
        except Exception:
            log.warning("NapCat 工具未取得确认结果")
            return web.json_response(
                {"ok": False, "status": "uncertain", "error": "未确认结果，不要自动重试"},
                status=503,
            )
