"""LlamaIndex splitting and pgvector, with explicit direct model clients."""

from __future__ import annotations

import asyncio
import hashlib
import math
import re

import aiohttp


class KnowledgeBackend:
    def __init__(self, config, *, schema="qq_knowledge"):
        self.config = config
        self.schema = schema
        self.http = None
        self.vector = None
        self.lock = asyncio.Lock()

    async def request(self, endpoint, body):
        if self.http is None:
            self.http = aiohttp.ClientSession(
                trust_env=False, timeout=aiohttp.ClientTimeout(total=45)
            )
        async with self.http.post(
            self.config.memory_base_url + endpoint,
            json=body,
            headers={"Authorization": "Bearer " + self.config.memory_api_key},
            allow_redirects=False,
        ) as response:
            if response.status != 200:
                raise RuntimeError("知识模型服务暂不可用")
            return await response.json()

    async def embed(self, texts, *, query=False):
        if query:
            texts = [
                "Instruct: Retrieve document passages relevant to the question.\nQuery:" + t
                for t in texts
            ]
        result = await self.request(
            "/embeddings",
            {
                "model": self.config.memory_embedding_model,
                "input": texts,
                "dimensions": self.config.memory_dimensions,
                "encoding_format": "float",
            },
        )
        data = sorted(result["data"], key=lambda row: row["index"])
        if [r["index"] for r in data] != list(range(len(texts))):
            raise ValueError("Embedding 返回条数或索引无效")
        vectors = [row["embedding"] for row in data]
        if any(
            len(v) != self.config.memory_dimensions
            or any(
                isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x)
                for x in v
            )
            for v in vectors
        ):
            raise ValueError("Embedding 维度或数值无效")
        return vectors

    async def ensure(self):
        async with self.lock:
            if self.vector is not None:
                return self.vector

            def create():
                from llama_index.vector_stores.postgres import PGVectorStore
                from sqlalchemy import create_engine
                from sqlalchemy.engine import make_url
                from sqlalchemy.ext.asyncio import create_async_engine

                url = make_url(self.config.memory_database_url)
                sync_url = url.set(drivername="postgresql+psycopg2")
                query = dict(url.query)
                timeout = min(30, max(1, float(query.pop("connect_timeout", "5"))))
                sslmode = query.pop("sslmode", None)
                async_url = url.set(drivername="postgresql+asyncpg", query=query)
                sync_engine = create_engine(sync_url, pool_size=2, max_overflow=0)
                async_engine = create_async_engine(
                    async_url,
                    pool_size=2,
                    max_overflow=0,
                    connect_args={
                        "timeout": timeout,
                        "command_timeout": 20,
                        **({"ssl": sslmode} if sslmode is not None else {}),
                    },
                )
                vector = PGVectorStore(
                    connection_string=sync_url.render_as_string(hide_password=False),
                    async_connection_string=async_url.render_as_string(hide_password=False),
                    engine=sync_engine,
                    async_engine=async_engine,
                    table_name="chunks",
                    schema_name=self.schema,
                    embed_dim=self.config.memory_dimensions,
                    use_jsonb=True,
                    initialization_fail_on_error=True,
                    hnsw_kwargs={
                        "hnsw_m": 16,
                        "hnsw_ef_construction": 64,
                        "hnsw_ef_search": 80,
                        "hnsw_dist_method": "vector_cosine_ops",
                    },
                )
                # PGVectorStore's public async methods initialize synchronously on first call.
                # Do that once off the bridge event loop instead.
                vector._initialize()
                return vector

            self.vector = await asyncio.to_thread(create)
            return self.vector

    async def replace(self, version_id, chunks):
        from llama_index.core.schema import TextNode

        vector = await self.ensure()
        await self.delete(version_id)
        for offset in range(0, len(chunks), 16):
            batch = chunks[offset : offset + 16]
            embeddings = await self.embed([c["text"] for c in batch])
            await vector.async_add(
                [
                    TextNode(
                        id_=c["id"],
                        text=c["text"],
                        embedding=embedding,
                        metadata={"version_id": version_id},
                    )
                    for c, embedding in zip(batch, embeddings, strict=True)
                ]
            )

    async def search(self, query, versions):
        from llama_index.core.vector_stores import (
            FilterOperator,
            MetadataFilter,
            MetadataFilters,
            VectorStoreQuery,
        )

        vector = await self.ensure()
        embedding = (await self.embed([query], query=True))[0]
        result = await vector.aquery(
            VectorStoreQuery(
                query_embedding=embedding,
                similarity_top_k=30,
                filters=MetadataFilters(
                    filters=[
                        MetadataFilter(key="version_id", value=versions, operator=FilterOperator.IN)
                    ]
                ),
            )
        )
        return [
            id
            for id, score in zip(result.ids or [], result.similarities or [], strict=True)
            if score >= 0.15
        ]

    async def delete(self, version_id):
        from llama_index.core.vector_stores import MetadataFilter, MetadataFilters

        vector = await self.ensure()
        await vector.adelete_nodes(
            filters=MetadataFilters(filters=[MetadataFilter(key="version_id", value=version_id)])
        )

    async def rerank(self, query, rows):
        result = await self.request(
            "/rerank",
            {
                "model": self.config.memory_rerank_model,
                "query": query,
                "documents": [row["text"] for row in rows],
                "top_n": min(5, len(rows)),
                "return_documents": False,
                "instruction": "Retrieve document passages that answer the question.",
            },
        )
        indices = [r["index"] for r in result["results"]]
        if len(indices) != len(set(indices)) or any(
            isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(rows) for i in indices
        ):
            raise ValueError("重排返回索引无效")
        scores = [r["relevance_score"] for r in result["results"]]
        if any(
            isinstance(score, bool)
            or not isinstance(score, (float, int))
            or not math.isfinite(score)
            or not 0 <= score <= 1
            for score in scores
        ):
            raise ValueError("重排得分无效")
        return [
            {**rows[i], "rerank_score": score}
            for i, score in zip(indices, scores, strict=True)
            if score >= 0.1
        ]

    async def close(self):
        if self.http:
            await self.http.close()
        if self.vector:
            await self.vector.close()


def terms(text):
    import jieba

    jieba.setLogLevel(30)
    # Keep exact identifiers as well as Chinese words, for config names and error codes.
    words = list(jieba.cut_for_search(text[:1_000_000]))
    words.extend(re.findall(r"[A-Za-z0-9_][A-Za-z0-9_.:/-]*", text))
    return " ".join(w.casefold() for w in words if w.strip() and any(c.isalnum() for c in w))


def split_sections(sections, version_id):
    from llama_index.core.node_parser import SentenceSplitter

    splitter = SentenceSplitter(chunk_size=400, chunk_overlap=60)
    chunks = []
    for section in sections:
        for text in splitter.split_text(section["text"]):
            position = len(chunks)
            chunks.append(
                {
                    "id": hashlib.sha256(f"{version_id}:{position}".encode()).hexdigest(),
                    "position": position,
                    "page": section["page"],
                    "heading": section["heading"],
                    "text": text,
                    "terms": terms(text),
                }
            )
            if len(chunks) > 2000:
                raise ValueError("文档分段超过 2000，请拆分后导入")
    return chunks
