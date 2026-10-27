"""Small, scoped evidence excerpts from bridge archives and completed tools."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time

from .content_safety import redact_evidence
from .models import Context


class MemoryEvidence:
    def __init__(self, memory):
        self.memory = memory
        self.bridge_store = memory.bridge_store
        self.opencode = memory.opencode
        self.store = memory.store

    def allowed_source(self, source, owner, private):
        return (
            source
            and source["owner"] == owner
            and not source["suppressed"]
            and (private or source["scope"] == "group")
        )

    def remember(self, job, source, kind, text, reference, query):
        text = redact_evidence(text)
        if not text.strip():
            return None
        position = text.lower().find(query.lower())
        offset = max(0, position - 400) if position >= 0 else 0
        excerpt = text[offset : offset + 2400]
        identity = json.dumps([job["id"], source["id"], kind, reference, excerpt], sort_keys=True)
        id = hashlib.sha256(identity.encode()).hexdigest()
        self.store.remember_evidence(
            id,
            source["owner"],
            job["id"],
            source["id"],
            kind,
            excerpt,
            json.dumps(reference, ensure_ascii=False),
            time.time(),
        )
        return {
            "id": id,
            "source_id": source["id"],
            "kind": kind,
            "text": excerpt,
            "time": source["created"],
            **reference,
        }

    async def tool_records(self, job, query="", active_job=None):
        """Stop at the next independent user turn, even in a shared session."""
        if not job["session_id"] or not job["admitted"]:
            return []
        context = Context(**json.loads(job["target"]))
        if context.group_id is not None and not job["memory_isolated"]:
            return []
        _, messages = await self.opencode.turn(job["session_id"], job["prompt_id"])
        if active_job is not None and self.memory.identity_resolver is not None:
            current, current_context = await self.memory.identity_resolver(active_job["session_id"])
            if current["id"] != active_job["id"] or current_context != Context(
                **json.loads(active_job["target"])
            ):
                raise PermissionError
        steer_ids = {
            row["prompt_id"]
            for row in self.bridge_store.steers(job.get("steer_parent_id") or job["id"])
            if row["admitted"] and row["context"] == context.key
        }
        result = []
        for message in messages:
            if message.get("type") == "user":
                if message.get("id") not in steer_ids:
                    break
                continue
            if message.get("type") != "assistant":
                continue
            for part in message.get("content", []):
                state = part.get("state", {})
                if (
                    part.get("type") != "tool"
                    or state.get("status") not in {"completed", "failed", "error"}
                    or part.get("name", "").startswith("memory_")
                ):
                    continue
                metadata = state.get("metadata") or {}
                failed = (
                    state.get("status") != "completed"
                    or bool(state.get("error"))
                    or metadata.get("exit", metadata.get("exitCode", 0)) != 0
                )
                chunks = [
                    item.get("text", "")
                    for item in state.get("content", [])
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                output = state.get("output")
                if not chunks and output is not None:
                    chunks = [
                        output
                        if isinstance(output, str)
                        else json.dumps(output, ensure_ascii=False)
                    ]
                text = "\n".join(chunks)
                if not text:
                    error = state.get("error")
                    if error:
                        text = (
                            error
                            if isinstance(error, str)
                            else json.dumps(error, ensure_ascii=False)
                        )
                    else:
                        continue
                try:
                    value = json.loads(text)
                    if isinstance(value, dict) and (
                        value.get("ok") is False or value.get("isError") is True
                    ):
                        failed = True
                except ValueError:
                    pass
                result.append(
                    (
                        "tool_error" if failed else "tool",
                        text,
                        {
                            "session_id": job["session_id"],
                            "message_id": message["id"],
                            "tool_id": part["id"],
                            "tool": part.get("name"),
                            "status": "failed" if failed else "completed",
                        },
                    )
                )
        if query:
            result.sort(key=lambda row: query.lower() in row[1].lower())
        return result[-10:]

    async def find(self, job, context, arguments, private):
        owner = self.memory.owner(context)
        query = arguments["query"]
        sources = [self.store.source(job["id"])]
        admitted = {job["id"]}
        if context.group_id is None:
            for row in self.bridge_store.steers(job["id"]):
                if row["admitted"] and row["context"] == context.key:
                    admitted.add(row["id"])
                    sources.append(self.store.source(row["id"]))
        for id in arguments.get("source_ids", []):
            source = self.store.source(id)
            if source and (source["completed"] or id in admitted):
                sources.append(source)
        sources += self.store.search_sources(owner, private, query)
        unique = {
            source["id"]: source
            for source in sources
            if self.allowed_source(source, owner, private)
        }
        candidates = []
        partial = False
        current = self.store.source(job["id"])
        persona = self.memory.config.workdir / "AGENTS.md"
        if self.allowed_source(current, owner, private) and persona.is_file():
            persona_text = persona.read_text()
            if query.lower() in persona_text.lower():
                candidates.append(
                    self.remember(
                        job,
                        current,
                        "persona",
                        persona_text,
                        {"document": "runtime_persona"},
                        query,
                    )
                )
        for source in list(unique.values())[:6]:
            for saved in self.store.saved_evidence(source["id"], owner):
                candidates.append(
                    self.remember(
                        job,
                        source,
                        saved["kind"],
                        saved["excerpt"],
                        json.loads(saved["reference"]),
                        query,
                    )
                )
            for kind, text in (
                ("user", source["user_text"]),
                ("assistant_report", source["assistant_text"]),
            ):
                if text:
                    candidates.append(self.remember(job, source, kind, text, {}, query))
            try:
                origin = self.bridge_store.job(source["id"])
            except KeyError:
                continue
            origin_context = Context(**json.loads(origin["target"]))
            if self.memory.owner(origin_context) != owner or (
                not private and origin_context.group_id is None
            ):
                continue
            try:
                async with asyncio.timeout(4):
                    records = await self.tool_records(origin, query, active_job=job)
            except Exception:
                records = []
                partial = True
            for kind, text, reference in records:
                candidates.append(self.remember(job, source, kind, text, reference, query))
        self.store.commit()
        candidates = list({row["id"]: row for row in candidates if row}.values())
        candidates.sort(
            key=lambda row: (
                query.lower() in row["text"].lower(),
                row["kind"] == "tool",
                row["time"],
            ),
            reverse=True,
        )
        return {
            "ok": True,
            "partial": partial,
            "evidence": candidates[:8],
            "note": (
                "user是用户原话；persona是角色资料；tool是已完成调用的结果；"
                "tool_error支持失败经验；assistant_report不独立证明外部操作成功。"
            ),
        }

    def resolve(self, ids, job_id, owner, private):
        records = []
        for id in ids:
            row = self.store.evidence(id)
            source = self.store.source(row["source_id"]) if row else None
            if (
                not row
                or row["job_id"] != job_id
                or row["owner"] != owner
                or not row["excerpt"]
                or not self.allowed_source(source, owner, private)
            ):
                return None
            records.append(
                {
                    "id": id,
                    "kind": row["kind"],
                    "text": row["excerpt"],
                    "source_id": row["source_id"],
                    "scope": source["scope"],
                    "reference": json.loads(row["reference"]),
                }
            )
        return records
