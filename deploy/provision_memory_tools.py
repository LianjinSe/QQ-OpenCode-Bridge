"""Register the native memory plugin without changing providers or credentials."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qqbot.config import Config  # noqa: E402


def install(config):
    plugin = str(Path(__file__).resolve().parent / "opencode-memory")
    path = config.workdir / "opencode.json"
    if not config.memory_enabled:
        raise ValueError("需要先启用现有个人记忆配置")
    if not path.exists() and path.with_suffix(".jsonc").exists():
        raise ValueError("已有 JSONC 配置，请将记忆插件合并到该文件，不另建覆盖文件")
    data = json.loads(path.read_text()) if path.exists() else {}
    entry = {
        "package": plugin,
        "options": {
            "socketPath": str(config.memory_db.with_name("memory-tools.sock")),
            "tokenPath": str(config.memory_db.with_name("memory-tools.token")),
        },
    }
    plugins = data.setdefault("plugins", [])
    index = next(
        (
            i
            for i, value in enumerate(plugins)
            if (value.get("package") if isinstance(value, dict) else value) == plugin
        ),
        None,
    )
    if index is None:
        plugins.append(entry)
    else:
        plugins[index] = entry
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".opencode-memory-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print("已注册助手记忆工具插件：" + str(path))


if __name__ == "__main__":
    install(Config.from_env())
