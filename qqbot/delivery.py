from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import uuid
from pathlib import Path

from .config import Config

DELIVERY_ENTRY_KEY = "qq-bridge.delivery"


class DeliveryError(ValueError):
    pass


class DeliveryCancelled(DeliveryError):
    pass


def directory(config: Config, job_id: str) -> Path:
    return config.workdir.resolve() / ".qq-deliveries" / job_id


def marker(job_id: str) -> str:
    return f'<qq-delivery id="{job_id}">'


def image_content(data: bytes) -> bool:
    return data.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a")) or (
        data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    )


def media_kind(data: bytes) -> str:
    if image_content(data):
        return "image"
    if data.startswith((b"#!SILK_V3", b"\x02#!SILK_V3", b"#!AMR")):
        return "audio"
    try:
        result = subprocess.run(
            ["file", "--brief", "--mime-type", "-"],
            input=data[:262144],
            capture_output=True,
            check=True,
            timeout=5,
        )
        mime = result.stdout.decode("ascii", errors="replace").strip()
    except (OSError, subprocess.SubprocessError):
        return "file"
    for prefix, kind in (("image/", "image"), ("video/", "video"), ("audio/", "audio")):
        if mime.startswith(prefix):
            return kind
    return "file"


def prepare_directory(config: Config, job_id: str) -> None:
    root = directory(config, job_id)
    if root.resolve() != root:
        raise DeliveryError("交付目录不能是符号链接")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)


def read_file(path: Path, root: Path, limit: int) -> bytes:
    try:
        if root.resolve() != root or not path.resolve(strict=True).is_relative_to(root):
            raise DeliveryError("文件不在本任务的交付目录内")
        for part in (path, *path.parents):
            if part == root:
                break
            if part.is_symlink():
                raise DeliveryError("不能回传符号链接")
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise DeliveryError("回传目标必须是普通文件")
            if info.st_size > limit:
                raise DeliveryError("回传文件总大小超限")
            data = file.read(limit + 1)
        if not data:
            raise DeliveryError("回传文件不能为空")
        if len(data) > limit:
            raise DeliveryError("回传文件总大小超限")
        return data
    except OSError as exc:
        raise DeliveryError("回传文件不存在或无法读取") from exc


def display_name(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value in {".", ".."}
        or any(char in value for char in ("/", "\\"))
        or any(ord(char) < 32 for char in value)
        or len(value.encode("utf-8")) > 200
    ):
        raise DeliveryError("回传文件名无效")
    return value


def _strip_empty_manifests(reply: str) -> str:
    def strip(match: re.Match[str]) -> str:
        try:
            manifest = json.loads(match[1])
        except ValueError:
            return match[0]
        if isinstance(manifest, dict) and manifest.get("files") == []:
            return ""
        return match[0]

    # 空清单不触发交付，编号过期、缺失或重复也不该吞掉正文。
    clean = re.sub(
        r"^[ \t]*<qq-delivery(?:[ \t]+[^>\r\n]*)?>(.*?)</qq-delivery>[ \t]*(?:\n|$)",
        strip,
        reply,
        flags=re.MULTILINE | re.DOTALL,
    )
    return clean.strip() if clean != reply else reply


def snapshot_reply(reply: str, config: Config, job_id: str) -> tuple[str, list[dict]]:
    reply = _strip_empty_manifests(reply)
    opening = marker(job_id)
    pattern = re.compile(
        r"^[ \t]*" + re.escape(opening) + r"(.*?)</qq-delivery>[ \t]*(?:\n|$)",
        re.MULTILINE | re.DOTALL,
    )
    matches = list(pattern.finditer(reply))
    if not matches and not re.search(r"^[ \t]*<qq-delivery\b", reply, re.MULTILINE):
        return reply, []
    if len(matches) != 1:
        raise DeliveryError("回传清单不存在、重复或不属于本任务")
    match = matches[0]
    clean = (reply[: match.start()] + reply[match.end() :]).strip()
    if re.search(r"^[ \t]*<qq-delivery\b", clean, re.MULTILINE):
        raise DeliveryError("回传清单重复")
    try:
        manifest = json.loads(match[1])
    except ValueError as exc:
        raise DeliveryError("回传清单格式无效") from exc
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, list) or len(files) > config.max_attachments:
        raise DeliveryError("回传文件数量无效或超限")
    # 空文件列表等同于没有清单：剥掉标记，按普通文字发送
    if not files:
        return clean, []
    # Compatibility parser for old records; live replies use qq_send_files instead.
    return clean, snapshot_files(
        [
            {k: v for k, v in item.items() if k in {"path", "name"}}
            if isinstance(item, dict)
            else item
            for item in files
        ],
        config,
        job_id,
    )


def snapshot_files(
    files: list[dict],
    config: Config,
    job_id: str,
    *,
    request_id: str | None = None,
    input_job_ids: tuple[str, ...] = (),
    existing: tuple[dict, ...] = (),
) -> list[dict]:
    if not files or len(files) > config.max_attachments:
        raise DeliveryError("回传文件数量无效或超限")
    root = directory(config, job_id)
    incoming = [
        config.workdir.resolve() / ".qq-attachments" / id for id in (job_id, *input_job_ids)
    ]
    selected, seen = [], {(a["name"], a["sha256"], a["kind"]) for a in existing}
    total = sum(a["size"] for a in existing)
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise DeliveryError("回传文件路径无效")
        path = Path(item["path"])
        if not path.is_absolute():
            path = root / path
        name = display_name(item.get("name", path.name))
        allowed_root = next((p for p in incoming if path.resolve().is_relative_to(p)), root)
        data = read_file(path, allowed_root, config.max_attachment_bytes)
        kind = media_kind(data)
        requested = item.get("kind", "auto")
        if requested not in {"auto", "image", "video", "audio", "file"}:
            raise DeliveryError("回传媒体类型无效")
        if requested == "file":
            kind = "file"
        elif requested not in {"auto", kind}:
            raise DeliveryError("回传媒体类型与文件内容不匹配")
        digest = hashlib.sha256(data).hexdigest()
        key = (name, digest, kind)
        if key in seen:
            continue
        total += len(data)
        if (
            total > config.max_attachment_bytes
            or len(existing) + len(selected) >= config.max_attachments
        ):
            raise DeliveryError("本任务回传文件累计数量或大小超限")
        seen.add(key)
        selected.append((name, data, digest, kind))
    if not selected:
        return []
    target = config.state_db.resolve().parent / ".qq-outbound" / job_id
    if request_id is not None:
        if not re.fullmatch(r"[0-9a-f]{64}", request_id):
            raise DeliveryError("交付请求编号无效")
        target = target / request_id
    if target.resolve() != target:
        raise DeliveryError("回传暂存目录无效")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    artifacts = []
    for index, (name, data, digest, kind) in enumerate(selected):
        path = target / f"{index}.bin"
        partial = target / f"{uuid.uuid4().hex}.part"
        try:
            with partial.open("xb") as file:
                os.fchmod(file.fileno(), 0o600)
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)
        artifacts.append(
            {
                "path": str(path),
                "name": name,
                "size": len(data),
                "sha256": digest,
                "kind": kind,
            }
        )
    fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return artifacts


def read_snapshot(payload: dict, config: Config, job_id: str) -> bytes:
    root = config.state_db.resolve().parent / ".qq-outbound" / job_id
    data = read_file(Path(payload["path"]), root, config.max_attachment_bytes)
    if len(data) != payload["size"] or hashlib.sha256(data).hexdigest() != payload["sha256"]:
        raise DeliveryError("回传文件在准备后发生变化")
    return data
