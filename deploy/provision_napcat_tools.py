"""Merge the NapCat capability plugin into this bot's workspace without replacing other plugins."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qqbot.config import Config  # noqa: E402


def install(config):
    if not config.napcat_tools_enabled:
        raise ValueError("需要先启用 NAPCAT_TOOLS_ENABLED")
    plugin = str(Path(__file__).resolve().parent / "opencode-napcat")
    path = config.workdir / "opencode.json"
    if not path.exists() and path.with_suffix(".jsonc").exists():
        raise ValueError("已有 JSONC 配置，请将知识插件合并到该文件，不另建覆盖文件")
    data = json.loads(path.read_text()) if path.exists() else {}
    root = config.state_db.parent / "napcat-tools"
    entry = {
        "package": plugin,
        "options": {"socketPath": str(root / "tools.sock"), "tokenPath": str(root / "tools.token")},
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
    fd, temporary = tempfile.mkstemp(prefix=".opencode-napcat-", dir=path.parent)
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
    print("已注册 NapCat 原生能力工具插件，保留原有供应商及插件配置")


if __name__ == "__main__":
    install(Config.from_env())
