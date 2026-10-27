import asyncio
import base64
import json
import os
import sys
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web
from conftest import eventually, message, start_server

from qqbot.config import Config, ConfigError
from qqbot.delivery import DELIVERY_ENTRY_KEY
from qqbot.imagegen import ImageGenerationError, ImageProvider, generate, load_provider
from qqbot.models import Context

IMAGE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aTnQAAAAASUVORK5CYII="
)
SECRET = "image-test-key"
SCRIPT = Path(__file__).resolve().parents[1] / "deploy/workspace-tools/imagegen.py"


async def test_workspace_image_tool_checks_enabled_before_reading_provider(tmp_path):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(SCRIPT),
        "--env-file",
        str(tmp_path / "missing.env"),
        "--output-dir",
        str(tmp_path),
        "--prompt",
        "画一只猫",
        env={
            "PATH": os.defpath,
            "PYTHONPATH": str(SCRIPT.parents[2]),
            "NAPCAT_TOKEN": "test",
            "ALLOWED_USERS": "11",
        },
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), 3)
    assert process.returncode == 1 and not stdout
    assert json.loads(stderr) == {"error": "当前未启用生图能力"}
    assert list(tmp_path.iterdir()) == []


def provider_config(tmp_path, base_url, key=SECRET):
    path = tmp_path / "opencode.json"
    path.write_text(
        json.dumps({"providers": {"custom": {"settings": {"baseURL": base_url, "apiKey": key}}}})
    )
    return path


@pytest.mark.parametrize("reference", ["literal", "env", "file"])
def test_reuse_opencode_v2_provider_credentials_without_exposing_key(
    tmp_path, monkeypatch, reference
):
    value = SECRET
    if reference == "env":
        value = "{env:IMAGE_TEST_SECRET}"
        monkeypatch.setenv("IMAGE_TEST_SECRET", SECRET)
    elif reference == "file":
        value = "{file:secret.txt}"
        (tmp_path / "secret.txt").write_text(SECRET + "\n")
    path = provider_config(tmp_path, "https://api.example.test/v1/", value)
    provider = load_provider(path, "custom")
    assert provider.base_url == "https://api.example.test/v1"
    assert provider.api_key == SECRET
    assert SECRET not in repr(provider)


@pytest.mark.parametrize("kind", ["missing", "invalid_json", "no_provider", "empty_key", "bad_url"])
def test_invalid_provider_config_fails_without_credential_disclosure(tmp_path, kind):
    path = provider_config(tmp_path, "https://api.example.test/v1")
    if kind == "missing":
        path.unlink()
    elif kind == "invalid_json":
        path.write_text(SECRET)
    elif kind == "no_provider":
        path.write_text('{"providers":{}}')
    elif kind == "empty_key":
        provider_config(tmp_path, "https://api.example.test/v1", "")
    else:
        provider_config(tmp_path, "https://user:password@example.test/v1")
    with pytest.raises(ImageGenerationError) as error:
        load_provider(path, "custom")
    assert SECRET not in str(error.value)
    assert "password" not in str(error.value)


@pytest.mark.parametrize("result_format", ["b64_json", "url"])
async def test_openai_images_request_and_compatible_response_formats(tmp_path, result_format):
    requests = []

    async def handle(request):
        requests.append(request.path)
        if request.path == "/generated.png":
            assert "Authorization" not in request.headers
            return web.Response(body=IMAGE)
        assert request.path == "/v1/images/generations"
        assert request.headers["Authorization"] == "Bearer " + SECRET
        assert await request.json() == {
            "model": "your-image-model",
            "prompt": "一只猫，图片上写着“你好”",
            "size": "1024x1536",
            "quality": "auto",
            "n": 1,
        }
        item = (
            {"b64_json": base64.b64encode(IMAGE).decode()}
            if result_format == "b64_json"
            else {"url": url + "/generated.png"}
        )
        return web.json_response({"data": [item]})

    runner, url = await start_server(handle)
    try:
        provider = load_provider(provider_config(tmp_path, url + "/v1"), "custom")
        async with aiohttp.ClientSession() as http:
            files = await generate(
                http,
                provider,
                prompt="一只猫，图片上写着“你好”",
                output_dir=tmp_path,
                size="1024x1536",
            )
        path = tmp_path / files[0]["path"]
        assert path.read_bytes() == IMAGE
        assert path.stat().st_mode & 0o777 == 0o600
        assert files[0]["name"].endswith(".png")
        assert requests.count("/v1/images/generations") == 1
    finally:
        await runner.cleanup()


@pytest.mark.parametrize(
    "fault", ["http", "timeout", "invalid_json", "invalid_b64", "not_image", "oversize", "count"]
)
async def test_errors_do_not_retry_or_leave_deliverables(tmp_path, fault):
    calls = 0

    async def handle(request):
        nonlocal calls
        calls += 1
        if fault == "http":
            return web.Response(status=401, text=SECRET)
        if fault == "timeout":
            await asyncio.sleep(0.1)
        if fault == "invalid_json":
            return web.Response(text="not json " + SECRET)
        encoded = base64.b64encode(IMAGE).decode()
        if fault == "invalid_b64":
            encoded = "%%%%"
        elif fault == "not_image":
            encoded = base64.b64encode(b"not an image").decode()
        return web.json_response({"data": [] if fault == "count" else [{"b64_json": encoded}]})

    runner, url = await start_server(handle)
    try:
        async with aiohttp.ClientSession() as http:
            with pytest.raises(ImageGenerationError) as error:
                await generate(
                    http,
                    ImageProvider(url, SECRET),
                    prompt="画一只猫",
                    output_dir=tmp_path,
                    max_bytes=8 if fault == "oversize" else 1024,
                    timeout_seconds=0.03 if fault == "timeout" else 5,
                )
        assert SECRET not in str(error.value)
        assert list(tmp_path.iterdir()) == []
        assert calls == 1
    finally:
        await runner.cleanup()


async def test_invalid_second_image_does_not_save_first_image(tmp_path):
    async def handle(request):
        return web.json_response(
            {"data": [{"b64_json": base64.b64encode(IMAGE).decode()}, {"b64_json": "bad"}]}
        )

    runner, url = await start_server(handle)
    try:
        async with aiohttp.ClientSession() as http:
            with pytest.raises(ImageGenerationError):
                await generate(
                    http, ImageProvider(url, SECRET), prompt="两只猫", output_dir=tmp_path, count=2
                )
        assert list(tmp_path.iterdir()) == []
    finally:
        await runner.cleanup()


async def test_symlink_output_directory_is_rejected_before_api_call(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    async with aiohttp.ClientSession() as http:
        with pytest.raises(ImageGenerationError, match="符号链接"):
            await generate(
                http, ImageProvider("http://127.0.0.1:1", SECRET), prompt="猫", output_dir=link
            )


@pytest.mark.parametrize("group", [None, 22])
@pytest.mark.parametrize("source", ["text", "attached", "quoted", "multiple"])
async def test_assistant_command_generates_and_returns_picture_to_original_qq(
    harness, tmp_path, group, source
):
    expected = [] if source == "text" else [IMAGE]
    if source == "multiple":
        expected.append(b"\xff\xd8\xffsecond-image")
    calls = []

    async def handle(request):
        calls.append(request.path)
        assert request.path == ("/v1/images/edits" if expected else "/v1/images/generations")
        assert request.headers["Authorization"] == "Bearer " + SECRET
        if expected:
            reader = await request.multipart()
            received, parameters, content_types = [], {}, []
            while part := await reader.next():
                if part.filename:
                    assert part.name == ("image" if len(expected) == 1 else "image[]")
                    received.append(bytes(await part.read()))
                    content_types.append(part.headers["Content-Type"])
                else:
                    parameters[part.name] = await part.text()
            assert received == expected
            assert content_types == ["image/png"] + (["image/jpeg"] if len(expected) == 2 else [])
            assert parameters["model"] == "your-image-model"
            assert parameters["n"] == "1"
            assert parameters["prompt"] == "给参考图加红色蝴蝶结"
        else:
            assert (await request.json())["prompt"] == "帮我画一只猫"
        return web.json_response({"data": [{"b64_json": base64.b64encode(IMAGE).decode()}]})

    runner, url = await start_server(handle)
    path = provider_config(tmp_path, url + "/v1")
    try:
        async with harness(image_generation_enabled=True, image_opencode_config=path) as (
            bridge,
            nap,
            op,
        ):
            op.mode = "stalled"
            nap.files = {f"reference-{index}": data for index, data in enumerate(expected)}
            attachments = [
                {"type": "image", "data": {"file_id": key, "name": key + ".png"}}
                for key in nap.files
            ]
            prompt = "给参考图加红色蝴蝶结" if expected else "帮我画一只猫"
            if source == "quoted":
                await nap.emit(message(group=group, mid=101, attachments=attachments))
                await nap.emit(message(prompt, group=group, at=group is not None, reply=101))
            else:
                await nap.emit(
                    message(prompt, group=group, at=group is not None, attachments=attachments)
                )
            await eventually(lambda: bool(op.prompts))
            sid = op.prompts[0]["sessionID"]
            assert DELIVERY_ENTRY_KEY not in op.instructions[sid]
            context = await bridge.delivery_tools.context(sid)
            command = [
                sys.executable,
                str(SCRIPT),
                "--env-file",
                str(tmp_path / "missing.env"),
                "--output-dir",
                context["output_dir"],
                "--input-dir",
                context["input_dir"],
            ]
            job = bridge.store.latest(Context(777, 11, group))
            inputs = json.loads(job["files"])
            assert len(inputs) == len(expected)
            for reference in inputs:
                command.extend(["--image", reference])
            # Execute the actual CLI given to the assistant, with no secret in its argv.
            process = await asyncio.create_subprocess_exec(
                *command,
                "--prompt",
                prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={
                    "PATH": os.defpath,
                    "PYTHONPATH": str(SCRIPT.parents[2]),
                    "NAPCAT_TOKEN": "test",
                    "ALLOWED_USERS": "11",
                    "IMAGE_GENERATION_ENABLED": "true",
                    "IMAGE_OPENCODE_CONFIG": str(path),
                },
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), 3)
            assert process.returncode == 0, stderr.decode()
            assert SECRET.encode() not in stdout + stderr
            manifest = json.loads(stdout)
            result = await bridge.delivery_tools.submit(sid, "generated-image", manifest)
            assert result["status"] == "queued"
            op.finish(sid, "画好啦")
            await eventually(lambda: bridge.store.job(job["id"])["status"] == "done")
            assert len(nap.media_sent) == 1
            media = nap.media_sent[0]
            assert media["bytes"] == IMAGE
            assert media["kind"] == "image"
            assert media["user_id" if group is None else "group_id"] == (
                "11" if group is None else "22"
            )
            assert not any("qq-delivery" in text or SECRET in text for text in nap.texts())
            assert nap.sent[-1]["message"][-1] == {"type": "text", "data": {"text": "画好啦"}}
            # Enabling image generation does not broaden permissions for ordinary users.
            assert op.sessions[sid]["permissions"][0]["effect"] == "ask"
            assert calls == ["/v1/images/edits" if expected else "/v1/images/generations"]
    finally:
        await runner.cleanup()


@pytest.mark.parametrize(
    "fault",
    ["outside", "other_job", "symlink", "parent_symlink", "missing", "gif", "size", "count"],
)
async def test_invalid_reference_is_rejected_without_uploading_or_falling_back(tmp_path, fault):
    output = tmp_path / "output"
    output.mkdir()
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    reference = inputs / "reference.png"
    reference.write_bytes(IMAGE)
    images, limit, max_files = [reference], 1024, 5
    if fault in {"outside", "other_job"}:
        reference = tmp_path / "another-job" / "private.png"
        reference.parent.mkdir()
        reference.write_bytes(IMAGE)
        images = [reference] if fault == "outside" else [inputs / "../another-job/private.png"]
    elif fault == "symlink":
        link = inputs / "alias.png"
        link.symlink_to(reference)
        images = [link]
    elif fault == "parent_symlink":
        link = inputs / "alias"
        link.symlink_to(inputs, target_is_directory=True)
        images = [link / "reference.png"]
    elif fault == "missing":
        reference.unlink()
    elif fault == "gif":
        reference.write_bytes(b"GIF89a unsupported reference")
    elif fault == "size":
        limit = len(IMAGE) - 1
    elif fault == "count":
        images = [reference, reference]
        max_files = 1
    async with aiohttp.ClientSession() as http:
        with pytest.raises(ImageGenerationError, match="参考图"):
            await generate(
                http,
                ImageProvider("http://127.0.0.1:1", SECRET),
                prompt="参考图片生成头像",
                output_dir=output,
                reference_images=images,
                input_dir=inputs,
                max_bytes=limit,
                max_files=max_files,
            )
    assert list(output.iterdir()) == []


@pytest.mark.parametrize("fault", ["http", "timeout", "no_images"])
async def test_edit_failure_never_retries_or_silently_generates_without_reference(tmp_path, fault):
    calls = []
    output = tmp_path / "output"
    output.mkdir()
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    reference = inputs / "reference.png"
    reference.write_bytes(IMAGE)

    async def handle(request):
        calls.append(request.path)
        if fault == "http":
            return web.Response(status=400, text=SECRET)
        if fault == "timeout":
            await asyncio.sleep(0.1)
        return web.json_response({"data": []})

    runner, url = await start_server(handle)
    try:
        async with aiohttp.ClientSession() as http:
            with pytest.raises(ImageGenerationError) as error:
                await generate(
                    http,
                    ImageProvider(url, SECRET),
                    prompt="修改原图",
                    output_dir=output,
                    reference_images=[reference],
                    input_dir=inputs,
                    timeout_seconds=0.03 if fault == "timeout" else 5,
                )
        assert calls == ["/images/edits"]
        assert list(output.iterdir()) == []
        assert SECRET not in str(error.value)
    finally:
        await runner.cleanup()


async def test_edit_can_reuse_this_tasks_output_image_without_an_input_directory(tmp_path):
    reference = tmp_path / "previous.png"
    reference.write_bytes(IMAGE)

    async def handle(request):
        assert request.path == "/images/edits"
        reader = await request.multipart()
        while part := await reader.next():
            if part.name == "image":
                assert bytes(await part.read()) == IMAGE
        return web.json_response({"data": [{"b64_json": base64.b64encode(IMAGE).decode()}]})

    runner, url = await start_server(handle)
    try:
        async with aiohttp.ClientSession() as http:
            files = await generate(
                http,
                ImageProvider(url, SECRET),
                prompt="继续修改这张图",
                output_dir=tmp_path,
                reference_images=[reference],
            )
        assert reference.read_bytes() == IMAGE
        assert (tmp_path / files[0]["path"]).read_bytes() == IMAGE
    finally:
        await runner.cleanup()


def test_image_environment_configuration(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLOWED_USERS", "11")
    monkeypatch.setenv("NAPCAT_TOKEN", "test")
    monkeypatch.setenv("IMAGE_GENERATION_ENABLED", "true")
    monkeypatch.setenv("IMAGE_OPENCODE_CONFIG", str(tmp_path / "opencode.json"))
    cfg = Config.from_env(tmp_path / "missing.env")
    assert cfg.image_generation_enabled
    assert cfg.image_provider == "custom"
    assert cfg.image_model == "your-image-model"
    monkeypatch.setenv("IMAGE_GENERATION_ENABLED", "invalid")
    with pytest.raises(ConfigError, match="IMAGE_GENERATION_ENABLED"):
        Config.from_env(tmp_path / "missing.env")
