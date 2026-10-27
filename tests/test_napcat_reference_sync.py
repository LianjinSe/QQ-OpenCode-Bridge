"""Run maintenance synchronization against isolated metadata and storage, without QQ or models."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("import_knowledge", [False, True])
def test_sync_stages_runtime_schema_and_uses_current_knowledge_constructor(
    tmp_path, import_knowledge
):
    project = tmp_path / "project"
    (project / "deploy").mkdir(parents=True)
    script = project / "deploy/sync_napcat_reference.py"
    shutil.copyfile(ROOT / "deploy/sync_napcat_reference.py", script)
    runtime = tmp_path / "runtime.json"
    runtime.write_text(
        json.dumps(
            {
                "version": "9.9.9",
                "source": "isolated schema fixture",
                "actions": {"get_status": {"description": "本机状态", "tags": ["系统接口"]}},
            }
        )
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "1e0.md").write_text("""# Test
```yaml
openapi: 3.0.1
paths:
  /get_status:
    post:
      summary: public-status
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                future_field: {type: string}
  /future_only:
    post:
      summary: future-only
```
""")
    env = os.environ.copy()
    env.update(
        PYTHONPATH=str(ROOT),
        NAPCAT_TOKEN="fixture",
        ALLOWED_USERS="11",
        SUPERADMIN_USER_ID="11",
        MEMORY_ENABLED="false",
        KNOWLEDGE_ENABLED="true",
        NAPCAT_TOOLS_ENABLED="false",
        SILICONFLOW_API_KEY="fixture",
        MEMORY_DATABASE_URL="postgresql://test:test@127.0.0.1:1/test",
        STATE_DB=str(tmp_path / "state.sqlite3"),
        MEMORY_DB=str(tmp_path / "memory.sqlite3"),
        OPENCODE_WORKDIR=str(tmp_path / "workspace"),
    )
    executable = tmp_path / "bin"
    executable.mkdir()
    systemctl = executable / "systemctl"
    systemctl.write_text("#!/bin/sh\nexit 3\n")
    systemctl.chmod(0o700)
    env["PATH"] = str(executable) + os.pathsep + env["PATH"]
    args = [
        sys.executable,
        str(script),
        "--runtime-catalogue",
        str(runtime),
        "--docs-dir",
        str(cache),
    ]
    if import_knowledge:
        args.append("--import-knowledge")
        output = project
    else:
        output = tmp_path / "preview"
        args.extend(["--output-root", str(output)])
    result = subprocess.run(args, cwd=project, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    catalogue = json.loads((output / "qqbot/napcat_catalogue.json").read_text())
    assert catalogue["version"] == "9.9.9"
    assert catalogue["actions"]["get_status"]["available"] is True
    assert catalogue["actions"]["get_status"]["payload"] == {"type": "object", "properties": {}}
    assert catalogue["actions"]["future_only"]["available"] is False
    assert catalogue["actions"]["get_status"]["description"] == "本机状态"
    if import_knowledge:
        with sqlite3.connect(tmp_path / "knowledge/catalogue.sqlite3") as db:
            assert (
                db.execute("select count(*) from versions where state='queued'").fetchone()[0] == 4
            )
    else:
        assert not (project / "qqbot/napcat_catalogue.json").exists()
        assert not (tmp_path / "knowledge/catalogue.sqlite3").exists()
