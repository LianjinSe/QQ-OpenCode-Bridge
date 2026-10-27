"""Administrator-only knowledge actions; mounted behind dashboard auth and CSRF."""

from __future__ import annotations

from aiohttp import web

from .http_params import page_number
from .knowledge import MAX_UPLOAD, KnowledgeError


class KnowledgeConsole:
    def __init__(self, dashboard):
        self.dashboard = dashboard
        self.knowledge = dashboard.knowledge

    def routes(self):
        return [
            web.get("/api/knowledge", self.index),
            web.post("/api/knowledge/libraries", self.save),
            web.post("/api/knowledge/libraries/{id}", self.save),
            web.post("/api/knowledge/libraries/{id}/delete", self.delete_library),
            web.get("/api/knowledge/libraries/{id}", self.library),
            web.post("/api/knowledge/libraries/{id}/documents", self.upload),
            web.get("/api/knowledge/documents/{id}", self.document),
            web.get("/api/knowledge/documents/{id}/download", self.download),
            web.post("/api/knowledge/documents/{id}/delete", self.delete),
            web.post("/api/knowledge/documents/{id}/retry", self.retry),
            web.post("/api/knowledge/search", self.search),
        ]

    async def index(self, request):
        kb = self.knowledge
        return web.json_response(
            {
                "enabled": kb.enabled,
                "error": kb.backend_error,
                "libraries": kb.store.libraries() if kb.enabled else [],
                "groups": sorted(self.dashboard.config.allowed_groups),
                "history": kb.store.history() if kb.enabled else [],
            }
        )

    async def save(self, request):
        library = self.knowledge.save_library(
            await self.dashboard.body(request), id=request.match_info.get("id")
        )
        self.dashboard.audit("knowledge_library", library["id"])
        return web.json_response(library)

    async def library(self, request):
        self.knowledge.require()
        id = request.match_info["id"]
        return web.json_response(
            {
                "library": self.knowledge.store.library(id),
                "documents": self.knowledge.store.documents(id),
            }
        )

    async def delete_library(self, request):
        self.knowledge.require()
        body = await self.dashboard.body(request)
        if body.get("confirm") != "delete":
            raise KnowledgeError("需要确认删除资料库")
        self.knowledge.store.delete_library(request.match_info["id"])
        self.knowledge.ready.set()
        self.dashboard.audit("knowledge_library_delete", request.match_info["id"])
        return web.json_response({"ok": True})

    async def upload(self, request):
        self.knowledge.require()
        reader = await request.multipart()
        field = await reader.next()
        if field is None or field.name != "file" or not field.filename:
            raise KnowledgeError("请选择一个文档")
        chunks, size = [], 0
        while data := await field.read_chunk(65536):
            size += len(data)
            if size > MAX_UPLOAD:
                raise web.HTTPRequestEntityTooLarge(max_size=MAX_UPLOAD, actual_size=size)
            chunks.append(data)
        result = await self.knowledge.upload(
            request.match_info["id"], field.filename, b"".join(chunks)
        )
        self.dashboard.audit("knowledge_upload", result["document"]["id"])
        return web.json_response(result, status=202)

    async def document(self, request):
        self.knowledge.require()
        return web.json_response(
            self.knowledge.preview(
                request.match_info["id"], offset=page_number(request, "offset", maximum=2000)
            )
        )

    async def download(self, request):
        self.knowledge.require()
        document = self.knowledge.store.document(request.match_info["id"])
        if not document["active_version"]:
            raise KnowledgeError("文档还没有可用版本")
        version = self.knowledge.store.version(document["active_version"])
        response = web.FileResponse(self.knowledge.file(version))
        from urllib.parse import quote

        response.headers["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(
            document["filename"]
        )
        response.content_type = "application/octet-stream"
        return response

    async def delete(self, request):
        self.knowledge.require()
        body = await self.dashboard.body(request)
        if body.get("confirm") != "delete":
            raise KnowledgeError("需要确认删除文档")
        self.knowledge.store.delete_document(request.match_info["id"])
        self.knowledge.ready.set()
        self.dashboard.audit("knowledge_delete", request.match_info["id"])
        return web.json_response({"ok": True, "cleanup_pending": True})

    async def retry(self, request):
        self.knowledge.require()
        self.knowledge.store.retry(request.match_info["id"])
        self.knowledge.ready.set()
        self.dashboard.audit("knowledge_retry", request.match_info["id"])
        return web.json_response({"ok": True})

    async def search(self, request):
        self.knowledge.require()
        body = await self.dashboard.body(request)
        library_id = body.get("library_id")
        if library_id is not None:
            if not isinstance(library_id, str):
                raise KnowledgeError("资料库参数无效")
            self.knowledge.store.library(library_id)
        return web.json_response(
            await self.knowledge.search(body.get("query"), library_id=library_id)
        )
