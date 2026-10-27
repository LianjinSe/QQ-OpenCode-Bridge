from __future__ import annotations

import json
import logging
import time

import aiohttp

from . import messages as copy
from .forms import AnswerError, add_answer, next_field, render_form
from .models import Context
from .onebot import DeliveryUnknown, Unavailable
from .opencode import ApiError, ProtocolError
from .policy import can_decide_permission, has_full_access, is_superadmin

log = logging.getLogger(__name__)

NETWORK_ERRORS = (aiohttp.ClientError, OSError, TimeoutError, Unavailable, DeliveryUnknown)
STATUS_LABELS = copy.STATUS_LABELS


class CommandHandler:
    def __init__(self, *, config, store, onebot, opencode, events, memory, reply, jobs_ready):
        self.config, self.store, self.onebot, self.opencode = config, store, onebot, opencode
        self.events, self.memory, self.reply = events, memory, reply
        self.jobs_ready = jobs_ready

    async def command(self, context: Context, event_id: str, command: str, args: str) -> None:
        key = f"command:{context.key}:{event_id}"
        if command == "/help":
            text = copy.PRIVATE_HELP if context.group_id is None else copy.GROUP_HELP
            if self.config.image_generation_enabled:
                text += "\n想画图也可以直接告诉我，比如“帮我画一只水彩风格的橘猫”。"
                text += "参考图和修改要求可以同条发送，或回复图片说“参考这张图生成头像”。"
                if context.group_id is not None:
                    text += "记得 @我，普通成员的生图操作仍需本群超级管理员批准呀。"
            if self.memory.owns(context):
                text += copy.memory_reply(context, "help")
            self.reply(context, text, key)
        elif command == "/status":
            jobs = self.store.conversation_jobs(context)
            history = self.store.conversation_jobs(context, unfinished=False)
            latest = history[-1] if history else None
            status = (
                STATUS_LABELS.get(latest["status"], "状态还没确认") if latest else "还没接到任务"
            )
            pending = [item for job in jobs for item in self.store.pending_for(job["id"])]
            if context.group_id is not None and is_superadmin(self.config, context):
                pending = list(
                    {
                        item["code"]: item
                        for item in [*pending, *self.store.group_permissions(context)]
                    }.values()
                )
            codes = (
                "、".join(
                    f"{'等批准' if p['kind'] == 'permission' else '等回答'} [{p['code']}]"
                    for p in pending
                )
                or "没有啦"
            )
            role = "超级管理员" if is_superadmin(self.config, context) else "授权用户"
            policy = "按常规规则，需要批准的操作会先问你"
            if has_full_access(self.config, context):
                policy = "你在当前聊天里已经默认授权所有操作啦"
            elif context.group_id is not None:
                policy = "只读操作我会直接做，改文件或还没确认只读的操作要本群超级管理员点头"
            self.reply(
                context,
                "我这边现在是这样呀：\n"
                f"消息连接：{'在线' if self.onebot.online else '离线'}；"
                f"任务连接：{'已连上' if self.opencode.available else '正在等连接'}\n"
                f"这个聊天还有 {len(jobs)} 件事没处理完；最近一件：{status}\n"
                "任务发起人："
                + ("、".join(str(json.loads(j["target"])["user_id"]) for j in jobs) or "无")
                + "\n"
                + f"等点头或回答：{codes}\n你的身份：{role}；操作权限：{policy}",
                # The displayed role comes from the authenticated sender, not model output.
                key,
            )
        elif command == "/cancel":
            all_members = context.group_id is not None and is_superadmin(self.config, context)
            count = self.store.cancel_context(context, all_members=all_members)
            self.jobs_ready.set()
            self.reply(
                context,
                f"已请求取消{'本群全部' if all_members else '你本人'}未完成任务"
                f"（{count} 个任务）。",
                key,
            )
        elif command == "/new":
            if context.group_id is not None and not is_superadmin(self.config, context):
                self.reply(context, "群共享上下文只能由超级管理员重置。", key)
                return
            if self.store.conversation_jobs(context):
                self.reply(context, copy.NEW_BLOCKED, key)
            else:
                self.store.reset_session(context)
                self.reply(context, copy.NEW_STARTED, key)
        elif command == "/trace":
            if context.group_id is None or not is_superadmin(self.config, context):
                self.reply(context, "请由超级管理员在原群 @我查询消息处理记录。", key)
                return
            self.reply(context, self.events.render(context, args.strip()), key)
        else:
            values = args.strip().split(maxsplit=1)
            code = values[0] if values else ""
            answer = values[1] if len(values) > 1 else ""
            item = self.store.interaction(code)
            if item is None or item["state"] != "pending":
                self.reply(context, copy.REQUEST_MISSING, key)
                return
            job = self.store.job(item["job_id"])
            task_context = Context(**json.loads(job["target"]))
            if command in {"/approve", "/reject"}:
                authorized = item["kind"] == "permission" and can_decide_permission(
                    self.config, context, task_context
                )
            else:
                authorized = context == task_context
            if not authorized:
                denied = (
                    copy.PERMISSION_DENIED
                    if command in {"/approve", "/reject"} and task_context.group_id is not None
                    else copy.ANSWER_DENIED
                    if command == "/answer"
                    else "这条请求属于别的聊天呀，要回到发起它的聊天里处理哦。"
                )
                self.events.record(context, event_id, "denied", "interaction_not_owned")
                self.reply(context, denied, key)
                return
            if job["cancel_requested"] or (
                time.time() - item["created"] > self.config.interaction_timeout
            ):
                self.reply(context, copy.REQUEST_EXPIRED, key)
                return
            if (command == "/answer") != (item["kind"] == "form"):
                self.reply(context, copy.REQUEST_MISMATCH, key)
                return
            try:
                permissions, forms = await self.opencode.interactions(job["session_id"])
                remote = next(
                    (
                        x
                        for x in (forms if item["kind"] == "form" else permissions)
                        if x["id"] == item["remote_id"] and x["sessionID"] == item["session_id"]
                    ),
                    None,
                )
                if remote is None:
                    self.store.update_interaction(code, state="expired")
                    self.reply(context, copy.REQUEST_ENDED, key)
                    return
                if command in {"/approve", "/reject"}:
                    await self.opencode.permission(
                        item["session_id"],
                        item["remote_id"],
                        "once" if command == "/approve" else "reject",
                    )
                    self.store.update_interaction(code, state="answered")
                    self.reply(
                        context, copy.APPROVED if command == "/approve" else copy.REJECTED, key
                    )
                    if task_context != context:
                        self.reply(
                            task_context,
                            (
                                f"超级管理员已经批准这一次操作啦 [{code}]，我继续这一步~"
                                if command == "/approve"
                                else f"超级管理员没有批准这一次操作 [{code}]，我就先不做这一步啦~"
                            ),
                            key + ":requester",
                        )
                else:
                    state = add_answer(remote, json.loads(item["answers"]), answer)
                    if next_field(remote, state) is None:
                        await self.opencode.answer(
                            item["session_id"], item["remote_id"], state["values"]
                        )
                        self.store.update_interaction(code, state="answered", answers=state)
                        self.reply(context, copy.ANSWER_SUBMITTED, key)
                    else:
                        self.store.update_interaction(code, answers=state)
                        self.reply(context, render_form(code, remote, state), key)
            except AnswerError as exc:
                self.reply(context, str(exc), key)
            except (ApiError, ProtocolError, *NETWORK_ERRORS):
                self.reply(context, copy.SUBMISSION_UNCERTAIN, key)
