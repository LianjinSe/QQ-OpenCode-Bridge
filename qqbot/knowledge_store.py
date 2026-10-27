"""Durable document catalogue. Personal memory is deliberately not involved."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path


def new_id():
    return uuid.uuid4().hex


class KnowledgeStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path)
        os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS libraries (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
                owner INTEGER NOT NULL, groups_json TEXT NOT NULL DEFAULT '[]',
                created REAL NOT NULL, updated REAL NOT NULL, deleted INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, library_id TEXT NOT NULL REFERENCES libraries(id),
                filename TEXT NOT NULL, active_version TEXT, target_version TEXT,
                deleted INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS document_filename
                ON documents(library_id, filename) WHERE deleted=0;
            CREATE TABLE IF NOT EXISTS versions (
                id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
                number INTEGER NOT NULL, digest TEXT NOT NULL, bytes INTEGER NOT NULL,
                suffix TEXT NOT NULL, state TEXT NOT NULL, stage TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
                next_at REAL NOT NULL DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES versions(id),
                position INTEGER NOT NULL, page INTEGER, heading TEXT NOT NULL,
                text TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS chunks_version ON chunks(version_id, position);
            CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(id UNINDEXED, terms);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS retrievals (
                id TEXT PRIMARY KEY, job_id TEXT, library_id TEXT, created REAL NOT NULL,
                query TEXT NOT NULL, results_json TEXT NOT NULL, elapsed_ms REAL NOT NULL,
                mode TEXT NOT NULL
            );
        """)
        # Only startup performs recovery. Browsing the catalogue never constructs it.
        self.db.execute("UPDATE versions SET state='queued' WHERE state='processing'")
        self.db.commit()

    def close(self):
        self.db.close()

    def setting(self, key):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def save_setting(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)", (key, value))
        self.db.commit()

    def mark_deleting(self, version_id):
        self.db.execute("UPDATE versions SET state='deleting' WHERE id=?", (version_id,))
        self.db.commit()

    def retry_delete(self, version_id, next_at, error):
        self.db.execute(
            "UPDATE versions SET next_at=?,error=? WHERE id=?",
            (next_at, error, version_id),
        )
        self.db.commit()

    def prune_retrievals(self, before):
        self.db.execute("DELETE FROM retrievals WHERE created<?", (before,))
        self.db.commit()

    def preview_chunks(self, version_id, offset=0):
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT * FROM chunks WHERE version_id=? ORDER BY position LIMIT 51 OFFSET ?",
                (version_id, offset),
            )
        ]

    def libraries(self):
        return [
            self.library(r[0])
            for r in self.db.execute("SELECT id FROM libraries WHERE deleted=0 ORDER BY created")
        ]

    def library(self, id):
        row = self.db.execute("SELECT * FROM libraries WHERE id=? AND deleted=0", (id,)).fetchone()
        if row is None:
            raise KeyError(id)
        item = dict(row)
        item["groups"] = json.loads(item.pop("groups_json"))
        item["documents"] = self.db.execute(
            "SELECT count(*) FROM documents WHERE library_id=? AND deleted=0", (id,)
        ).fetchone()[0]
        return item

    def save_library(self, name, description, owner, groups, *, id=None):
        now = time.time()
        if id:
            self.library(id)
            self.db.execute(
                "UPDATE libraries SET name=?,description=?,groups_json=?,updated=? WHERE id=?",
                (name, description, json.dumps(groups), now, id),
            )
        else:
            id = new_id()
            self.db.execute(
                "INSERT INTO libraries (id,name,description,owner,groups_json,created,updated) "
                "VALUES (?,?,?,?,?,?,?)",
                (id, name, description, owner, json.dumps(groups), now, now),
            )
        self.db.commit()
        return self.library(id)

    def delete_library(self, id):
        for document in self.documents(id):
            self.delete_document(document["id"])
        self.db.execute("UPDATE libraries SET deleted=1,groups_json='[]' WHERE id=?", (id,))
        self.db.commit()

    def visible(self, context):
        return [
            lib
            for lib in self.libraries()
            if (context.group_id is None and context.user_id == lib["owner"])
            or (context.group_id is not None and context.group_id in lib["groups"])
        ]

    def documents(self, library_id):
        self.library(library_id)
        return [
            self.document(row[0])
            for row in self.db.execute(
                "SELECT id FROM documents WHERE library_id=? AND deleted=0 ORDER BY updated DESC",
                (library_id,),
            )
        ]

    def version(self, id):
        row = self.db.execute("SELECT * FROM versions WHERE id=?", (id,)).fetchone()
        if row is None:
            raise KeyError(id)
        return dict(row)

    def document(self, id):
        row = self.db.execute("SELECT * FROM documents WHERE id=? AND deleted=0", (id,)).fetchone()
        if row is None:
            raise KeyError(id)
        item = dict(row)
        item["versions"] = [
            dict(v)
            for v in self.db.execute(
                "SELECT * FROM versions WHERE document_id=? ORDER BY number DESC", (id,)
            )
        ]
        return item

    def enqueue(self, library_id, filename, digest, size, suffix, version_id):
        self.library(library_id)
        previous = self.db.execute(
            "SELECT * FROM documents WHERE library_id=? AND filename=? AND deleted=0",
            (library_id, filename),
        ).fetchone()
        if previous:
            for vid in (previous["target_version"],):
                if vid:
                    v = self.version(vid)
                    if v["digest"] == digest and v["state"] in {"queued", "processing", "ready"}:
                        return self.document(previous["id"]), False
        now = time.time()
        did = previous["id"] if previous else new_id()
        with self.db:
            if not previous:
                self.db.execute(
                    "INSERT INTO documents VALUES (?,?,?,NULL,NULL,0,?,?)",
                    (did, library_id, filename, now, now),
                )
            number = self.db.execute(
                "SELECT coalesce(max(number),0)+1 FROM versions WHERE document_id=?", (did,)
            ).fetchone()[0]
            self.db.execute(
                "INSERT INTO versions "
                "(id,document_id,number,digest,bytes,suffix,state,created,updated) "
                "VALUES (?,?,?,?,?,?,'queued',?,?)",
                (version_id, did, number, digest, size, suffix, now, now),
            )
            self.db.execute(
                "UPDATE documents SET target_version=?,updated=? WHERE id=?",
                (version_id, now, did),
            )
            self.db.execute(
                "UPDATE versions SET state='deleting' WHERE document_id=? AND id!=? "
                "AND id!=coalesce((SELECT active_version FROM documents WHERE id=?),'') "
                "AND state IN ('queued','processing','failed')",
                (did, version_id, did),
            )
        return self.document(did), True

    def pending(self):
        row = self.db.execute(
            "SELECT * FROM versions WHERE state IN ('deleting','queued') AND next_at<=? "
            "ORDER BY CASE state WHEN 'deleting' THEN 0 ELSE 1 END,created LIMIT 1",
            (time.time(),),
        ).fetchone()
        return dict(row) if row else None

    def current_target(self, version_id):
        return bool(
            self.db.execute(
                "SELECT 1 FROM documents WHERE target_version=? AND deleted=0", (version_id,)
            ).fetchone()
        )

    def stage(self, id, stage):
        self.db.execute(
            "UPDATE versions SET state='processing',stage=?,updated=? "
            "WHERE id=? AND state!='deleting'",
            (stage, time.time(), id),
        )
        self.db.commit()

    def failed(self, id, message, *, retry=False):
        v = self.version(id)
        attempts = v["attempts"] + 1
        self.db.execute(
            "UPDATE versions SET state=?,error=?,attempts=?,next_at=?,updated=? "
            "WHERE id=? AND state!='deleting'",
            (
                "queued" if retry and attempts < 4 else "failed",
                message,
                attempts,
                time.time() + min(300, 10 * 2**attempts),
                time.time(),
                id,
            ),
        )
        self.db.commit()

    def retry(self, document_id):
        document = self.document(document_id)
        v = self.version(document["target_version"])
        if v["state"] != "failed":
            raise ValueError("只有失败的导入可以重试")
        self.db.execute(
            "UPDATE versions SET state='queued',attempts=0,next_at=0,error='' WHERE id=?",
            (v["id"],),
        )
        self.db.commit()

    def remove_chunks(self, version_id):
        self.db.execute(
            "DELETE FROM chunk_fts WHERE id IN (SELECT id FROM chunks WHERE version_id=?)",
            (version_id,),
        )
        self.db.execute("DELETE FROM chunks WHERE version_id=?", (version_id,))

    def publish(self, version_id, chunks):
        if not self.current_target(version_id):
            return False
        v = self.version(version_id)
        with self.db:
            self.remove_chunks(version_id)
            for chunk in chunks:
                self.db.execute(
                    "INSERT INTO chunks VALUES (?,?,?,?,?,?)",
                    (
                        chunk["id"],
                        version_id,
                        chunk["position"],
                        chunk["page"],
                        chunk["heading"],
                        chunk["text"],
                    ),
                )
                self.db.execute("INSERT INTO chunk_fts VALUES (?,?)", (chunk["id"], chunk["terms"]))
            self.db.execute(
                "UPDATE versions SET state='deleting' WHERE document_id=? AND state='ready'",
                (v["document_id"],),
            )
            self.db.execute(
                "UPDATE versions SET state='ready',stage='ready',error='',updated=? WHERE id=?",
                (time.time(), version_id),
            )
            self.db.execute(
                "UPDATE documents SET active_version=?,updated=? WHERE id=?",
                (version_id, time.time(), v["document_id"]),
            )
        return True

    def delete_document(self, id):
        self.document(id)
        with self.db:
            self.db.execute(
                "UPDATE documents SET deleted=1,active_version=NULL,target_version=NULL WHERE id=?",
                (id,),
            )
            for row in self.db.execute("SELECT id FROM versions WHERE document_id=?", (id,)):
                self.remove_chunks(row[0])
            self.db.execute(
                "UPDATE versions SET state='deleting' WHERE document_id=? AND state!='deleted'",
                (id,),
            )

    def finish_delete(self, version_id):
        with self.db:
            self.remove_chunks(version_id)
            self.db.execute("UPDATE versions SET state='deleted' WHERE id=?", (version_id,))

    def active_versions(self, libraries):
        if not libraries:
            return []
        marks = ",".join("?" for _ in libraries)
        return [
            row[0]
            for row in self.db.execute(
                f"SELECT active_version FROM documents WHERE library_id IN ({marks}) "
                "AND deleted=0 AND active_version IS NOT NULL",
                tuple(libraries),
            )
        ]

    def chunk(self, id, versions):
        row = self.db.execute(
            "SELECT c.*,d.id document_id,d.filename,d.library_id,v.number version "
            "FROM chunks c JOIN versions v ON v.id=c.version_id "
            "JOIN documents d ON d.active_version=c.version_id AND d.deleted=0 WHERE c.id=?",
            (id,),
        ).fetchone()
        return dict(row) if row and row["version_id"] in versions else None

    def lexical(self, match, versions):
        if not match or not versions:
            return []
        marks = ",".join("?" for _ in versions)
        return [
            row[0]
            for row in self.db.execute(
                "SELECT c.id FROM chunk_fts f JOIN chunks c ON c.id=f.id "
                f"WHERE chunk_fts MATCH ? AND c.version_id IN ({marks}) "
                "ORDER BY bm25(chunk_fts) LIMIT 30",
                (match, *versions),
            )
        ]

    def record(self, query, rows, elapsed_ms, mode, *, job_id=None, library_id=None):
        id = new_id()
        with self.db:
            self.db.execute(
                "INSERT INTO retrievals VALUES (?,?,?,?,?,?,?,?)",
                (
                    id,
                    job_id,
                    library_id,
                    time.time(),
                    query,
                    json.dumps([r["id"] for r in rows]),
                    elapsed_ms,
                    mode,
                ),
            )
            self.db.execute("DELETE FROM retrievals WHERE created<?", (time.time() - 604800,))
        return id

    def history(self):
        items = []
        versions = self.active_versions([lib["id"] for lib in self.libraries()])
        for row in self.db.execute(
            "SELECT * FROM retrievals WHERE created>? ORDER BY created DESC LIMIT 20",
            (time.time() - 604800,),
        ):
            item = dict(row)
            ids = json.loads(item.pop("results_json"))
            item["sources"] = [c for id in ids if (c := self.chunk(id, versions))]
            items.append(item)
        return items
