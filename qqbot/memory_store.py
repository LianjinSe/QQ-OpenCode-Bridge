"""Owner-scoped source archive, durable work queue, and memory policy ledger."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path


class MemoryStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path)
        os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS owners (
                owner TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS archive (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, scope TEXT NOT NULL,
                group_id INTEGER, user_text TEXT NOT NULL, assistant_text TEXT NOT NULL DEFAULT '',
                created REAL NOT NULL, completed INTEGER NOT NULL DEFAULT 0,
                suppressed INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS archive_owner_time ON archive(owner,created);
            CREATE TABLE IF NOT EXISTS entries (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, content TEXT NOT NULL,
                kind TEXT NOT NULL, scope TEXT NOT NULL, sources TEXT NOT NULL,
                fact_key TEXT NOT NULL DEFAULT '', pinned INTEGER NOT NULL DEFAULT 0,
                expires REAL, backend_id TEXT, state TEXT NOT NULL DEFAULT 'pending',
                created REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS entries_owner ON entries(owner,state,kind);
            CREATE TABLE IF NOT EXISTS work (
                id INTEGER PRIMARY KEY, dedupe TEXT NOT NULL UNIQUE, owner TEXT NOT NULL,
                kind TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'ready',
                attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL DEFAULT 0,
                error TEXT, created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS forgotten (
                id INTEGER PRIMARY KEY, owner TEXT NOT NULL, query TEXT NOT NULL,
                content TEXT NOT NULL, created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memory_evidence (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, job_id TEXT NOT NULL,
                source_id TEXT NOT NULL, kind TEXT NOT NULL, excerpt TEXT NOT NULL,
                reference TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS evidence_owner ON memory_evidence(owner,job_id);
        """)
        entry_columns = {row["name"] for row in self.db.execute("PRAGMA table_info(entries)")}
        if "subject" not in entry_columns:
            self.db.execute("ALTER TABLE entries ADD COLUMN subject TEXT NOT NULL DEFAULT 'user'")
            self.db.execute("UPDATE entries SET subject='shared' WHERE kind='diary'")
        if "evidence" not in entry_columns:
            self.db.execute("ALTER TABLE entries ADD COLUMN evidence TEXT NOT NULL DEFAULT '[]'")
        forgotten_columns = {row["name"] for row in self.db.execute("PRAGMA table_info(forgotten)")}
        for name, default in (("subject", "user"), ("kind", "profile")):
            if name not in forgotten_columns:
                self.db.execute(
                    f"ALTER TABLE forgotten ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'"
                )
                self.db.execute(
                    f"UPDATE forgotten SET {name}=COALESCE((SELECT {name} FROM entries "
                    "WHERE entries.owner=forgotten.owner AND entries.content=forgotten.content "
                    f"ORDER BY created DESC LIMIT 1),'{default}')"
                )
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(work)")}
        if "result" not in columns:
            self.db.execute("ALTER TABLE work ADD COLUMN result TEXT")
        self.db.execute("UPDATE work SET state='ready' WHERE state='running'")
        self.db.commit()

    def close(self):
        self.db.close()

    def revision(self, owner: str) -> int:
        self.db.execute("INSERT OR IGNORE INTO owners(owner) VALUES (?)", (owner,))
        self.db.commit()
        return self.db.execute("SELECT revision FROM owners WHERE owner=?", (owner,)).fetchone()[0]

    def archive(self, id: str, owner: str, scope: str, text: str, *, group_id=None, created=None):
        revision = self.revision(owner)
        self.db.execute(
            "INSERT OR IGNORE INTO archive(id,owner,scope,group_id,user_text,created,revision) "
            "VALUES (?,?,?,?,?,?,?)",
            (id, owner, scope, group_id, text, created or time.time(), revision),
        )
        self.db.commit()

    def source(self, id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM archive WHERE id=?", (id,)).fetchone()
        return dict(row) if row else None

    def mark_source_completed(self, id):
        self.db.execute("UPDATE archive SET completed=1 WHERE id=?", (id,))
        self.db.commit()

    def latest_work(self, kind):
        row = self.db.execute("SELECT * FROM work WHERE kind=? ORDER BY id DESC LIMIT 1", (kind,))
        row = row.fetchone()
        if not row:
            return None
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        return result

    def history_search(self, owner, private, query, *, limit=3):
        rows = self.db.execute(
            "SELECT * FROM archive WHERE owner=? AND suppressed=0 AND completed=1 "
            "AND (? OR scope='group') AND (instr(user_text,?) OR instr(assistant_text,?)) "
            "ORDER BY created DESC LIMIT ?",
            (owner, int(private), query, query, limit),
        )
        return [dict(row) for row in rows]

    def search_sources(self, owner, private, query, *, limit=4):
        rows = self.db.execute(
            "SELECT * FROM archive WHERE owner=? AND completed=1 AND suppressed=0 "
            "AND (? OR scope='group') AND (instr(lower(user_text),lower(?)) "
            "OR instr(lower(assistant_text),lower(?))) ORDER BY created DESC LIMIT ?",
            (owner, int(private), query, query, limit),
        )
        return [dict(row) for row in rows]

    def saved_evidence(self, source_id, owner, *, limit=8):
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT * FROM memory_evidence WHERE source_id=? AND owner=? AND used=1 "
                "AND excerpt!='' ORDER BY created DESC LIMIT ?",
                (source_id, owner, limit),
            )
        ]

    def evidence(self, id):
        row = self.db.execute("SELECT * FROM memory_evidence WHERE id=?", (id,)).fetchone()
        return dict(row) if row else None

    def remember_evidence(self, id, owner, job_id, source_id, kind, excerpt, reference, created):
        self.db.execute(
            "INSERT OR IGNORE INTO memory_evidence "
            "(id,owner,job_id,source_id,kind,excerpt,reference,created) VALUES (?,?,?,?,?,?,?,?)",
            (id, owner, job_id, source_id, kind, excerpt, reference, created),
        )

    def mark_evidence_used(self, ids):
        self.db.executemany("UPDATE memory_evidence SET used=1 WHERE id=?", [(id,) for id in ids])

    def restore_forgotten(self, ids):
        self.db.executemany("DELETE FROM forgotten WHERE id=?", [(id,) for id in ids])
        self.db.commit()

    def commit(self):
        self.db.commit()

    def work_by_dedupe(self, dedupe):
        row = self.db.execute("SELECT * FROM work WHERE dedupe=?", (dedupe,)).fetchone()
        return dict(row) if row else None

    def work_item(self, id):
        row = self.db.execute("SELECT * FROM work WHERE id=?", (id,)).fetchone()
        return dict(row) if row else None

    def save_work_payload(self, id, payload):
        self.db.execute(
            "UPDATE work SET payload=? WHERE id=?",
            (json.dumps(payload, ensure_ascii=False), id),
        )
        self.db.commit()

    def complete(self, id: str, assistant: str, *, extract: bool = False):
        with self.db:
            self.db.execute(
                "UPDATE archive SET assistant_text=?,completed=1 WHERE id=?", (assistant, id)
            )
            source = self.source(id)
            if extract and source and not source["suppressed"]:
                self.enqueue(
                    source["owner"], "extract", {"source": id}, "extract:" + id, commit=False
                )

    def pending_control(self, owner):
        return (
            self.db.execute(
                "SELECT 1 FROM work WHERE owner=? AND kind='control' "
                "AND state IN ('ready','running') LIMIT 1",
                (owner,),
            ).fetchone()
            is not None
        )

    def retry_failed(self, owner):
        self.db.execute(
            "UPDATE work SET state='ready',attempts=0,next_at=0 WHERE owner=? AND state='failed'",
            (owner,),
        )
        self.db.commit()

    def complete_control_source(self, id, *, suppressed=False):
        self.db.execute(
            "UPDATE archive SET completed=1,suppressed=? WHERE id=?", (int(suppressed), id)
        )
        self.db.commit()

    def update_entry_sources(self, id, sources, evidence, *, pin=False, kind=None, fact_key=None):
        if pin:
            self.db.execute(
                "UPDATE entries SET pinned=1,kind=?,fact_key=?,sources=?,evidence=? WHERE id=?",
                (kind, fact_key, json.dumps(sources), json.dumps(evidence), id),
            )
        else:
            self.db.execute(
                "UPDATE entries SET sources=?,evidence=? WHERE id=?",
                (json.dumps(sources), json.dumps(evidence), id),
            )

    def delete_other_fact_entries(self, owner, fact_key, subject, keep_id):
        self.db.execute(
            "UPDATE entries SET state='deleted' WHERE owner=? AND fact_key=? "
            "AND subject=? AND id!=?",
            (owner, fact_key, subject, keep_id),
        )

    def merge_duplicate_entry(
        self,
        id,
        owner,
        fact_key,
        subject,
        sources,
        evidence,
        *,
        pin=False,
        kind=None,
        replace=False,
    ):
        with self.db:
            self.update_entry_sources(id, sources, evidence, pin=pin, kind=kind, fact_key=fact_key)
            if replace and fact_key:
                self.delete_other_fact_entries(owner, fact_key, subject, id)

    def update_archive_reply(self, id, assistant):
        self.db.execute("UPDATE archive SET assistant_text=? WHERE id=?", (assistant, id))
        self.db.commit()

    def suppress_source(self, id, owner):
        self.db.execute("UPDATE archive SET suppressed=1 WHERE id=? AND owner=?", (id, owner))
        self.db.commit()

    def purge_sources(self, owner, ids):
        with self.db:
            self.db.executemany(
                "UPDATE archive SET user_text='',assistant_text='',suppressed=1 "
                "WHERE id=? AND owner=?",
                [(id, owner) for id in ids],
            )
            self.db.executemany(
                "UPDATE memory_evidence SET excerpt='' WHERE source_id=? AND owner=?",
                [(id, owner) for id in ids],
            )

    def incomplete_sources(self):
        return [dict(row) for row in self.db.execute("SELECT id FROM archive WHERE completed=0")]

    def complete_failed_source(self, id, assistant):
        self.db.execute(
            "UPDATE archive SET completed=1,assistant_text=? WHERE id=?", (assistant, id)
        )
        self.db.commit()

    def deleted_backend_entries(self, owner):
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT * FROM entries WHERE owner=? AND state IN ('deleted','expired') "
                "AND backend_id IS NOT NULL LIMIT 100",
                (owner,),
            )
        ]

    def clear_backend_id(self, id):
        self.db.execute("UPDATE entries SET backend_id=NULL WHERE id=?", (id,))
        self.db.commit()

    def maintenance_expire(self, before):
        with self.db:
            self.db.execute("DELETE FROM memory_evidence WHERE used=0 AND created<?", (before,))
            self.db.execute(
                "UPDATE entries SET state='expired' WHERE state='active' "
                "AND expires IS NOT NULL AND expires<=?",
                (time.time(),),
            )

    def journal_candidates(self, before):
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT DISTINCT owner,strftime('%Y-%m-%d',created,'unixepoch','+8 hours') AS day "
                "FROM archive WHERE completed=1 AND suppressed=0 AND created<?",
                (before,),
            )
        ]

    def owners(self):
        return [row[0] for row in self.db.execute("SELECT owner FROM owners")]

    def enqueue(self, owner: str, kind: str, payload: dict, dedupe: str, *, commit=True):
        self.db.execute(
            "INSERT OR IGNORE INTO work(owner,kind,payload,dedupe,created) VALUES (?,?,?,?,?)",
            (owner, kind, json.dumps(payload, ensure_ascii=False), dedupe, time.time()),
        )
        if commit:
            self.db.commit()

    def next_work(self, *, control=False) -> dict | None:
        operator = "=" if control else "!="
        row = self.db.execute(
            f"SELECT * FROM work WHERE state='ready' AND kind{operator}'control' "
            "AND next_at<=? ORDER BY CASE kind WHEN 'extract' THEN 0 ELSE 1 END,id LIMIT 1",
            (time.time(),),
        ).fetchone()
        if not row:
            return None
        with self.db:
            self.db.execute(
                "UPDATE work SET state='running',attempts=attempts+1 WHERE id=?", (row["id"],)
            )
        result = dict(row)
        result["attempts"] += 1
        result["payload"] = json.loads(result["payload"])
        return result

    def finish_work(self, id: int, result=None):
        self.db.execute(
            "UPDATE work SET state='done',error=NULL,result=? WHERE id=?",
            (json.dumps(result, ensure_ascii=False) if result is not None else None, id),
        )
        self.db.commit()

    def fail_work(self, work: dict, reason: str):
        terminal = work["attempts"] >= 5
        self.db.execute(
            "UPDATE work SET state=?,error=?,next_at=? WHERE id=?",
            (
                "failed" if terminal else "ready",
                reason[:300],
                time.time() + min(300, 5 * 2 ** work["attempts"]),
                work["id"],
            ),
        )
        self.db.commit()
        return terminal

    def entry(self, id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM entries WHERE id=?", (id,)).fetchone()
        return dict(row) if row else None

    def entries(self, owner: str, *, private=True, kinds=None, limit=100) -> list[dict]:
        sql = (
            "SELECT * FROM entries WHERE owner=? AND state='active' "
            "AND (expires IS NULL OR expires>?)"
        )
        args: list = [owner, time.time()]
        if not private:
            sql += " AND scope='group'"
        if kinds:
            sql += " AND kind IN (" + ",".join("?" for _ in kinds) + ")"
            args.extend(kinds)
        sql += " ORDER BY pinned DESC,created DESC LIMIT ?"
        return [dict(row) for row in self.db.execute(sql, [*args, limit])]

    def prepare_entry(
        self,
        owner,
        content,
        kind,
        scope,
        sources,
        *,
        fact_key="",
        pinned=False,
        expires=None,
        subject="user",
        evidence_ids=(),
    ) -> dict:
        identity = json.dumps(
            [owner, subject, content, kind, scope, sorted(sources)], ensure_ascii=False
        )
        id = hashlib.sha256(identity.encode()).hexdigest()
        self.db.execute(
            "INSERT OR IGNORE INTO entries "
            "(id,owner,content,kind,scope,sources,fact_key,pinned,expires,created,"
            "subject,evidence) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                id,
                owner,
                content,
                kind,
                scope,
                json.dumps(sources),
                fact_key,
                int(pinned),
                expires,
                time.time(),
                subject,
                json.dumps(list(evidence_ids)),
            ),
        )
        self.db.commit()
        return self.entry(id)

    def activate(self, id: str, backend_id: str):
        self.db.execute(
            "UPDATE entries SET backend_id=?,state='active' WHERE id=?", (backend_id, id)
        )
        self.db.commit()

    def deactivate(self, ids: list[str]):
        with self.db:
            self.db.executemany(
                "UPDATE entries SET state='deleted' WHERE id=?", [(id,) for id in ids]
            )

    def tombstones(self, owner: str) -> list[dict]:
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT * FROM forgotten WHERE owner=? ORDER BY id DESC", (owner,)
            )
        ]

    def forget(self, owner: str, query: str, selected: list[dict]):
        source_ids = {id for entry in selected for id in json.loads(entry["sources"])}
        # Delete derived summaries that used a forgotten source, even when their text differs.
        related = [
            entry
            for entry in self.entries(owner, limit=100000)
            if entry["kind"] == "diary" and source_ids.intersection(json.loads(entry["sources"]))
        ]
        all_entries = {entry["id"]: entry for entry in [*selected, *related]}
        with self.db:
            self.db.execute("UPDATE owners SET revision=revision+1 WHERE owner=?", (owner,))
            for entry in all_entries.values():
                self.db.execute("UPDATE entries SET state='deleted' WHERE id=?", (entry["id"],))
                self.db.execute(
                    "INSERT INTO forgotten(owner,query,content,created,subject,kind) "
                    "VALUES (?,?,?,?,?,?)",
                    (owner, query, entry["content"], time.time(), entry["subject"], entry["kind"]),
                )
            self.db.executemany(
                "UPDATE archive SET suppressed=1 WHERE id=? AND owner=?",
                [(id, owner) for id in source_ids],
            )
            # Earlier list/history replies can quote a now-forgotten fact too.
            for phrase in {query, *(entry["content"] for entry in selected)}:
                self.db.execute(
                    "UPDATE archive SET suppressed=1 WHERE owner=? "
                    "AND (instr(user_text,?)>0 OR instr(assistant_text,?)>0)",
                    (owner, phrase, phrase),
                )
        return list(all_entries.values())

    def sources_for(self, owner: str, ids: list[str], *, private=True, limit=4) -> list[dict]:
        result = []
        for id in dict.fromkeys(ids):
            row = self.source(id)
            if (
                row
                and row["owner"] == owner
                and not row["suppressed"]
                and (private or row["scope"] == "group")
            ):
                result.append(row)
            if len(result) == limit:
                break
        return result

    def day_sources(self, owner: str, start: float, end: float) -> list[dict]:
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT * FROM archive WHERE owner=? AND completed=1 AND suppressed=0 "
                "AND created>=? AND created<? ORDER BY created",
                (owner, start, end),
            )
        ]

    def status(self, owner: str) -> dict:
        counts = {}
        for table in ("archive", "entries", "work"):
            suffix = " AND state='active'" if table == "entries" else ""
            if table == "work":
                suffix = " AND state IN ('ready','running','failed')"
            counts[table] = self.db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE owner=?{suffix}", (owner,)
            ).fetchone()[0]
        return counts
