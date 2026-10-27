from __future__ import annotations

import importlib.util
import shutil
import stat
from pathlib import Path

import pytest
from dotenv import dotenv_values

from qqbot.config import Config
from qqbot.models import Context
from qqbot.policy import memory_path_protected, memory_read_denials

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def installer(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("deployment_setup", ROOT / "deploy/configure.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    project = tmp_path / "arbitrary checkout"
    (project / "deploy/workspace-tools").mkdir(parents=True)
    for name in (
        ".env.example",
        "deploy/qq-persona.md",
        "deploy/qqbot.service",
        "deploy/workspace-tools/imagegen.py",
    ):
        shutil.copyfile(ROOT / name, project / name)
    monkeypatch.setattr(module, "ROOT", project)
    return module, project


def test_new_checkout_prepares_private_paths_and_separate_runtime_instructions(installer, tmp_path):
    module, project = installer
    workdir = tmp_path / "separate agent workspace"
    module.prepare(workdir)
    env = dotenv_values(project / ".env")
    assert env["OPENCODE_WORKDIR"] == str(workdir)
    assert env["STATE_DB"] == str(project / "data/bridge.sqlite3")
    assert env["MEMORY_DB"] == str(project / "data/memory.sqlite3")
    compose = dotenv_values(project / "deploy/compose.env")
    assert compose["QQ_POSTGRES_PASSWORD"] in env["MEMORY_DATABASE_URL"]
    assert compose["NAPCAT_WEBUI_TOKEN"] != env["NAPCAT_TOKEN"]
    for path in (project / ".env", project / "deploy/compose.env", workdir / "AGENTS.md"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert (workdir / "AGENTS.md").read_text() == (project / "deploy/qq-persona.md").read_text()
    assert (workdir / "tools/bridge-python").readlink() == project / ".venv/bin/python"
    unit = (project / "deploy/qqbot.local.service").read_text()
    assert "@PROJECT_DIR@" not in unit
    assert f'WorkingDirectory="{project}"' in unit
    assert f'ExecStart="{project}/.venv/bin/python" -m qqbot' in unit


def test_rerun_preserves_credentials_and_custom_persona(installer, tmp_path):
    module, project = installer
    workdir = tmp_path / "workspace"
    module.prepare(workdir)
    (workdir / "AGENTS.md").write_text("自定义部署人格，保留工具规则")
    before = {
        path: path.read_bytes()
        for path in (
            project / ".env",
            project / "deploy/compose.env",
            workdir / "AGENTS.md",
        )
    }
    module.prepare(workdir)
    assert all(path.read_bytes() == content for path, content in before.items())
    with pytest.raises(ValueError, match="已有 .env"):
        module.prepare(tmp_path / "different-workspace")


@pytest.mark.parametrize("layout", ("same", "inside", "parent"))
def test_workspace_must_not_overlap_source_or_expose_it_as_context(installer, layout):
    module, project = installer
    directory = {"same": project, "inside": project / "workspace", "parent": project.parent}[layout]
    with pytest.raises(ValueError, match="源码仓库"):
        module.prepare(directory)
    assert not (project / ".env").exists()


def test_permission_denials_follow_actual_environment_file_after_relocation(tmp_path):
    config = Config(
        napcat_url="ws://localhost:1",
        napcat_token="synthetic-test-token",
        allowed_users=frozenset({11}),
        env_file=tmp_path / "configuration/bridge.env",
        state_db=tmp_path / "state/bridge.sqlite3",
        memory_db=tmp_path / "state/memory.sqlite3",
        workdir=tmp_path / "workspace",
    )
    assert memory_path_protected(config, str(config.env_file))
    rules = memory_read_denials(config, Context(777, 11, None))
    assert any(rule["resource"] == str(config.env_file) for rule in rules)
