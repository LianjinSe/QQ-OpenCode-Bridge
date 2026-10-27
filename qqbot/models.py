from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Context:
    self_id: int
    user_id: int
    group_id: int | None = None

    @property
    def key(self) -> str:
        if self.group_id is None:
            return f"{self.self_id}:private:{self.user_id}"
        return f"{self.self_id}:group:{self.group_id}:{self.user_id}"

    @property
    def conversation_key(self) -> str:
        if self.group_id is None:
            return self.key
        return f"{self.self_id}:group:{self.group_id}"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Attachment:
    reference: str
    name: str = "attachment"
    size: int | None = None
    kind: str = "file"
    url: str | None = field(default=None, repr=False)
    inline_text: str | None = field(default=None, repr=False)

    def to_dict(self) -> dict:
        result = asdict(self)
        if self.inline_text is None:
            result.pop("inline_text")
        return result


@dataclass
class Incoming:
    context: Context
    event_id: str
    text: str
    mentioned: bool = False
    attachments: list[Attachment] = field(default_factory=list)
    notice: bool = False
    reply_id: str | None = None
    forwards: list[dict] = field(default_factory=list)
    nickname: str = ""
    timestamp: float | None = None
    mentions: list[str] = field(default_factory=list)
    command_text: str = ""
    body_text: str = ""


@dataclass
class ReplyContent:
    attachments: list[Attachment] = field(default_factory=list)
    chat_records: list[dict] = field(default_factory=list)
    quoted_text: str = ""
    card_links: list[str] = field(default_factory=list)


def identifier(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("Invalid QQ identifier")
    text = str(value)
    if not text.isascii() or not text.isdecimal() or int(text) <= 0:
        raise ValueError("Invalid QQ identifier")
    return int(text)


def segments(message: Any) -> list[dict]:
    if isinstance(message, list):
        return [s for s in message if isinstance(s, dict) and isinstance(s.get("data"), dict)]
    # Legacy CQ strings recognize @, replies, and forwards; media must be structured.
    # file names and CQ-looking ordinary text cannot become filesystem attachments.
    if isinstance(message, str):
        result = []
        start = 0
        for match in re.finditer(
            r"\[CQ:(?:at,qq=(?P<qq>\d+|all)|reply,id=(?P<reply>-?\d+)"
            r"|forward,id=(?P<forward>[^\],]+))\]",
            message,
        ):
            result.append(
                {"type": "text", "data": {"text": html.unescape(message[start : match.start()])}}
            )
            if match.group("qq") is not None:
                result.append({"type": "at", "data": {"qq": match.group("qq")}})
            elif match.group("reply") is not None:
                result.append({"type": "reply", "data": {"id": match.group("reply")}})
            else:
                result.append(
                    {"type": "forward", "data": {"id": html.unescape(match.group("forward"))}}
                )
            start = match.end()
        result.append({"type": "text", "data": {"text": html.unescape(message[start:])}})
        return result
    return []


def normalize(event: dict) -> Incoming | None:
    if event.get("post_type") not in {"message", "notice"}:
        return None
    try:
        self_id, user_id = identifier(event["self_id"]), identifier(event["user_id"])
        group_id = identifier(event["group_id"]) if event.get("group_id") is not None else None
    except (KeyError, ValueError):
        return None
    if user_id == self_id:
        return None
    context = Context(self_id, user_id, group_id)
    if event.get("post_type") == "notice":
        if event.get("notice_type") != "group_upload" or group_id is None:
            return None
        file = event.get("file", {})
        if not isinstance(file, dict) or not file.get("id"):
            return None
        ref = str(file["id"])
        return Incoming(
            context,
            f"upload:{ref}:{event.get('time', '')}",
            "",
            attachments=[
                Attachment(ref, str(file.get("name", "attachment")), valid_size(file.get("size")))
            ],
            notice=True,
        )
    if event.get("message_type") not in {"private", "group"}:
        return None
    if (event["message_type"] == "group") != (group_id is not None):
        return None
    if "message_id" not in event:
        return None
    body, attachments, mentioned = [], [], False
    reply_id = None
    forwards = []
    mentions = []
    plain = []
    command_body = []
    leading = True
    for segment in segments(event.get("message")):
        kind, data = segment.get("type"), segment["data"]
        if kind == "text":
            value = str(data.get("text", ""))
            body.append(value)
            plain.append(value)
            command_body.append(value)
            if value.strip():
                leading = False
        elif kind == "at":
            target = str(data.get("qq", ""))
            mentions.append(target)
            if target == str(self_id):
                mentioned = True
            else:
                body.append(f"@{target} ")
                if not leading:
                    command_body.append(f"@{target} ")
        elif kind == "reply" and reply_id is None:
            value = data.get("id")
            if not isinstance(value, bool) and isinstance(value, (str, int)):
                candidate = str(value)
                if len(candidate) <= 24 and re.fullmatch(r"-?[0-9]+", candidate):
                    reply_id = candidate
        elif kind in {"image", "file"}:
            item = attachment_from_segment(kind, data)
            if item is not None:
                attachments.append(item)
        elif kind == "forward":
            forwards.append(data)
        elif kind == "node":
            forwards.append({"content": [segment]})
    sender = event.get("sender")
    sender = sender if isinstance(sender, dict) else {}
    return Incoming(
        context,
        str(event["message_id"]),
        "".join(body).lstrip(),
        mentioned,
        attachments,
        reply_id=reply_id,
        forwards=forwards,
        nickname=str(sender.get("card") or sender.get("nickname") or ""),
        timestamp=event.get("time") if isinstance(event.get("time"), (int, float)) else None,
        mentions=mentions,
        command_text="".join(command_body).strip(),
        body_text="".join(plain).strip(),
    )


def qq_image_url(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 8192:
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
        ):
            return None
    except ValueError:
        return None
    host = parsed.hostname or ""
    if host == "multimedia.nt.qq.com.cn" or host == "qpic.cn" or host.endswith(".qpic.cn"):
        return value
    return None


def attachment_from_segment(kind: str, data: dict) -> Attachment | None:
    ref = data.get("file_id") or data.get("file")
    if not ref:
        return None
    return Attachment(
        str(ref),
        str(
            data.get("name")
            or data.get("file_name")
            or {"image": "image", "video": "video", "audio": "audio", "record": "audio"}.get(
                kind, "attachment"
            )
        ),
        valid_size(data.get("size", data.get("file_size"))),
        "audio" if kind == "record" else kind,
        qq_image_url(data.get("url")) if kind == "image" else None,
    )


def valid_size(value: Any) -> int | None:
    try:
        size = int(value)
        return size if size >= 0 else None
    except (TypeError, ValueError):
        return None


def excluded(text: str, prefixes: tuple[str, ...]) -> bool:
    return text.lstrip().casefold().startswith(prefixes) if prefixes else False


def unique_attachments(items: list[Attachment]) -> list[Attachment]:
    return list({item.reference: item for item in items}.values())
