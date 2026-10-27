from __future__ import annotations

import hashlib
import json

import aiohttp
import jsonschema


class MemoryAPI:
    def __init__(self, config):
        self.config = config
        self.http = None

    async def request(self, endpoint, body):
        if self.http is None:
            self.http = aiohttp.ClientSession(
                trust_env=False, timeout=aiohttp.ClientTimeout(total=self.config.memory_timeout)
            )
        async with self.http.post(
            self.config.memory_base_url + endpoint,
            json=body,
            headers={"Authorization": "Bearer " + self.config.memory_api_key},
            allow_redirects=False,
        ) as response:
            if response.status != 200:
                raise RuntimeError(f"记忆模型服务 HTTP {response.status}")
            return await response.json()

    async def structured(self, system, data, schema):
        schema_name = (
            "qq_memory_"
            + hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()[:12]
        )
        for attempt in range(2):
            response = await self.request(
                "/chat/completions",
                {
                    "model": self.config.memory_model,
                    "enable_thinking": False,
                    "temperature": 0.1,
                    "max_tokens": 2500,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {"name": schema_name, "strict": True, "schema": schema},
                    },
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
                    ],
                },
            )
            try:
                choice = response["choices"][0]
                if choice.get("finish_reason") == "length":
                    raise ValueError("记忆输出被截断")
                value = json.loads(choice["message"]["content"])
                jsonschema.validate(value, schema)
                return value
            except (ValueError, KeyError, IndexError, TypeError, jsonschema.ValidationError):
                if attempt:
                    raise ValueError("记忆输出未通过 JSON 和字段校验") from None
        raise ValueError("记忆输出无效")

    async def rerank(self, query, entries):
        response = await self.request(
            "/rerank",
            {
                "model": self.config.memory_rerank_model,
                "query": query,
                "documents": [entry["content"] for entry in entries],
                "instruction": "Find personal memories relevant to the user's current question.",
                "top_n": min(5, len(entries)),
                "return_documents": False,
            },
        )
        indices = [row["index"] for row in response["results"]]
        if (
            len(indices) != len(set(indices))
            or not indices
            or any(not isinstance(index, int) or not 0 <= index < len(entries) for index in indices)
        ):
            raise ValueError("重排结果索引无效")
        return [entries[index] for index in indices]

    async def close(self):
        if self.http:
            await self.http.close()
