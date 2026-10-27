"""Mem0/pgvector storage with direct, bounded SiliconFlow embedding calls."""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

from .config import Config


class Mem0Backend:
    def __init__(self, config: Config, *, collection="qq_owner_memory"):
        self.config = config
        self.collection = collection
        self.memory = None
        self.client = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qq-memory")

    def _ensure(self):
        if self.memory is not None:
            return
        os.environ["MEM0_TELEMETRY"] = "false"
        from mem0 import Memory
        from openai import DefaultHttpxClient, OpenAI

        cfg = self.config
        self.client = OpenAI(
            api_key=cfg.memory_api_key,
            base_url=cfg.memory_base_url,
            http_client=DefaultHttpxClient(trust_env=False),
            timeout=min(20, cfg.memory_timeout),
            max_retries=0,
        )
        self.memory = Memory.from_config(
            {
                "llm": {
                    "provider": "openai",
                    "config": {
                        "model": cfg.memory_model,
                        "api_key": cfg.memory_api_key,
                        "openai_base_url": cfg.memory_base_url,
                    },
                },
                "embedder": {
                    "provider": "openai",
                    "config": {
                        "model": cfg.memory_embedding_model,
                        "api_key": cfg.memory_api_key,
                        "openai_base_url": cfg.memory_base_url,
                        "embedding_dims": cfg.memory_dimensions,
                    },
                },
                "vector_store": {
                    "provider": "pgvector",
                    "config": {
                        "connection_string": cfg.memory_database_url,
                        "collection_name": self.collection,
                        "embedding_model_dims": cfg.memory_dimensions,
                        "minconn": 1,
                        "maxconn": 2,
                        "hnsw": True,
                    },
                },
                "history_db_path": str(cfg.memory_db.with_name("mem0-history.sqlite3")),
            }
        )
        os.chmod(cfg.memory_db.with_name("mem0-history.sqlite3"), 0o600)
        # The SDK's stock OpenAI embedder does not forward its HTTP client config.
        # Use a direct client explicitly, without changing any process proxy variables.
        self.memory.embedding_model.client.close()
        self.memory.embedding_model = SiliconFlowEmbedding(self.client, cfg)

    async def _call(self, method, *args):
        def run():
            self._ensure()
            return getattr(self, method)(*args)

        return await asyncio.get_running_loop().run_in_executor(self.executor, run)

    async def health(self):
        return await self._call("_health")

    def _health(self):
        return {"collection": self.collection, "dimensions": self.config.memory_dimensions}

    async def add(self, entry: dict) -> str:
        return await self._call("_add", entry)

    def _add(self, entry):
        filters = {"user_id": entry["owner"], "ledger_id": entry["id"]}
        previous = self.memory.get_all(filters=filters, top_k=1)["results"]
        if previous:
            return previous[0]["id"]
        result = self.memory.add(
            entry["content"],
            user_id=entry["owner"],
            infer=False,
            metadata={
                "ledger_id": entry["id"],
                "scope": entry["scope"],
                "kind": entry["kind"],
                "subject": entry.get("subject", "user"),
            },
        )
        if not result.get("results"):
            raise ValueError("Mem0 未确认记忆写入")
        return result["results"][0]["id"]

    async def search(self, owner: str, query: str, *, private=True) -> list[dict]:
        return await self._call("_search", owner, query, private)

    def _search(self, owner, query, private):
        filters = {"user_id": owner}
        if not private:
            filters["scope"] = "group"
        return self.memory.search(query, filters=filters, top_k=20, threshold=0.15)["results"]

    async def delete(self, owner: str, backend_id: str):
        return await self._call("_delete", owner, backend_id)

    def _delete(self, owner, backend_id):
        record = self.memory.get(backend_id)
        if record and record.get("user_id") != owner:
            raise ValueError("记忆归属不匹配")
        if record:
            self.memory.delete(backend_id)

    async def close(self):
        def close():
            if self.memory:
                self.memory.close()
                pool = self.memory.vector_store.connection_pool
                if hasattr(pool, "closeall"):
                    pool.closeall()
                else:
                    pool.close()
                self.memory.llm.client.close()
            if self.client:
                self.client.close()

        await asyncio.get_running_loop().run_in_executor(self.executor, close)
        self.executor.shutdown(wait=True, cancel_futures=True)


class SiliconFlowEmbedding:
    def __init__(self, client, config):
        self.client, self.config = client, config

    def embed(self, text, memory_action=None):
        if memory_action == "search":
            text = (
                "Instruct: Retrieve personal memories relevant to the user question.\nQuery:" + text
            )
        response = self.client.embeddings.create(
            model=self.config.memory_embedding_model,
            input=[text],
            encoding_format="float",
            dimensions=self.config.memory_dimensions,
        )
        vector = response.data[0].embedding
        if len(vector) != self.config.memory_dimensions:
            raise ValueError("Embedding 返回维度与数据库配置不符")
        return vector

    def embed_batch(self, texts, memory_action=None):
        return [self.embed(text, memory_action) for text in texts]
