"""Authenticated management console, hosted by the bridge's aiohttp event loop."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import secrets
import time
from collections import deque
from pathlib import Path

import aiohttp
from aiohttp import web

from .http_params import page_number
from .knowledge import MAX_UPLOAD, KnowledgeError
from .models import Context
from .opencode import ApiError, ProtocolError
from .webui_auth import COOKIE_NAME, SESSION_SECONDS, AdminAuth
from .webui_capabilities import CapabilitiesConsole
from .webui_context import ContextConsole
from .webui_data import UNFINISHED, DashboardData
from .webui_export import ExportConsole
from .webui_knowledge import KnowledgeConsole
from .webui_sessions import SessionConsole

log = logging.getLogger(__name__)
ASSETS = Path(__file__).with_name("webui_static")


async def restart_bridge():
    process = await asyncio.create_subprocess_exec(
        "/usr/bin/systemctl",
        "restart",
        "--no-block",
        "qqbot.service",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    async with asyncio.timeout(10):
        if await process.wait():
            raise RuntimeError("systemd 未接受重启请求")


class AdminDashboard:
    def __init__(
        self,
        config,
        store,
        onebot,
        opencode,
        knowledge,
        memory,
        control_lock,
        jobs_ready,
        *,
        restart=restart_bridge,
    ):
        self.config, self.store, self.onebot, self.opencode = config, store, onebot, opencode
        self.knowledge, self.memory = knowledge, memory
        self.control_lock, self.jobs_ready = control_lock, jobs_ready
        self.data = DashboardData(config, onebot, opencode, knowledge, memory)
        self.restart = restart
        self.auth = None
        self.started = time.monotonic()
        self.boot_id = secrets.token_hex(12)
        self.login_attempts = deque(maxlen=20)
        self.login_limit = asyncio.Semaphore(2)
        self.restart_pending = False
        self.restart_error = None
        self.background = set()
        self.runner = None
        self.site = None

    def audit(self, action, target=""):
        self.auth.record(action, target)
        log.info("WebUI action=%s target=%s", action, target or "-")

    @staticmethod
    async def body(request):
        content = bytearray()
        async for chunk in request.content.iter_chunked(16384):
            content.extend(chunk)
            if len(content) > 65536:
                raise web.HTTPRequestEntityTooLarge(max_size=65536, actual_size=len(content))
        value = json.loads(content)
        if not isinstance(value, dict):
            raise ValueError("请求应为 JSON 对象")
        return value

    @web.middleware
    async def middleware(self, request, handler):
        try:
            if request.path.startswith("/api/"):
                if request.method not in {"GET", "HEAD"}:
                    origin = request.headers.get("Origin")
                    expected = self.config.webui_public_url or f"{request.scheme}://{request.host}"
                    if (origin and origin != expected) or request.headers.get(
                        "Sec-Fetch-Site"
                    ) == "cross-site":
                        raise web.HTTPForbidden(text="请求来源不匹配")
                public = request.path in {"/api/auth/status", "/api/auth/login"}
                token = request.cookies.get(COOKIE_NAME, "")
                if not public:
                    if not self.auth.valid(token):
                        raise web.HTTPUnauthorized(text="请先登录管理台")
                    if request.method not in {"GET", "HEAD"} and not hmac.compare_digest(
                        request.headers.get("X-CSRF-Token", "").encode(),
                        self.auth.csrf(token).encode(),
                    ):
                        raise web.HTTPForbidden(text="登录校验已失效，请刷新页面")
            response = await handler(request)
        except web.HTTPException as exc:
            response = web.json_response({"error": exc.text}, status=exc.status)
        except KnowledgeError as exc:
            response = web.json_response({"error": str(exc)}, status=400)
        except (ValueError, KeyError) as exc:
            response = web.json_response(
                {"error": "记录不存在" if isinstance(exc, KeyError) else "输入参数无效"},
                status=404 if isinstance(exc, KeyError) else 400,
            )
        except (ApiError, ProtocolError, aiohttp.ClientError, TimeoutError, OSError):
            response = web.json_response({"error": "服务暂不可用，请稍后重试"}, status=503)
        except Exception:
            # Do not log raw request bodies, tool output, credentials, or private transcripts.
            log.error(
                "WebUI request failed: %s %s",
                request.method,
                request.match_info.route.name or "unknown",
            )
            response = web.json_response({"error": "操作未完成，请稍后重试"}, status=500)
        response.headers.update(
            {
                "Cache-Control": (
                    "public, max-age=86400"
                    if request.match_info.route.name == "asset"
                    and request.match_info.get("name") in {"favicon.svg", "assistant-avatar.svg"}
                    and response.status == 200
                    else "no-store"
                ),
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": (
                    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                    "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
                    "base-uri 'none'; form-action 'self'"
                ),
            }
        )
        return response

    async def application(self):
        self.auth = await asyncio.to_thread(AdminAuth, self.config.state_db.parent)
        self.data.history = lambda: self.auth.data.get("session_history", [])
        app = web.Application(middlewares=[self.middleware], client_max_size=MAX_UPLOAD + 65536)
        app.add_routes(KnowledgeConsole(self).routes())
        app.add_routes(ContextConsole(self).routes())
        app.add_routes(SessionConsole(self).routes())
        app.add_routes(ExportConsole(self).routes())
        app.add_routes(CapabilitiesConsole(self).routes())
        app.add_routes(
            [
                web.get("/", self.index, name="index"),
                web.get("/assets/{name}", self.asset, name="asset"),
                web.get("/api/auth/status", self.auth_status, name="auth-status"),
                web.post("/api/auth/login", self.login, name="login"),
                web.post("/api/auth/logout", self.logout, name="logout"),
                web.post("/api/auth/password", self.password, name="password"),
                web.get("/api/overview", self.overview, name="overview"),
                web.get("/api/conversations", self.conversations, name="conversations"),
                web.get("/api/jobs", self.jobs, name="jobs"),
                web.get("/api/jobs/{id}", self.job, name="job"),
                web.post("/api/jobs/{id}/cancel", self.cancel_job, name="cancel"),
                web.get("/api/sessions/{id}", self.session, name="session"),
                web.get("/api/sessions", self.sessions, name="sessions"),
                web.post("/api/mappings", self.switch_mapping, name="mapping"),
                web.get("/api/memories", self.memories, name="memories"),
                web.get("/api/system", self.system, name="system"),
                web.post("/api/system/restart", self.restart_service, name="restart"),
            ]
        )
        return app

    async def start(self):
        self.runner = web.AppRunner(await self.application(), access_log=None)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.config.webui_host, self.config.webui_port)
        await self.site.start()
        log.info("WebUI 已启动，监听 %s:%s", self.config.webui_host, self.config.webui_port)

    async def close(self):
        for task in self.background:
            task.cancel()
        await asyncio.gather(*self.background, return_exceptions=True)
        if self.runner:
            await self.runner.cleanup()

    async def run(self):
        try:
            await self.start()
            await asyncio.Future()
        except (OSError, ValueError, KeyError):
            log.error("WebUI 启动失败，QQ 桥接继续运行；请检查管理台配置与认证文件")
        finally:
            await self.close()

    async def index(self, request):
        return web.FileResponse(ASSETS / "console.html")

    async def asset(self, request):
        name = request.match_info["name"]
        if name not in {
            "console.js",
            "console-conversations.js",
            "console-knowledge.js",
            "console-context.js",
            "style.css",
            "theme.css",
            "serif-sc.woff2",
            "mono.woff2",
            "mist.svg",
            "JetBrainsMono-OFL.txt",
            "NotoSerifSC-OFL.txt",
            "favicon.svg",
            "assistant-avatar.svg",
            "Lucide-LICENSE.txt",
        }:
            raise web.HTTPNotFound()
        return web.FileResponse(ASSETS / name)

    def auth_payload(self, token):
        valid = self.auth.valid(token)
        return {
            "authenticated": valid,
            "username": self.auth.data["username"] if valid else None,
            "admin_user_id": self.config.superadmin_user_id if valid else None,
            "knowledge_enabled": self.config.knowledge_enabled if valid else None,
            "csrf": self.auth.csrf(token) if valid else None,
            "initial_password": bool(valid and self.auth.data["initial"]),
            "boot_id": self.boot_id,
        }

    async def auth_status(self, request):
        return web.json_response(self.auth_payload(request.cookies.get(COOKIE_NAME, "")))

    def session_response(self, token):
        response = web.json_response(self.auth_payload(token))
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=SESSION_SECONDS,
            httponly=True,
            samesite="Strict",
            secure=self.config.webui_public_url.startswith("https://"),
            path="/",
        )
        return response

    async def login(self, request):
        now = time.monotonic()
        while self.login_attempts and self.login_attempts[0] < now - 60:
            self.login_attempts.popleft()
        if len(self.login_attempts) >= 10:
            raise web.HTTPTooManyRequests(text="尝试次数过多，请一分钟后再试")
        self.login_attempts.append(now)
        body = await self.body(request)
        username, password = body.get("username"), body.get("password")
        if (
            not isinstance(username, str)
            or not isinstance(password, str)
            or len(username) > 64
            or len(password) > 256
        ):
            raise ValueError("登录输入无效")
        async with self.login_limit:
            valid = await asyncio.to_thread(self.auth.check, username, password)
        if not valid:
            raise web.HTTPUnauthorized(text="账号或密码不正确")
        token = self.auth.create_session()
        self.audit("login")
        return self.session_response(token)

    async def logout(self, request):
        self.auth.revoke(request.cookies.get(COOKIE_NAME, ""))
        response = web.json_response({"ok": True})
        response.del_cookie(COOKIE_NAME, path="/")
        return response

    async def password(self, request):
        body = await self.body(request)
        username = body.get("username", "").strip() if isinstance(body.get("username"), str) else ""
        current, password = body.get("current_password"), body.get("password")
        if (
            not username
            or len(username) > 64
            or not isinstance(current, str)
            or len(current) > 256
            or not isinstance(password, str)
            or not 12 <= len(password) <= 256
        ):
            raise web.HTTPBadRequest(text="用户名需为 1–64 字，密码需为 12–256 字")
        if not await asyncio.to_thread(self.auth.change, username, password, current):
            raise web.HTTPForbidden(text="当前密码不正确")
        token = self.auth.create_session()
        self.audit("password_changed")
        return self.session_response(token)

    async def overview(self, request):
        result = await asyncio.to_thread(self.data.overview)
        result.update(
            napcat_online=bool(self.onebot.online),
            opencode_online=bool(self.opencode.available),
            uptime_seconds=time.monotonic() - self.started,
            boot_id=self.boot_id,
            restart_pending=self.restart_pending,
            restart_error=self.restart_error,
        )
        return web.json_response(result)

    async def conversations(self, request):
        return web.json_response(
            await asyncio.to_thread(
                self.data.conversations,
                request.query.get("q", "")[:200],
                page_number(request, "offset"),
            )
        )

    async def jobs(self, request):
        return web.json_response(
            await asyncio.to_thread(
                self.data.jobs,
                request.query.get("conversation"),
                before=request.query.get("before"),
                unfinished=request.query.get("unfinished") == "1",
            )
        )

    async def job(self, request):
        job_id = request.match_info["id"]
        try:
            result = await self.data.job_detail(job_id)
        except (ApiError, ProtocolError, aiohttp.ClientError, TimeoutError, OSError):
            result = await asyncio.to_thread(self.data.local_job, job_id)
            result.update(
                messages=[],
                metrics=None,
                complete=False,
                remote_error="OpenCode 记录暂不可用；桥接保存的任务与交付记录仍可查看。",
            )
        return web.json_response(result)

    async def session(self, request):
        return web.json_response(
            await self.data.session_messages(
                request.match_info["id"],
                request.query.get("cursor"),
            )
        )

    async def sessions(self, request):
        return web.json_response(await self.data.sessions())

    async def switch_mapping(self, request):
        body = await self.body(request)
        if body.get("confirm") != "switch":
            raise web.HTTPBadRequest(text="请确认切换会话映射")
        conversation, session_id = body.get("conversation"), body.get("session_id")
        if not isinstance(conversation, str) or not isinstance(session_id, str):
            raise ValueError("会话参数无效")
        inventory = await self.data.sessions(fresh=True)
        mapping = next(
            (m for m in inventory["mappings"] if m["conversation"] == conversation), None
        )
        candidate = next((s for s in inventory["items"] if s["id"] == session_id), None)
        if mapping is None or candidate is None:
            raise KeyError(session_id)
        if candidate["conversation"] != conversation or not candidate["eligible"]:
            raise web.HTTPForbidden(
                text="只能切换到同一聊天中可复用的会话；私密独立会话不能用于群共享"
            )
        if candidate.get("archived"):
            raise web.HTTPConflict(text="请先恢复归档会话，再切换映射")
        async with self.control_lock:
            if mapping["session_id"] != body.get("expected_current"):
                raise web.HTTPConflict(text="当前映射已有变化，请刷新后重试")
            client = self.data.client()
            active = await client.active()
            for root in {mapping["session_id"], session_id} - {None}:
                if await client.inbox(root):
                    raise web.HTTPConflict(text="原会话或目标会话还有待处理请求，请等待完成后切换")
            for active_id in active:
                for root in {mapping["session_id"], session_id} - {None}:
                    if await client.belongs_to(active_id, root):
                        raise web.HTTPConflict(text="原会话或目标会话仍在执行，请等待结束后切换")
            target_info = await client.get_session(session_id)
            if target_info.get("archived") or (target_info.get("time") or {}).get("archived"):
                raise web.HTTPConflict(text="目标会话已经归档，请恢复后再切换")
            context = Context(**mapping["target"])
            # Recheck after network I/O. No await may separate this check from the update.
            if self.store.conversation_jobs(context):
                raise web.HTTPConflict(text="这个聊天还有未完成任务，请先等待完成或取消")
            current = self.store.session(context)
            if current != body.get("expected_current"):
                raise web.HTTPConflict(text="当前映射已有变化，请刷新后重试")
            self.auth.remember_sessions(conversation, {current, session_id})
            self.store.switch_session(context, session_id)
            self.data.cache.clear()
            self.audit("mapping_switched", conversation + " => " + session_id)
        return web.json_response({"ok": True, "session_id": session_id})

    async def cancel_job(self, request):
        async with self.control_lock:
            job_id = request.match_info["id"]
            job = self.store.job(job_id)
            if job["steer_parent_id"] or job["status"] not in UNFINISHED:
                raise web.HTTPConflict(text="这个任务已经结束，或需要从原任务操作")
            self.store.cancel_job(job_id)
            self.jobs_ready.set()
            self.audit("cancel_requested", job_id)
        return web.json_response({"ok": True, "status": "cancel_requested"})

    async def memories(self, request):
        return web.json_response(
            await asyncio.to_thread(
                self.data.memories,
                query=request.query.get("q", "")[:200],
                kind=request.query.get("kind", "")[:30],
                subject=request.query.get("subject", "")[:30],
                offset=page_number(request, "offset"),
            )
        )

    async def system(self, request):
        return web.json_response(
            {
                "service": "qqbot.service",
                "restart_scope": "bridge_only",
                "config": {
                    "public_url": self.config.webui_public_url,
                    "model": self.config.model or "继承 OpenCode 默认模型",
                    "memory_enabled": self.config.memory_enabled,
                    "memory_model": self.config.memory_model,
                    "embedding_model": self.config.memory_embedding_model,
                    "rerank_model": self.config.memory_rerank_model,
                    "max_queued_per_context": self.config.max_queued_per_context,
                    "execution_timeout": self.config.execution_timeout,
                },
                "audit": list(reversed(self.auth.data.get("audit", []))),
            }
        )

    async def restart_service(self, request):
        body = await self.body(request)
        if body.get("confirm") != "restart":
            raise web.HTTPBadRequest(text="请确认重启桥接服务")
        if self.restart_pending:
            raise web.HTTPConflict(text="重启请求已经提交")
        self.restart_pending, self.restart_error = True, None
        self.audit("restart_requested", "qqbot.service")
        task = asyncio.create_task(self.perform_restart())
        self.background.add(task)
        task.add_done_callback(self.background.discard)
        return web.json_response(
            {"status": "restart_requested", "boot_id": self.boot_id}, status=202
        )

    async def perform_restart(self):
        try:
            # Flush the HTTP acknowledgement before systemd terminates this process.
            await asyncio.sleep(0.7)
            await self.restart()
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError, TimeoutError):
            self.restart_pending = False
            self.restart_error = "重启请求未被 systemd 接受，请检查服务权限与状态。"
            log.error("WebUI bridge restart failed")
