"""Prepare a fresh deployment without starting services or overwriting private files."""

from __future__ import annotations

import argparse
import os
import pwd
import secrets
import shlex
import shutil
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def private_write(path: Path, content: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(content)


def prepare(workdir: Path) -> None:
    workdir = workdir.expanduser().resolve()
    if workdir == ROOT or ROOT in workdir.parents or workdir in ROOT.parents:
        raise ValueError("OpenCode 工作目录必须与源码仓库分开，且不能相互包含")
    if any(char in str(workdir) + str(ROOT) for char in '\n\r"\\%'):
        raise ValueError("部署路径不能包含换行、双引号、反斜杠或百分号")
    env_path = ROOT / ".env"
    if env_path.exists():
        configured = dotenv_values(env_path).get("OPENCODE_WORKDIR")
        if not configured or Path(configured).expanduser().resolve() != workdir:
            raise ValueError("已有 .env 的工作目录不同；请使用相同 --workdir 或手工迁移")
    for directory in (workdir, workdir / "tools", ROOT / "data"):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    compose_env = ROOT / "deploy/compose.env"
    if not compose_env.exists():
        private_write(
            compose_env,
            f"NAPCAT_WEBUI_TOKEN={secrets.token_hex(24)}\n"
            f"QQ_POSTGRES_PASSWORD={secrets.token_hex(32)}\n"
            "QQ_POSTGRES_PORT=55432\n",
        )
    compose = dotenv_values(compose_env)
    if not env_path.exists():
        values = {
            "NAPCAT_TOKEN": secrets.token_hex(24),
            "OPENCODE_WORKDIR": str(workdir),
            "OPENCODE_SERVICE_FILE": str(Path.home() / ".local/state/opencode/service.json"),
            "OPENCODE_BINARY": shutil.which("opencode") or "opencode",
            "IMAGE_OPENCODE_CONFIG": str(Path.home() / ".config/opencode/opencode.json"),
            "STATE_DB": str(ROOT / "data/bridge.sqlite3"),
            "MEMORY_DB": str(ROOT / "data/memory.sqlite3"),
            "MEMORY_DATABASE_URL": (
                f"postgresql://qqbridge:{compose['QQ_POSTGRES_PASSWORD']}@127.0.0.1:"
                f"{compose.get('QQ_POSTGRES_PORT', '55432')}/qqbridge?connect_timeout=5"
            ),
        }
        lines = []
        for line in (ROOT / ".env.example").read_text().splitlines():
            key = line.partition("=")[0]
            lines.append(f"{key}={shlex.quote(values[key])}" if key in values else line)
        private_write(env_path, "\n".join(lines) + "\n")
    persona = workdir / "AGENTS.md"
    if not persona.exists():
        private_write(persona, (ROOT / "deploy/qq-persona.md").read_text())
    script = workdir / "tools/imagegen.py"
    if not script.exists():
        private_write(script, (ROOT / "deploy/workspace-tools/imagegen.py").read_text())
    interpreter = workdir / "tools/bridge-python"
    if not interpreter.exists() and not interpreter.is_symlink():
        interpreter.symlink_to(ROOT / ".venv/bin/python")
    unit = ROOT / "deploy/qqbot.local.service"
    if not unit.exists():
        content = (ROOT / "deploy/qqbot.service").read_text()
        replacements = {
            "@PROJECT_DIR@": str(ROOT),
            "@RUN_USER@": pwd.getpwuid(os.getuid()).pw_name,
            "@EXEC_PATH@": os.pathsep.join(
                dict.fromkeys(
                    [
                        str(Path(shutil.which("opencode") or "/usr/local/bin/opencode").parent),
                        str(Path(shutil.which("node") or "/usr/bin/node").parent),
                        "/usr/local/bin",
                        "/usr/bin",
                        "/bin",
                    ]
                )
            ),
        }
        for key, value in replacements.items():
            content = content.replace(key, value)
        private_write(unit, content)
    print("部署文件已准备；已有配置、AGENTS.md 和工具文件保持原样。未启动服务，未输出凭据。")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, default=Path.home() / "qq-agent-workspace")
    args = parser.parse_args()
    prepare(args.workdir)


if __name__ == "__main__":
    main()
