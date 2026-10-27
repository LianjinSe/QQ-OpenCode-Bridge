"""Explicit document knowledge, separate from autobiographical personal memory."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys
import time
from contextlib import suppress
from pathlib import Path

from .knowledge_backend import KnowledgeBackend, split_sections, terms
from .knowledge_store import KnowledgeStore, new_id

log = logging.getLogger(__name__)
MAX_UPLOAD = 10 * 1024 * 1024
SUFFIXES = {".txt", ".md", ".markdown", ".pdf"}


class KnowledgeError(ValueError):
    pass


class Knowledge:
    def __init__(self, config, state_db, identity_resolver=None):
        self.config = config
        self.identity_resolver = identity_resolver
        self.enabled = self.config.knowledge_enabled
        self.root = state_db.parent / "knowledge"
        self.store = KnowledgeStore(self.root / "catalogue.sqlite3") if self.enabled else None
        try:
            self.backend = KnowledgeBackend(self.config) if self.enabled else None
            self.ready = asyncio.Event()
            self.search_limit = asyncio.Semaphore(2)
            self.backend_error = ""
            self.tools = None
            self.last_cleanup = 0
            if self.enabled:
                from .knowledge_tools import KnowledgeTools

                self.tools = KnowledgeTools(self)
                self.root.chmod(0o700)
                (self.root / "raw").mkdir(exist_ok=True, mode=0o700)
                binding = json.dumps(
                    [
                        self.config.memory_base_url,
                        self.config.memory_embedding_model,
                        self.config.memory_dimensions,
                    ]
                )
                old = self.store.setting("embedding")
                if old and old != binding:
                    self.backend_error = "Embedding 配置已变化，需迁移知识索引后才能继续使用"
                elif old is None:
                    self.store.save_setting("embedding", binding)
        except BaseException:
            if self.store is not None:
                self.store.close()
            raise

    def require(self):
        if not self.enabled:
            raise KnowledgeError("知识库尚未启用")
        if self.backend_error:
            raise KnowledgeError(self.backend_error)

    def file(self, version):
        return self.root / "raw" / (version["id"] + version["suffix"])

    def save_library(self, body, *, id=None):
        self.require()
        name, description = body.get("name"), body.get("description", "")
        groups = body.get("groups", [])
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise KnowledgeError("资料库名称需要 1–80 个字符")
        if not isinstance(description, str) or len(description) > 500:
            raise KnowledgeError("说明最多 500 个字符")
        if not isinstance(groups, list) or any(
            isinstance(g, bool) or not isinstance(g, int) or g not in self.config.allowed_groups
            for g in groups
        ):
            raise KnowledgeError("只能选择桥接已授权的群聊")
        if not id and len(self.store.libraries()) >= 30:
            raise KnowledgeError("资料库数量已达 30 个上限")
        return self.store.save_library(
            name.strip(),
            description.strip(),
            self.config.superadmin_user_id,
            sorted(set(groups)),
            id=id,
        )

    async def write_from_tool(
        self, library_id, filename, args, *, context=None, session_id=None, job_id=None
    ):
        """让助手把自己的方法笔记写进资料库；只接受主人私聊，且只能写自己的库。"""
        self.require()
        if (
            context is None
            or context.group_id is not None
            or context.user_id != self.config.superadmin_user_id
        ):
            raise PermissionError
        libraries = self.store.visible(context) if context is not None else []
        if not any(
            lib["id"] == library_id and lib["owner"] == context.user_id for lib in libraries
        ):
            raise PermissionError
        if not Path(filename).suffix:
            filename = filename + ".md"
        content = args.get("content")
        if content is None:
            path = args.get("path")
            if not isinstance(path, str) or not path:
                raise KnowledgeError("需要提供 content 或 path")
            source = Path(path)
            try:
                data = await asyncio.to_thread(self._read_tool_file, source)
            except FileNotFoundError:
                raise KnowledgeError("找不到这个文件") from None
            if not data or len(data) > MAX_UPLOAD:
                raise KnowledgeError("文档不能为空，单个文件最大 10 MiB")
            content = data
        elif isinstance(content, str):
            content = content.encode("utf-8")
        if not content:
            raise KnowledgeError("文档不能为空")
        if session_id is not None:
            if self.identity_resolver is None:
                raise PermissionError
            current, current_context = await self.identity_resolver(session_id)
            if current["id"] != job_id or current_context != context:
                raise PermissionError
            libraries = self.store.visible(current_context)
            if not any(
                lib["id"] == library_id and lib["owner"] == current_context.user_id
                for lib in libraries
            ):
                raise PermissionError
        return await self.upload(library_id, filename, content)

    @staticmethod
    def _read_tool_file(source: Path) -> bytes:
        if not source.is_file():
            raise FileNotFoundError(source)
        if source.stat().st_size > MAX_UPLOAD:
            raise KnowledgeError("文档不能为空，单个文件最大 10 MiB")
        with source.open("rb") as stream:
            data = stream.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise KnowledgeError("文档不能为空，单个文件最大 10 MiB")
        return data

    async def upload(self, library_id, filename, content):
        self.require()
        if not isinstance(filename, str) or not 1 <= len(filename) <= 180:
            raise KnowledgeError("文件名需要 1–180 个字符")
        if any(c in filename for c in ("/", "\\", "\x00", "\r", "\n")):
            raise KnowledgeError("文件名不能包含路径或控制字符")
        suffix = Path(filename).suffix.lower()
        if suffix not in SUFFIXES:
            raise KnowledgeError("支持 Markdown、TXT 和文字型 PDF")
        if not content or len(content) > MAX_UPLOAD:
            raise KnowledgeError("文档不能为空，单个文件最大 10 MiB")
        if sum(lib["documents"] for lib in self.store.libraries()) >= 500:
            existing = self.store.documents(library_id)
            if not any(d["filename"] == filename for d in existing):
                raise KnowledgeError("文档数量已达 500 个上限")
        self.store.library(library_id)
        vid = new_id()
        path = self.root / "raw" / (vid + suffix)
        # Persist the original before enqueueing. A failed/repeated upload never overwrites a file.
        with path.open("xb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        try:
            document, created = self.store.enqueue(
                library_id, filename, hashlib.sha256(content).hexdigest(), len(content), suffix, vid
            )
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        if not created:
            path.unlink(missing_ok=True)
        self.ready.set()
        return {"document": document, "duplicate": not created}

    async def parse(self, version):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "qqbot.knowledge_parse",
            str(self.file(version)),
            version["suffix"],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(35):
                stdout, _ = await process.communicate()
            if process.returncode:
                raise KnowledgeError("文档解析超出限制或进程未完成，请拆分文档")
            result = json.loads(stdout)
            if "error" in result:
                raise KnowledgeError(result["error"])
            return result["sections"]
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()

    async def process(self, version):
        vid = version["id"]
        if version["state"] == "deleting":
            await self.backend.delete(vid)
            self.file(version).unlink(missing_ok=True)
            self.store.finish_delete(vid)
            return
        if not self.store.current_target(vid):
            self.store.mark_deleting(vid)
            return
        self.store.stage(vid, "parsing")
        sections = await self.parse(version)
        self.store.stage(vid, "splitting")
        chunks = await asyncio.to_thread(split_sections, sections, vid)
        if not self.store.current_target(vid):
            return
        if not chunks:
            raise KnowledgeError("文档没有可索引的文字")
        self.store.stage(vid, "indexing")
        await self.backend.replace(vid, chunks)
        if not self.store.publish(vid, chunks):
            await self.backend.delete(vid)

    async def worker(self):
        while True:
            if time.monotonic() - self.last_cleanup > 60:
                self.store.prune_retrievals(time.time() - 604800)
                self.last_cleanup = time.monotonic()
            version = self.store.pending()
            if version is None or self.backend_error:
                self.ready.clear()
                with suppress(TimeoutError):
                    await asyncio.wait_for(self.ready.wait(), 3)
                continue
            try:
                await self.process(version)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("知识库后台任务待处理：%s", type(exc).__name__)
                if version["state"] == "deleting":
                    self.store.retry_delete(version["id"], time.time() + 60, "索引清理待重试")
                else:
                    self.store.failed(
                        version["id"],
                        str(exc) if isinstance(exc, KnowledgeError) else "索引服务暂不可用，可重试",
                        retry=not isinstance(exc, KnowledgeError),
                    )

    def allowed(self, context=None, library_id=None):
        libs = self.store.libraries() if context is None else self.store.visible(context)
        ids = [lib["id"] for lib in libs]
        if library_id:
            ids = [library_id] if library_id in ids else []
        return self.store.active_versions(ids)

    async def search(self, query, *, context=None, library_id=None, job_id=None):
        self.require()
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 500:
            raise KnowledgeError("检索问题需要 1–500 个字符")
        start = time.monotonic()
        async with self.search_limit:
            versions = self.allowed(context, library_id)
            if not versions:
                return {"items": [], "mode": "empty", "elapsed_ms": 0, "retrieval_id": None}
            query_terms = (await asyncio.to_thread(terms, query)).split()[:32]
            match = " OR ".join('"' + t.replace('"', '""') + '"' for t in set(query_terms))
            lexical = self.store.lexical(match, versions)
            mode = "hybrid"
            try:
                async with asyncio.timeout(15):
                    semantic = await self.backend.search(query, versions)
            except Exception:
                semantic, mode = [], "keyword_only"
            scores = {}
            for ids in (lexical, semantic):
                for rank, id in enumerate(dict.fromkeys(ids)):
                    scores[id] = scores.get(id, 0) + 1 / (60 + rank + 1)
            # Permission/version checks happen again after every remote operation.
            versions = self.allowed(context, library_id)
            rows = [
                row
                for id in sorted(scores, key=scores.get, reverse=True)[:20]
                if (row := self.store.chunk(id, versions))
            ]
            if rows and self.config.memory_rerank_enabled:
                try:
                    async with asyncio.timeout(10):
                        rows = await self.backend.rerank(query, rows)
                    mode += "+rerank"
                except Exception:
                    mode += "+rerank_unavailable"
            versions = self.allowed(context, library_id)
            scores = {r["id"]: r["rerank_score"] for r in rows if "rerank_score" in r}
            rows = [self.store.chunk(r["id"], versions) for r in rows]
            rows = [r for r in rows if r][:5]
            for row in rows:
                if row["id"] in scores:
                    row["rerank_score"] = scores[row["id"]]
                row["citation"] = self.citation(row)
                row["url"] = (
                    self.config.webui_public_url + "/#/knowledge?document=" + row["document_id"]
                )
            elapsed = round((time.monotonic() - start) * 1000)
            rid = self.store.record(
                query, rows, elapsed, mode, job_id=job_id, library_id=library_id
            )
            return {"items": rows, "mode": mode, "elapsed_ms": elapsed, "retrieval_id": rid}

    @staticmethod
    def citation(row):
        location = f"第 {row['page']} 页" if row["page"] else row["heading"]
        return f"《{row['filename']}》第 {row['version']} 版" + (
            " · " + location if location else ""
        )

    def preview(self, document_id, *, version_id=None, offset=0):
        document = self.store.document(document_id)
        vid = version_id or document["active_version"]
        if not vid:
            return {"document": document, "chunks": [], "more": False}
        if vid != document["active_version"]:
            raise KnowledgeError("只能预览当前可用版本")
        rows = self.store.preview_chunks(vid, offset)
        return {"document": document, "chunks": rows[:50], "more": len(rows) > 50}

    async def run(self):
        if not self.enabled:
            return
        log.info("LlamaIndex 知识库已启用；个人记忆与文档索引分别管理")
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(self.worker(), name="knowledge-import")
            tasks.create_task(self.tools.run(), name="knowledge-tools")

    async def close(self):
        if self.enabled:
            await self.tools.close()
            await self.backend.close()
            self.store.close()
