"""Read-only projections of OpenCode capabilities. Never expose plugin configuration."""

from __future__ import annotations

import asyncio
import time
from pathlib import PurePosixPath

from aiohttp import ClientError, web

from .opencode import ApiError, ProtocolError


def project(kind, items):
    if not isinstance(items, list):
        raise ProtocolError("能力目录响应无效")
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if kind == "plugins":
            source, state = item.get("source") or {}, item.get("state") or {}
            result.append(
                {
                    "id": item.get("id")
                    or PurePosixPath(source.get("path") or source.get("target") or "plugin").name,
                    "source": source.get("type"),
                    "version": source.get("version"),
                    "status": state.get("status", "unknown"),
                    "features": [
                        k for k in ("server", "tui", "rpc") if (item.get("features") or {}).get(k)
                    ],
                }
            )
        elif kind == "mcp":
            result.append(
                {
                    "name": item.get("name"),
                    "status": (item.get("status") or {}).get("status", "unknown"),
                }
            )
        elif kind == "skills":
            result.append({k: item.get(k) for k in ("id", "name", "description", "autoinvoke")})
        elif kind == "agents":
            if not item.get("hidden"):
                result.append({k: item.get(k) for k in ("id", "name", "description", "mode")})
        else:
            result.append({k: item.get(k) for k in ("id", "name", "description") if k in item})
    return result


class CapabilitiesConsole:
    def __init__(self, dashboard):
        self.dashboard = dashboard
        self.cached = None

    def routes(self):
        return [web.get("/api/capabilities", self.index)]

    async def index(self, request):
        ui = self.dashboard
        if self.cached and time.monotonic() - self.cached[0] < 30:
            return web.json_response(self.cached[1])
        client = ui.data.client()
        params = {"location[directory]": str(ui.config.workdir)}

        async def read(kind, path):
            try:
                async with ui.data.remote_limit, asyncio.timeout(10):
                    items = await client.request("GET", path, params=params)
                return kind, {"available": True, "items": project(kind, items)}
            except (
                ApiError,
                ProtocolError,
                ClientError,
                TimeoutError,
                OSError,
                ValueError,
                TypeError,
            ):
                return kind, {"available": False, "items": []}

        sections = dict(
            await asyncio.gather(
                *(
                    read(kind, path)
                    for kind, path in {
                        "plugins": "/api/plugin",
                        "skills": "/api/skill",
                        "mcp": "/api/mcp",
                        "commands": "/api/command",
                        "agents": "/api/agent",
                        "search": "/api/websearch/provider",
                    }.items()
                )
            )
        )
        selected = None
        try:
            async with ui.data.remote_limit, asyncio.timeout(10):
                documents = await client.request("GET", "/api/config", params=params, unwrap=False)
            if isinstance(documents, list):
                for document in documents:
                    if isinstance(document, dict):
                        config = document.get("info")
                        search = config.get("websearch") if isinstance(config, dict) else None
                        if isinstance(search, dict) and isinstance(search.get("provider"), str):
                            selected = search["provider"]
            if selected not in {p["id"] for p in sections["search"]["items"]}:
                selected = None
        except (ApiError, ProtocolError, ClientError, TimeoutError, OSError):
            pass
        result = ui.data.clean(
            {"sections": sections, "search_provider": selected, "updated": time.time()}
        )
        self.cached = (time.monotonic(), result)
        return web.json_response(result)
