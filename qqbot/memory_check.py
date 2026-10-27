"""Exercise real memory APIs and PostgreSQL in an isolated, disposable namespace."""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import psycopg2
from psycopg2 import sql

from .config import Config
from .logging_utils import configure_logging
from .memory import ZONE, PersonalMemory, datetime
from .memory_backend import Mem0Backend
from .models import Context
from .store import Store


async def verify(config):
    collection = "qq_memory_check_" + uuid.uuid4().hex[:12]
    checks = []
    with tempfile.TemporaryDirectory(prefix="qq-memory-check-") as temporary:
        cfg = replace(config, memory_enabled=True, memory_db=Path(temporary) / "memory.sqlite3")
        bridge_store = Store(Path(temporary) / "bridge.sqlite3")
        replies = []
        bridge = SimpleNamespace(
            config=cfg, store=bridge_store, reply=lambda *args: replies.append(args)
        )
        manager = PersonalMemory(
            cfg,
            bridge_store,
            SimpleNamespace(belongs_to=lambda session, root: False, turn=None),
            bridge.reply,
        )
        await manager.backend.close()
        manager.backend = Mem0Backend(cfg, collection=collection)
        context = Context(900000000, cfg.memory_owner_user_id)
        owner = manager.owner(context)

        def source(id, text):
            manager.store.archive(id, owner, "private", text)
            manager.store.mark_source_completed(id)

        def work(action, argument, id):
            source(id, argument)
            manager.store.enqueue(
                owner,
                "control",
                {
                    "action": action,
                    "argument": argument,
                    "context": context.to_dict(),
                    "key": id,
                    "source": id,
                },
                id,
            )
            return manager.store.next_work(control=True)

        def passed(name, condition):
            if not condition:
                raise AssertionError(name)
            checks.append({"name": name, "passed": True})
            print(json.dumps(checks[-1], ensure_ascii=False), flush=True)

        started = time.monotonic()
        try:
            await manager.backend.health()
            saved = work("remember", "这个合成测试用户希望被叫做松果测试员", "remember-test")
            await manager.process_control(saved)
            manager.store.finish_work(saved["id"])
            entries = manager.store.entries(owner)
            passed("explicit_save_confirmed", bool(entries) and bool(replies))
            hits = await manager.recall(owner, "这个测试用户希望怎么称呼", private=True)
            passed(
                "real_mem0_embedding_and_rerank",
                any("松果测试员" in row["content"] for row in hits),
            )
            stranger = await manager.backend.search("qq:900000000:other-user", "测试用户称呼")
            passed("database_user_isolation", stranger == [])
            bridge_store.set_session(context, "old-test-session")
            bridge_store.reset_session(context)
            id = bridge_store.enqueue(context, "你还记得我的测试称呼吗", [], config=cfg)
            prepared = await manager.prepare(bridge_store.job(id), "本次问题")
            hits = await manager.recall(owner, "测试用户的称呼", private=True)
            passed(
                "new_session_keeps_memory_without_injection",
                prepared == "本次问题" and any("松果测试员" in row["content"] for row in hits),
            )
            await manager.close()
            manager = PersonalMemory(
                cfg,
                bridge_store,
                SimpleNamespace(belongs_to=lambda session, root: False, turn=None),
                bridge.reply,
            )
            await manager.backend.close()
            manager.backend = Mem0Backend(cfg, collection=collection)
            hits = await manager.recall(owner, "测试用户的称呼", private=True)
            passed("restart_keeps_memory", any("松果测试员" in row["content"] for row in hits))
            forgotten = work("forget", "松果测试员", "forget-test")
            await manager.process_control(forgotten)
            manager.store.finish_work(forgotten["id"])
            passed(
                "forget_removes_ledger_and_vector",
                not manager.store.entries(owner)
                and not await manager.backend.search(owner, "松果测试员"),
            )
            passed(
                "forgotten_source_is_blocked",
                bool(manager.store.source("remember-test")["suppressed"]),
            )
            source("daily-test", "这是合成对话：我今天在开发QQ机器人，刚加班回来有一点累。")
            manager.store.enqueue(
                owner,
                "control",
                {
                    "tool": "remember",
                    "arguments": {
                        "content": "用户在开发QQ机器人",
                        "evidence": "我今天在开发QQ机器人",
                    },
                    "context": context.to_dict(),
                    "private": True,
                    "source": "daily-test",
                    "key": "tool-save-check",
                },
                "tool-save-check",
            )
            tool_work = manager.store.next_work(control=True)
            result = await manager.tools.process(tool_work)
            manager.store.finish_work(tool_work["id"], result)
            passed(
                "agent_selected_memory_write", result["ok"] and bool(manager.store.entries(owner))
            )
            day = datetime.now(ZONE).strftime("%Y-%m-%d")
            manager.schedule_day(owner, day)
            diary = manager.store.latest_work("diary")
            await manager.diary(diary)
            journals = manager.store.entries(owner, kinds=["diary"])
            passed(
                "daily_diary_with_sources",
                bool(journals) and all(json.loads(row["sources"]) for row in journals),
            )
            passed(
                "forgotten_detail_absent_from_diary",
                all("松果测试员" not in row["content"] for row in journals),
            )
            report = {
                "passed": True,
                "checks": checks,
                "seconds": round(time.monotonic() - started, 2),
                "collection": collection,
                "synthetic_data_only": True,
            }
        finally:
            await manager.close()
            bridge_store.close()
            with psycopg2.connect(cfg.memory_database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(
                            sql.Identifier(collection)
                        )
                    )
        return report


def main():
    config = Config.from_env()
    configure_logging("WARNING", config.memory_api_key, config.memory_database_url)
    report = asyncio.run(verify(config))
    path = config.memory_db.with_name("memory-check-latest.json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    path.chmod(0o600)
    print(
        json.dumps(
            {"passed": report["passed"], "checks": len(report["checks"]), "report": str(path)},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
