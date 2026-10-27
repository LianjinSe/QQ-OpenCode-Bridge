from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

from qqbot.bridge import Bridge
from qqbot.config import Config
from qqbot.knowledge import Knowledge, KnowledgeError
from qqbot.knowledge_backend import KnowledgeBackend
from qqbot.knowledge_parse import parse
from qqbot.models import Context
from qqbot.store import Store


class Index:
    def __init__(self):
        self.rows = {}
        self.calls = []
        self.failure = False
        self.on_search = None

    async def replace(self, version_id, chunks):
        if self.failure:
            raise RuntimeError("index unavailable")
        self.rows[version_id] = [dict(c) for c in chunks]

    async def search(self, query, versions):
        self.calls.append(list(versions))
        if self.on_search:
            self.on_search()
        if self.failure:
            raise RuntimeError("index unavailable")
        # Deliberately return out-of-scope IDs too: policy must recheck actual rows.
        return [c["id"] for rows in self.rows.values() for c in rows]

    async def delete(self, version_id):
        if self.failure:
            raise RuntimeError("delete unavailable")
        self.rows.pop(version_id, None)

    async def rerank(self, query, rows):
        return rows[:5]

    async def close(self):
        pass


@pytest.fixture
async def knowledge(tmp_path):
    config = Config(
        napcat_url="ws://localhost:1",
        napcat_token="test",
        allowed_users=frozenset({11, 12}),
        allowed_groups=frozenset({22, 33}),
        superadmin_user_id=11,
        knowledge_enabled=True,
        workdir=tmp_path / "workspace",
        state_db=tmp_path / "bridge.sqlite3",
        memory_db=tmp_path / "memory.sqlite3",
        webui_enabled=True,
    )
    store = Store(config.state_db)
    opencode = SimpleNamespace(belongs_to=AsyncMock(return_value=False), available=True)
    bridge = Bridge(config, store, SimpleNamespace(self_id=777, online=True), opencode)
    kb = bridge.knowledge
    await kb.backend.close()
    kb.backend = Index()
    # Test-only access to the owning context dependencies; Knowledge itself keeps no Bridge.
    kb.bridge_store = store
    kb.opencode = opencode
    kb.webui = bridge.webui
    kb.webui.knowledge = kb
    kb.webui.data.knowledge = kb
    try:
        yield kb
    finally:
        await bridge.memory.close()
        await bridge.knowledge.close()
        store.close()


def library(kb, groups=()):
    return kb.save_library(
        {"name": "部署资料", "description": "项目部署手册", "groups": list(groups)}
    )


async def indexed(kb, lib, text="# 部署\n更新配置后重启 qqbot.service。", name="guide.md"):
    result = await kb.upload(lib["id"], name, text.encode())
    vid = result["document"]["target_version"]
    await kb.process(kb.store.version(vid))
    return kb.store.document(result["document"]["id"])


def job(kb, *, user=11, group=None):
    context = Context(777, user, group)
    id = kb.bridge_store.enqueue(context, "查询部署手册", [], config=kb.config)
    kb.bridge_store.db.execute(
        "UPDATE jobs SET session_id=?,status='running' WHERE id=?", ("ses_" + id, id)
    )
    kb.bridge_store.db.commit()
    return kb.bridge_store.job(id)


async def test_private_scope_and_explicit_group_scope(knowledge):
    kb = knowledge
    private, shared = library(kb), library(kb, [22])
    a = await indexed(kb, private, "私人的日记和资料")
    b = await indexed(kb, shared, "授权群内的部署说明")
    owner = await kb.search("资料", context=Context(777, 11))
    assert len(owner["items"]) == 2
    outsider = await kb.search("资料", context=Context(777, 12))
    assert outsider["items"] == []
    group = await kb.search("说明", context=Context(777, 12, 22))
    assert [r["version_id"] for r in group["items"]] == [b["active_version"]]
    assert kb.backend.calls[-1] == [b["active_version"]]
    assert a["active_version"] not in kb.backend.calls[-1]
    assert (await kb.search("说明", context=Context(777, 11, 33)))["items"] == []
    # Even the owner cannot automatically use private libraries in a group.
    assert len((await kb.search("说明", context=Context(777, 11, 22)))["items"]) == 1


async def test_chinese_keyword_fallback_and_source_metadata(knowledge):
    kb = knowledge
    lib = library(kb)
    await indexed(kb, lib)
    kb.backend.failure = True
    r = await kb.search("qqbot.service", context=Context(777, 11))
    assert r["mode"].startswith("keyword_only")
    assert "qqbot.service" in r["items"][0]["text"]
    assert r["items"][0]["heading"] == "部署"
    assert r["items"][0]["citation"] == "《guide.md》第 1 版 · 部署"
    assert "#/knowledge?document=" in r["items"][0]["url"]


async def test_version_switch_is_atomic_and_duplicate_upload_is_idempotent(knowledge):
    kb = knowledge
    lib = library(kb)
    old = await indexed(kb, lib)
    old_chunk = (await kb.search("重启"))["items"][0]["id"]
    duplicate = await kb.upload(
        lib["id"], "guide.md", "# 部署\n更新配置后重启 qqbot.service。".encode()
    )
    assert duplicate["duplicate"]
    assert len(list((kb.root / "raw").iterdir())) == 1
    update = await kb.upload(lib["id"], "guide.md", "新版本：先备份再重启。".encode())
    pending = update["document"]
    assert pending["active_version"] == old["active_version"]
    assert kb.store.chunk(old_chunk, kb.allowed())
    kb.backend.failure = True
    with pytest.raises(RuntimeError):
        await kb.process(kb.store.version(pending["target_version"]))
    assert kb.store.document(old["id"])["active_version"] == old["active_version"]
    kb.backend.failure = False
    await kb.process(kb.store.version(pending["target_version"]))
    current = kb.store.document(old["id"])
    assert current["active_version"] == pending["target_version"]
    assert kb.store.chunk(old_chunk, kb.allowed()) is None
    await kb.process(kb.store.version(old["active_version"]))
    assert not kb.file(kb.store.version(old["active_version"])).exists()
    assert "新版本" in (await kb.search("备份"))["items"][0]["text"]


async def test_deleted_document_disappears_before_vector_cleanup(knowledge):
    kb = knowledge
    lib = library(kb)
    d = await indexed(kb, lib)
    kb.store.delete_document(d["id"])
    assert (await kb.search("部署"))["items"] == []
    assert d["active_version"] in kb.backend.rows
    with pytest.raises(KeyError):
        kb.preview(d["id"])
    await kb.process(kb.store.version(d["active_version"]))
    assert kb.backend.rows == {}
    assert not list((kb.root / "raw").iterdir())


async def test_permission_revoked_while_searching_drops_results(knowledge):
    kb = knowledge
    lib = library(kb, [22])
    await indexed(kb, lib)
    kb.backend.on_search = lambda: kb.save_library({"name": "部署", "groups": []}, id=lib["id"])
    assert (await kb.search("部署", context=Context(777, 12, 22)))["items"] == []


async def test_replaced_or_deleted_during_search_drops_old_chunks(knowledge):
    kb = knowledge
    lib = library(kb)
    d = await indexed(kb, lib)
    kb.backend.on_search = lambda: kb.store.delete_document(d["id"])
    assert (await kb.search("部署", context=Context(777, 11)))["items"] == []


async def test_superseded_pending_version_cannot_publish(knowledge):
    kb = knowledge
    lib = library(kb)
    old = await kb.upload(lib["id"], "guide.md", b"old")
    new = await kb.upload(lib["id"], "guide.md", b"new")
    await kb.process(kb.store.version(old["document"]["target_version"]))
    assert kb.store.document(new["document"]["id"])["active_version"] is None
    await kb.process(kb.store.version(new["document"]["target_version"]))
    assert (
        kb.store.document(new["document"]["id"])["active_version"]
        == new["document"]["target_version"]
    )


async def test_catalogue_recovery_resumes_import_without_changing_chat_or_memory(knowledge):
    kb = knowledge
    lib = library(kb)
    r = await kb.upload(lib["id"], "guide.md", b"pending document")
    vid = r["document"]["target_version"]
    kb.store.stage(vid, "indexing")
    kb.store.close()
    recovered = Knowledge(kb.config, kb.config.state_db, identity_resolver=kb.identity_resolver)
    recovered.backend = kb.backend
    kb.store = recovered.store
    assert kb.store.version(vid)["state"] == "queued"
    await kb.process(kb.store.pending())
    assert kb.store.document(r["document"]["id"])["active_version"] == vid
    assert kb.bridge_store.db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
    assert not kb.config.memory_db.exists()


async def test_invalid_uploads_and_unknown_group_are_rejected(knowledge):
    kb = knowledge
    lib = library(kb)
    for name, content in [("bad.exe", b"bad"), ("../secret.md", b"bad"), ("empty.txt", b"")]:
        with pytest.raises(KnowledgeError):
            await kb.upload(lib["id"], name, content)
    with pytest.raises(KnowledgeError):
        kb.save_library({"name": "错误权限", "groups": [99]})
    assert not list((kb.root / "raw").iterdir())


async def test_embedding_binding_change_does_not_silently_mix_indexes(knowledge):
    kb = knowledge
    changed_config = replace(kb.config, memory_dimensions=512)
    changed = Knowledge(changed_config, changed_config.state_db)
    try:
        with pytest.raises(KnowledgeError, match="迁移"):
            changed.require()
    finally:
        await changed.close()


async def test_import_worker_records_failure_and_retries_after_restart(knowledge):
    from conftest import eventually

    kb = knowledge
    lib = library(kb)
    result = await kb.upload(lib["id"], "bad.pdf", b"not a PDF")
    worker = asyncio.create_task(kb.worker())
    try:
        await eventually(
            lambda: kb.store.version(result["document"]["target_version"])["state"] == "failed"
        )
        failed = kb.store.version(result["document"]["target_version"])
        assert "解析" in failed["error"]
        kb.store.retry(result["document"]["id"])
        assert kb.store.version(failed["id"])["state"] == "queued"
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_native_tools_auth_real_task_child_scope_and_no_identity_arguments(knowledge):
    kb = knowledge
    lib = library(kb, [22])
    await indexed(kb, lib)
    owner, group, stranger = job(kb), job(kb, user=12, group=22), job(kb, user=12)
    await kb.tools.start()
    async with aiohttp.ClientSession(
        connector=aiohttp.UnixConnector(path=str(kb.tools.socket))
    ) as http:

        async def call(j, name="search", args=None, *, session=None, token=True):
            async with http.post(
                "http://localhost/call",
                json={
                    "session_id": session or j["session_id"],
                    "call_id": "test",
                    "name": name,
                    "arguments": {"query": "部署"} if args is None else args,
                },
                headers={"Authorization": "Bearer " + kb.tools.token} if token else {},
            ) as r:
                return r.status, await r.json()

        assert (await call(owner, token=False))[0] == 401
        assert (await call(owner, session="spoofed"))[0] == 403
        assert (await call(owner, args={"query": "部署", "user_id": 11}))[0] == 400
        assert (await call(group))[1]["items"]
        assert (await call(stranger))[1]["items"] == []
        kb.opencode.belongs_to.side_effect = lambda session, root: (
            session == "child" and root == owner["session_id"]
        )
        assert (await call(owner, session="child"))[0] == 200
        result = (await call(owner))[1]
        chunk = result["items"][0]["id"]
        assert (await call(stranger, "read", {"id": chunk}))[0] == 403
        kb.backend.on_search = lambda: kb.bridge_store.update_job(owner["id"], cancel_requested=1)
        assert (await call(owner))[0] == 403


async def test_webui_auth_csrf_upload_preview_search_and_delete(knowledge):
    kb = knowledge
    dashboard = kb.webui
    client = TestClient(TestServer(await dashboard.application()))
    await client.start_server()
    try:
        assert (await client.get("/api/knowledge")).status == 401
        assert (await client.post("/api/knowledge/libraries", json={"name": "test"})).status == 401
        password = dashboard.auth.login_file.read_text().split("密码：", 1)[1].splitlines()[0]
        login = await client.post(
            "/api/auth/login", json={"username": "admin", "password": password}
        )
        headers = {"X-CSRF-Token": (await login.json())["csrf"]}
        status = await (await client.get("/api/auth/status")).json()
        assert status["knowledge_enabled"] is True
        assert (await client.post("/api/knowledge/libraries", json={"name": "test"})).status == 403
        r = await client.post(
            "/api/knowledge/libraries", json={"name": "测试库", "groups": [22]}, headers=headers
        )
        lib = await r.json()
        data = aiohttp.FormData()
        data.add_field(
            "file",
            "# Deploy\nRestart qqbot.service",
            filename="guide.md",
            content_type="text/markdown",
        )
        r = await client.post(
            f"/api/knowledge/libraries/{lib['id']}/documents", data=data, headers=headers
        )
        assert r.status == 202
        d = (await r.json())["document"]
        await kb.process(kb.store.version(d["target_version"]))
        preview = await (await client.get(f"/api/knowledge/documents/{d['id']}")).json()
        assert preview["chunks"][0]["heading"] == "Deploy"
        r = await client.get(f"/api/knowledge/documents/{d['id']}/download")
        assert r.status == 200 and "attachment;" in r.headers["Content-Disposition"]
        r = await client.post(
            "/api/knowledge/search",
            json={"query": "qqbot.service", "library_id": lib["id"]},
            headers=headers,
        )
        assert (await r.json())["items"]
        assert not kb.bridge_store.db.execute("SELECT * FROM jobs").fetchall()
        r = await client.post(
            f"/api/knowledge/documents/{d['id']}/delete",
            json={"confirm": "delete"},
            headers=headers,
        )
        assert r.status == 200
        assert (await client.get(f"/api/knowledge/documents/{d['id']}/download")).status == 404
        await client.post(
            f"/api/knowledge/libraries/{lib['id']}/delete",
            json={"confirm": "delete"},
            headers=headers,
        )
        assert (await (await client.get("/api/knowledge")).json())["libraries"] == []
    finally:
        await client.close()
        await dashboard.close()


def test_parser_handles_sections_encoding_empty_and_scan(tmp_path):
    p = tmp_path / "test.md"
    p.write_bytes("# 部署\n先备份\n## 恢复\n再检查".encode("gb18030"))
    sections = parse(p, ".md")
    assert [s["heading"] for s in sections] == ["部署", "恢复"]
    p.write_bytes(b"\0\1\2")
    with pytest.raises(ValueError, match="文字"):
        parse(p, ".txt")
    from pypdf import PdfWriter

    pdf = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with pdf.open("wb") as stream:
        writer.write(stream)
    with pytest.raises(ValueError, match="OCR"):
        parse(pdf, ".pdf")


async def test_model_client_validates_embeddings_and_does_not_use_personal_memory_instruction(
    knowledge,
):
    backend = KnowledgeBackend(knowledge.config)
    vector = [0.1] * knowledge.config.memory_dimensions
    backend.request = AsyncMock(return_value={"data": [{"index": 0, "embedding": vector}]})
    assert await backend.embed(["部署"], query=True) == [vector]
    payload = backend.request.call_args.args[1]
    assert "document passages" in payload["input"][0]
    assert payload["dimensions"] == 1024
    backend.request.return_value = {"data": [{"index": 0, "embedding": [float("nan")]}]}
    with pytest.raises(ValueError):
        await backend.embed(["bad"])


async def test_rerank_rejects_invalid_scores_and_omits_irrelevant_passages(knowledge):
    backend = KnowledgeBackend(knowledge.config)
    backend.request = AsyncMock(
        return_value={
            "results": [
                {"index": 0, "relevance_score": 0.01},
                {"index": 1, "relevance_score": 0.8},
            ]
        }
    )
    rows = [{"id": "a", "text": "无关内容"}, {"id": "b", "text": "部署说明"}]
    result = await backend.rerank("如何部署", rows)
    assert [r["id"] for r in result] == ["b"]
    assert result[0]["rerank_score"] == 0.8
    backend.request.return_value = {"results": [{"index": 0, "relevance_score": float("nan")}]}
    with pytest.raises(ValueError):
        await backend.rerank("如何部署", rows)


async def test_assistant_can_write_own_method_notes(knowledge):
    """助手可以把自己的方法笔记写进可见的资料库。"""
    kb = knowledge
    lib = library(kb)
    result = await kb.write_from_tool(
        lib["id"],
        "如何抓取视频字幕",
        {"content": "# 抓取字幕\n\n先用 player/v2 查字幕轨，再补 https 前缀下载。"},
        context=Context(777, 11),
    )
    assert result["duplicate"] is False
    vid = result["document"]["target_version"]
    await kb.process(kb.store.version(vid))
    found = await kb.search("字幕", context=Context(777, 11))
    assert any("player/v2" in r["text"] for r in found["items"])


async def test_assistant_cannot_write_to_invisible_library(knowledge):
    kb = knowledge
    lib = library(kb)
    with pytest.raises(PermissionError):
        await kb.write_from_tool(lib["id"], "note.md", {"content": "x"}, context=Context(777, 12))


@pytest.mark.parametrize("change", ["cancel", "delete_library"])
async def test_write_rechecks_identity_and_library_after_async_file_read(
    knowledge, tmp_path, monkeypatch, change
):
    kb = knowledge
    lib = library(kb)
    active_job = job(kb)
    source = tmp_path / "method.md"
    source.write_text("bounded source document", encoding="utf-8")
    started, release = threading.Event(), threading.Event()

    def blocked_read(path):
        started.set()
        if not release.wait(timeout=5):
            raise TimeoutError
        return path.read_bytes()

    monkeypatch.setattr(kb, "_read_tool_file", blocked_read)
    pending = asyncio.create_task(
        kb.write_from_tool(
            lib["id"],
            "method.md",
            {"path": str(source)},
            context=Context(777, 11),
            session_id=active_job["session_id"],
            job_id=active_job["id"],
        )
    )
    assert await asyncio.to_thread(started.wait, 2)
    if change == "cancel":
        kb.bridge_store.update_job(active_job["id"], cancel_requested=1)
    else:
        kb.store.delete_library(lib["id"])
    release.set()
    with pytest.raises(PermissionError):
        await pending
    assert (
        kb.store.db.execute(
            "SELECT count(*) FROM documents WHERE library_id=?", (lib["id"],)
        ).fetchone()[0]
        == 0
    )
