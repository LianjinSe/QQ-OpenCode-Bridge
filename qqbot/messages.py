"""User-facing bridge copy in a friendly chat style; diagnostics stay in service logs."""

from __future__ import annotations

import json
import re

from .models import Context

HELP_COMMANDS = (
    "/status 看看我忙到哪啦；/cancel 停止任务并清空这个聊天的队列；/new 换个新话题。\n"
    "/approve <编号> 批准这一次操作；/reject <编号> 不做这一步；/answer <编号> <回答>。\n"
)

PRIVATE_HELP = (
    "查资料、写代码、看图片或文件，都可以直接发给我呀~\n"
    "我正在处理时，你补发的消息会一起接着看呀。\n"
    + HELP_COMMANDS
    + "发图片时，记得一起写上要我做什么，也可以回复自己那条图片消息告诉我。\n"
    "文件先发给我，再回复自己那条文件消息，告诉我要做什么呀。单独发文件时我会等你说明哦。\n"
    "合并转发也先发给我，再回复自己那条卡片写上说明，我会把聊天记录一起读进去呀。"
)

GROUP_HELP = (
    "本群共享聊天上下文，@我在消息的任何位置都可以呀~\n"
    "/status 查看群任务；/cancel 取消自己的任务，超级管理员可取消全群任务。\n"
    "/new 仅超级管理员可在群任务和交付完成后使用，开始新上下文。\n"
    "/approve <编号> 批准一次；/reject <编号> 拒绝；/answer <编号> <回答> 回答自己的问题。\n"
    "/trace <消息ID> 由超级管理员在本群 @我查询消息处理记录。\n"
    "普通成员改文件需本群超级管理员批准，管理员本人发起的任务自动授权。\n"
    "回复同群文字、图片、文件或转发卡片并 @我即可；不写说明时按“看看这个”处理。\n"
    "直接发送文件或转发卡片后，需要回复那条消息再 @我；单独 @我且没有引用时不创建任务。"
)

STATUS_LABELS = {
    "queued": "排着队呢",
    "preparing": "正在收好附件",
    "submitting": "正在开始这件事",
    "running": "正在忙这件事",
    "waiting": "等点头或回答呢",
    "cancelling": "正在停下来",
    "reply_ready": "回复写好啦，正准备发",
    "delivering": "图片或文件正往聊天里发呢",
    "done": "做完啦",
    "failed": "这次没做完",
    "cancelled": "已经停下来啦",
    "send_uncertain": "回复有没有送到还没确认",
    "send_failed": "回复没发成功",
}

QUOTE_UNAVAILABLE = (
    "欸，你回复的那条消息我没读到呀，请确认引用的是当前聊天里的消息，或重发文字、图片、视频、音频、文件或合并转发，"
    "然后回复那条消息告诉我要做什么吧~"
)
CARD_LINK_UNAVAILABLE = "这张分享卡片里没找到可用的网页链接，把链接直接发给我吧。"
FORWARD_LIMIT = "这份聊天记录太长或嵌套太多啦，拆成几个合并转发卡片，再分别回复我说明任务吧~"
DELIVERY_PREPARE_FAILED = "这次的附件没能准备好发回来，文件还没交付。可以让我检查后重新发一次呀。"
DELIVERY_FAILED = "有附件这次没能发成功，完整结果还没交付。可以让我检查后重新发一次呀。"
DELIVERY_UNCERTAIN = (
    "有附件的发送结果还没确认，我先不重复发啦。你看看聊天里有没有收到，再决定是否重发呀。"
)
ATTACHMENT_LIMIT = "这次的附件数量或总大小超限啦，少发一点或压小一点，再交给我吧~"
QUEUE_FULL = (
    "欸？等一下等一下，我现在有点太忙了，思考不过来啦~\n"
    "这条还没排进去哦，等我忙完一点再发，或用 /cancel 取消自己的任务"
    "（超级管理员可取消本群全部任务）。"
)
QUEUED = "收到啦，我先把上一件事忙完，这条已经替你排好队啦~"
NEW_BLOCKED = "手头的事还没停下来呢，先 /cancel，等我停好再 /new 好嘛~"
NEW_STARTED = "那我们换个新话题啦~下一条消息会开始新一轮聊天。"
REQUEST_MISSING = "欸，我没找到还在等处理的这个编号呀，可能已经结束或过期啦。"
PERMISSION_DENIED = "这一步要由本群的超级管理员批准呀，这里还不能处理这条请求哦。"
ANSWER_DENIED = "这个问题要回到发起任务的聊天里，由发起人回答呀。"
REQUEST_EXPIRED = "这条请求已经过期，或任务正在停下来，这会儿不能继续处理啦。"
REQUEST_MISMATCH = "欸，这个编号和指令没对上呀，照着那条提示里的指令回复就行啦~"
REQUEST_ENDED = "这一条已经在 OpenCode 里结束啦，不用再回它了~"
APPROVED = "收到啦，这次批准记下了，我继续这一步~"
REJECTED = "知道啦，这一步我不做了~"
ANSWER_SUBMITTED = "记下你的回答啦，已经提交了，我接着做~"
SUBMISSION_UNCERTAIN = "唔，刚才的提交还没确认成功呀。先用 /status 看一眼，再决定要不要重试~"
INTERACTION_TIMEOUT = "等你点头或回答等得有点久啦，这件事已经停下来，要继续的话再发我一次吧~"
EXECUTION_TIMEOUT = "这件事执行超时啦，我已经停下来了，等会儿再试，或把任务拆小一点交给我吧~"
INTERRUPTED = "这件事已经停下来啦~"
NO_TEXT = "这次已经处理完啦，不过没有文字回复可以发给你呀。"
TASK_FAILED = (
    "唔，这次中途卡住了，还没做完呀。可以先看看服务日志或 OpenCode 里的这轮记录，再试一次~"
)

MEMORY_COPY = {
    "denied": "个人记忆目前只为主人开启呀。",
    "missing_content": "想让我记住或忘掉哪件事呀？比如 /remember 我喜欢喝茶。",
    "secret": "这段里有密码或密钥呀，我就不把它记进长期记忆啦。",
    "bad_date": "日期这样写就好呀：/diary 2026-10-22，也可以写今天或昨天。",
    "status": (
        "我现在记着 {entries} 条记忆，留着 {archive} 段聊天原文。\n"
        "还有 {work} 件没处理完，得再整理或重试一下呀。\n"
        "想看看或改一改，可以用 /remember、/forget、/memories、/diary、/memory history。"
    ),
    "retry": "之前没处理完的记忆，我会再试一次呀。",
    "queued_remember": "等我把这件事记好呀，记好了就告诉你~",
    "queued_forget": "我先把你说的这件事找出来，处理好就告诉你呀。",
    "queued_list": "我看看现在记着哪些事呀，等我一下~",
    "queued_history": "我找找当时怎么说的，等我一下呀~",
    "queued_diary": "我看看这天的日记呀~",
    "saved": "{address}记住啦，换个新话题也还记得的~",
    "not_saved": "{address}这条我还没记下来呢，不能算已经记好啦。",
    "list_title": "{address}我现在记着这些呀：\n",
    "list_empty": "还没整理出能长期记着的事呢。想让我记住的，可以直接告诉我呀~",
    "history_empty": "我没找到对应的聊天原话呢，换个关键词再找找吧~",
    "diary_title": "{day} 的日记在这儿呀：\n",
    "diary_queued": "这天的日记已经排队啦，晚点用 /diary {day} 来看看呀~",
    "diary_empty": "这天还没有可以整理成日记的聊天呢。",
    "forget_missing": "我没找到这件事对应的记忆呀，这次没有删掉别的内容。",
    "forget_ambiguous": ("我还没法确定你想忘的是哪一条呀，这次先没删。再多告诉我一点内容吧。"),
    "forgotten": (
        "{address}这件事我放下啦，相关的记忆和日记一共清掉了 {count} 条，不会再从旧聊天里记回来。"
    ),
    "originals_kept": "\n之前的聊天原文还留着，但不会再拿这些内容来回忆或整理了。",
    "originals_purged": "\n相关的聊天原文也一起清掉啦。",
    "failed_remember": (
        "{address}这次还没记好呢，先别当作已经保存啦。晚点用 /memory retry，我再试一次。"
    ),
    "failed_forget": (
        "{address}这次还没处理完，先别当作已经全部忘掉啦。晚点用 /memory retry，我接着处理。"
    ),
    "failed": "这次还没处理好呢。晚点用 /memory retry，我再试一次呀。",
    "help": (
        "\n想让我记住的事，可以直接说“记住……”，也可以用 /remember 内容呀。\n"
        "/forget 内容 让我忘掉那件事；/memories 看看我记着什么；/diary 日期 看那天的日记。\n"
        "/memory history 关键词 找聊天原话；/memory 看看记忆的情况。\n"
        "/memory retry 让我再试一次没完成的整理；"
        "/memory purge 关键词 忘掉相关记忆，也清掉相关聊天原文。\n"
        "用 /new 换个话题，之前记住的事也还在哦。"
    ),
}


def memory_reply(context: Context, key: str, **values: object) -> str:
    address = ""
    return MEMORY_COPY[key].format(address=address, **values)


# Original exception strings remain useful for logs and stored diagnostics.
ERROR_MESSAGES = {
    "附件接收缓冲区溢出": "附件传得太快，我这次没收完整呀，少发一点，再发一次吧~",
    "附件超过大小限制": "这个附件超过大小限制啦，压小一点再发给我吧~",
    "附件标识无效": "这个附件的标识不对，我没法取到它呀，重新上传一次吧~",
    "拒绝将文件路径当作 QQ 附件标识": (
        "这个附件标识看起来是本地路径，我不能把它当成 QQ 附件读取呀，请直接上传文件哦。"
    ),
    "附件流提前结束": "附件还没传完就断开啦，我没收完整，再发一次吧~",
    "NapCat 附件下载失败": "刚才没能把附件取下来呀，重新上传一次再交给我吧~",
    "图片链接下载失败": "刚才没能把图片取下来呀，重新上传或转发一次再交给我吧~",
    "附件流无效": "附件传过来的数据格式不对，我这次没法读取呀，重新上传一次吧~",
    "附件分块顺序错误": "附件传过来的顺序乱啦，我没法拼完整，重新上传一次吧~",
    "附件分块长度错误": "附件有一段的长度对不上，我没法拼完整呀，重新上传一次吧~",
    "附件流没有完成标记": "附件传输没有确认结束，我还不能把它当成完整文件呀，再发一次吧~",
    "附件总长度错误": "收到的附件大小对不上，文件可能没传完整呀，重新上传一次吧~",
    "附件下载不完整": "附件这次没收完整呀，重新上传一次，我再看看~",
    "附件下载超时或数据损坏，请重新发送": (
        "附件这次可能传太久，或数据损坏了，我没法完整读取呀，再发一次吧~"
    ),
    "已保存附件缺失或路径无效，请重新发送": (
        "之前收好的附件找不到了，或保存位置不对呀，麻烦重新上传一次~"
    ),
    "无法读取 OpenCode 服务注册文件": (
        "我暂时读不到任务服务的连接记录呀，需要检查一下服务配置再试。"
    ),
    "OpenCode 服务地址无效": "任务服务的地址填得不对，我没法连过去呀，需要先检查一下配置。",
    "OpenCode 后台服务启动超时": "任务服务启动等太久啦，这次没能继续呀，检查一下服务日志再试吧。",
    "OpenCode 后台服务启动失败": "任务服务这次没启动起来呀，需要先看看服务日志里的原因。",
    "桥接服务需要 OpenCode v2，当前服务版本不兼容": (
        "任务服务的版本和这里对不上呀，需要换成 OpenCode v2 才能继续哦。"
    ),
    "OpenCode v2 API 缺少桥接所需接口": (
        "任务服务少了这里需要的接口呀，要先检查一下 OpenCode 的版本和配置。"
    ),
    "OpenCode 返回了无效的 API 响应": (
        "任务服务回来的数据格式不对，我这次读不懂呀，看看服务日志再试吧。"
    ),
    "OpenCode v2 响应缺少 data": (
        "任务服务的回复少了需要的数据，我没法接着处理呀，看看服务日志再试吧。"
    ),
    "OpenCode 会话的来源或工作目录不匹配": (
        "这轮任务的聊天来源或工作目录对不上呀，我先不继续，检查一下会话配置再试哦。"
    ),
}

PERMISSION_ACTIONS = {
    "read": "读取这些文件",
    "glob": "查找这些文件",
    "grep": "搜索这些文件里的内容",
    "edit": "修改这些文件",
    "write": "写入这些文件",
    "patch": "修改这些文件",
    "apply_patch": "修改这些文件",
    "delete": "删除这些文件",
    "remove": "删除这些文件",
    "shell": "执行下面的命令",
    "external_directory": "访问这个目录",
    "websearch": "搜索这些资料",
    "webfetch": "读取这个网页",
    "skill": "使用这个技能",
    "execute": "执行这一步操作",
    "subagent": "启动这个子任务",
}


def permission_prompt(code: str, request: dict) -> str:
    action = request.get("action", "")
    description = PERMISSION_ACTIONS.get(action)
    if description is None:
        description = f"调用 {action} 完成这一步" if action else "执行下面这一步"
    resources = "\n".join(str(value) for value in request.get("resources", []))
    return (
        f"我可以{description}吗？ [{code}]\n"
        f"{resources[:6000]}\n"
        f"/approve {code} 本次批准\n"
        f"/reject {code} 拒绝"
    )


def failure_reply(reason: str, *, stopped: bool = False) -> str:
    text = ERROR_MESSAGES.get(reason)
    if text is None:
        api_error = re.fullmatch(r"OpenCode (.+) 失败（HTTP (\d+)）", reason)
        if api_error:
            operation, status = api_error.groups()
            text = (
                f"唔，这一步请求没成功，我还没做完呀。看看服务日志再试吧~\n"
                f"错误信息：{operation}（HTTP {status}）"
            )
        else:
            text = f"唔，这次遇到一个还没识别的错误，没能做完呀。\n错误信息：{reason}"
    if stopped:
        text += "\n这件事已经停下来啦。"
    return text


def provider_failure_reply(error: dict | None) -> str:
    """Describe a failed model turn without confusing it with successful retries."""
    if not isinstance(error, dict):
        return TASK_FAILED
    detail = {}
    response = error.get("response")
    body = response.get("body") if isinstance(response, dict) else None
    if isinstance(body, str):
        try:
            payload = json.loads(body)
            value = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(value, dict):
                detail = value
        except ValueError:
            pass
    codes = {
        value
        for value in (error.get("type"), error.get("code"), detail.get("type"), detail.get("code"))
        if isinstance(value, str)
    }
    value = error.get("status")
    status = value if isinstance(value, int) else None
    if "upstream_unavailable" in codes:
        return "唔，刚才用到的服务暂时不可用，这次没能做完呀，稍后再发我一次吧~"
    if "provider.context-window-exceeded" in codes:
        return "这轮聊天的内容有点太长啦，这次没能继续。用 /new 开个新话题，再把要做的事发我吧~"
    if status == 429 or "provider.rate-limit" in codes:
        return "欸，那边现在忙不过来啦，这次没能继续，等一会儿再发我一次吧~"
    if status in {408, 504} or any("timeout" in str(code).lower() for code in codes if code):
        return "刚才等服务回复等太久啦，这次没能做完，稍后再试一次吧~"
    if status in {401, 403}:
        return "唔，刚才连接的凭据或权限没有通过，这次没能继续呀，要先检查一下服务配置哦。"
    if isinstance(status, int) and status >= 500:
        return "唔，刚才用到的服务出错了，这次没能做完呀，稍后再发我一次吧~"
    if status in {400, 404, 422}:
        return "唔，刚才的请求没被那边接受，这次没做完呀，需要看一下服务日志再重试哦。"
    return TASK_FAILED
