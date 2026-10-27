"""OpenAI Images client and a credential-free CLI for the OpenCode assistant."""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import json
import math
import os
import re
import stat
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp

from .config import Config, ConfigError


class ImageGenerationError(ValueError):
    pass


@dataclass(frozen=True)
class ImageProvider:
    base_url: str
    api_key: str = field(repr=False)


def _setting(value: object, config_file: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ImageGenerationError("生图供应商缺少 baseURL 或 apiKey")
    reference = re.fullmatch(r"\{(env|file):([^{}]+)\}", value)
    if reference:
        kind, source = reference.groups()
        if kind == "env":
            value = os.environ.get(source, "")
        else:
            path = Path(source).expanduser()
            if not path.is_absolute():
                path = config_file.parent / path
            try:
                value = path.read_text().strip()
            except (OSError, UnicodeError):
                raise ImageGenerationError("无法读取生图供应商的配置引用") from None
    if not value.strip() or any(char in value for char in "\r\n"):
        raise ImageGenerationError("生图供应商的配置为空或无效")
    return value.strip()


def load_provider(config_file: Path, provider: str) -> ImageProvider:
    """Read OpenCode v2 settings without exposing them to model/tool output."""
    try:
        config = json.loads(config_file.read_text())
        settings = config["providers"][provider]["settings"]
        base = _setting(settings.get("baseURL"), config_file).rstrip("/")
        key = _setting(settings.get("apiKey"), config_file)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, AttributeError) as exc:
        if isinstance(exc, ImageGenerationError):
            raise
        raise ImageGenerationError("无法读取 OpenCode 生图供应商配置") from None
    try:
        parsed = urlsplit(base)
    except ValueError:
        raise ImageGenerationError("生图供应商 baseURL 无效") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ImageGenerationError("生图供应商 baseURL 无效")
    return ImageProvider(base, key)


async def _read_limited(response: aiohttp.ClientResponse, limit: int) -> bytes:
    data = bytearray()
    async for chunk in response.content.iter_chunked(65536):
        data.extend(chunk)
        if len(data) > limit:
            raise ImageGenerationError("生图响应或图片大小超过本次交付限制")
    return bytes(data)


def _extension(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    raise ImageGenerationError("生图接口返回的内容不是 PNG、JPEG 或 WebP 图片")


def _validate_directory(output_dir: Path) -> None:
    if (
        not output_dir.is_absolute()
        or output_dir.resolve() != output_dir
        or not output_dir.is_dir()
    ):
        raise ImageGenerationError("生图必须使用已准备好的本任务交付目录，且不能是符号链接")


def _save_images(output_dir: Path, images: list[tuple[bytes, str]]) -> list[dict[str, str]]:
    _validate_directory(output_dir)
    created: list[Path] = []
    try:
        for data, extension in images:
            path = output_dir / f"image-{uuid.uuid4().hex}.{extension}"
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created.append(path)
            with os.fdopen(descriptor, "wb") as file:
                file.write(data)
    except OSError:
        for path in created:
            path.unlink(missing_ok=True)
        raise ImageGenerationError("生成图片无法保存到本任务交付目录") from None
    return [{"path": path.name, "name": path.name} for path in created]


def _read_references(
    paths: list[Path],
    input_dir: Path | None,
    output_dir: Path,
    max_files: int,
    max_bytes: int,
) -> list[tuple[bytes, str]]:
    if len(paths) > min(max_files, 16):
        raise ImageGenerationError("参考图数量超过本次附件限制")
    roots = [output_dir] if input_dir is None else [input_dir, output_dir]
    images = []
    remaining = max_bytes
    for path in paths:
        if not path.is_absolute():
            path = (input_dir or output_dir) / path
        try:
            resolved = path.resolve(strict=True)
            root = next((root for root in roots if resolved.is_relative_to(root)), None)
            if root is None or not root.is_absolute() or root.resolve() != root:
                raise ImageGenerationError("参考图不在本任务的附件或交付目录内")
            for part in (path, *path.parents):
                if part == root:
                    break
                if part.is_symlink():
                    raise ImageGenerationError("参考图不能是符号链接")
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as file:
                info = os.fstat(file.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise ImageGenerationError("参考图必须是普通图片文件")
                if info.st_size > remaining:
                    raise ImageGenerationError("参考图总大小超过本次附件限制")
                data = file.read(remaining + 1)
        except OSError:
            raise ImageGenerationError("参考图不存在或无法读取，请重新发送图片") from None
        if len(data) > remaining:
            raise ImageGenerationError("参考图总大小超过本次附件限制")
        try:
            extension = _extension(data)
        except ImageGenerationError:
            raise ImageGenerationError("参考图必须是 PNG、JPEG 或 WebP 图片") from None
        images.append((data, extension))
        remaining -= len(data)
    return images


async def generate(
    http: aiohttp.ClientSession,
    provider: ImageProvider,
    *,
    prompt: str,
    output_dir: Path,
    model: str = "your-image-model",
    size: str = "1024x1024",
    quality: str = "auto",
    count: int = 1,
    max_files: int = 5,
    max_bytes: int = 20 * 1024 * 1024,
    timeout_seconds: float = 600,
    reference_images: list[Path] | None = None,
    input_dir: Path | None = None,
) -> list[dict[str, str]]:
    if not prompt.strip() or len(prompt) > 32000:
        raise ImageGenerationError("生图描述必须为 1 至 32000 个字符")
    if (
        not 1 <= count <= max_files
        or max_bytes <= 0
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ImageGenerationError("生图数量、大小限制或超时设置无效")
    if size not in {"auto", "1024x1024", "1536x1024", "1024x1536"}:
        raise ImageGenerationError("生图尺寸必须为 auto、1024x1024、1536x1024 或 1024x1536")
    if quality not in {"auto", "low", "medium", "high"} or not model.strip():
        raise ImageGenerationError("生图质量或模型设置无效")
    await asyncio.to_thread(_validate_directory, output_dir)
    references = await asyncio.to_thread(
        _read_references, reference_images or [], input_dir, output_dir, max_files, max_bytes
    )
    parameters = {"model": model, "prompt": prompt, "n": count, "size": size, "quality": quality}
    request_body = {"json": parameters}
    endpoint = "/images/generations"
    if references:
        endpoint = "/images/edits"
        form = aiohttp.FormData()
        for key, value in parameters.items():
            form.add_field(key, str(value))
        for index, (data, extension) in enumerate(references):
            form.add_field(
                "image" if len(references) == 1 else "image[]",
                data,
                filename=f"reference-{index + 1}.{extension}",
                content_type="image/jpeg" if extension == "jpg" else f"image/{extension}",
            )
        request_body = {"data": form}
    images: list[tuple[bytes, str]] = []
    try:
        async with asyncio.timeout(timeout_seconds):
            async with http.post(
                provider.base_url + endpoint,
                headers={"Authorization": "Bearer " + provider.api_key},
                **request_body,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=timeout_seconds, sock_connect=30),
            ) as response:
                if response.status != 200:
                    raise ImageGenerationError(f"生图接口调用失败（HTTP {response.status}）")
                body = await _read_limited(response, (max_bytes + 2) // 3 * 4 + 1024 * 1024)
            try:
                payload = json.loads(body)
            except (ValueError, UnicodeError):
                raise ImageGenerationError("生图接口返回了无效 JSON") from None
            items = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(items, list) or len(items) != count:
                raise ImageGenerationError("生图接口返回的图片数量与请求不符")
            remaining = max_bytes
            for item in items:
                if not isinstance(item, dict):
                    raise ImageGenerationError("生图接口返回的图片数据无效")
                encoded, url = item.get("b64_json"), item.get("url")
                if isinstance(encoded, str) and encoded:
                    if len(encoded) > (remaining + 2) // 3 * 4:
                        raise ImageGenerationError("生成图片的总大小超过本次交付限制")
                    try:
                        data = base64.b64decode(encoded, validate=True)
                    except (ValueError, binascii.Error):
                        raise ImageGenerationError("生图接口返回了无效的 base64 图片") from None
                elif isinstance(url, str) and url:
                    parsed = urlsplit(url)
                    if (
                        parsed.scheme not in {"https", "http"}
                        or not parsed.hostname
                        or parsed.username
                        or parsed.password
                        or parsed.fragment
                    ):
                        raise ImageGenerationError("生图接口返回的图片地址无效")
                    # CDN requests never receive the provider's Authorization header.
                    async with http.get(
                        url,
                        allow_redirects=False,
                        timeout=aiohttp.ClientTimeout(total=timeout_seconds, sock_connect=30),
                    ) as response:
                        if response.status != 200:
                            raise ImageGenerationError(
                                f"生成图片下载失败（HTTP {response.status}）"
                            )
                        data = await _read_limited(response, remaining)
                else:
                    raise ImageGenerationError("生图接口没有返回图片数据或图片地址")
                if len(data) > remaining:
                    raise ImageGenerationError("生成图片的总大小超过本次交付限制")
                images.append((data, _extension(data)))
                remaining -= len(data)
    except TimeoutError:
        raise ImageGenerationError("生图请求超时，结果尚未确认；请勿自动重试") from None
    except (aiohttp.ClientError, OSError):
        raise ImageGenerationError("生图连接中断，结果尚未确认；请勿自动重试") from None
    # Validate every image before writing any deliverable.
    return await asyncio.to_thread(_save_images, output_dir, images)


def main(*, workspace: bool = False) -> None:
    parser = argparse.ArgumentParser(description="使用 OpenCode 供应商凭据生成 QQ 交付图片")
    if workspace:
        parser.add_argument(
            "--env-file",
            type=Path,
            default=Path(__file__).resolve().parents[1] / ".env",
            help="桥接配置文件，默认使用本机部署配置；不输出凭据",
        )
    else:
        parser.add_argument("--opencode-config", type=Path, required=True)
        parser.add_argument("--provider", default="custom")
        parser.add_argument("--model", default="your-image-model")
        parser.add_argument("--max-files", type=int, default=5)
        parser.add_argument("--max-bytes", type=int, default=20 * 1024 * 1024)
        parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument(
        "--image", type=Path, action="append", default=[], help="参考图，可重复指定"
    )
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--quality", default="auto")
    parser.add_argument("--count", type=int, default=1)
    args = parser.parse_args()

    async def run() -> list[dict[str, str]]:
        if workspace:
            config = await asyncio.to_thread(Config.from_env, args.env_file)
            if not config.image_generation_enabled:
                raise ImageGenerationError("当前未启用生图能力")
            args.opencode_config = config.image_opencode_config
            args.provider, args.model = config.image_provider, config.image_model
            args.max_files, args.max_bytes = config.max_attachments, config.max_attachment_bytes
            args.timeout = min(config.image_timeout, config.execution_timeout)
        provider = await asyncio.to_thread(load_provider, args.opencode_config, args.provider)
        async with aiohttp.ClientSession() as http:
            return await generate(
                http,
                provider,
                prompt=args.prompt,
                output_dir=args.output_dir,
                model=args.model,
                size=args.size,
                quality=args.quality,
                count=args.count,
                max_files=args.max_files,
                max_bytes=args.max_bytes,
                timeout_seconds=args.timeout,
                reference_images=args.image,
                input_dir=args.input_dir,
            )

    try:
        files = asyncio.run(run())
    except (ImageGenerationError, ConfigError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps({"files": files}, ensure_ascii=False))


if __name__ == "__main__":
    main()
