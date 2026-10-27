from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from pathlib import Path

from .job_state import (
    ACTIVE_TOOL_STATUSES,
    RUNNABLE_STATUSES,
    TERMINAL_STATUSES,
    JobStatus,
    validate_transition,
)
from .models import Attachment, Context, unique_attachments

TERMINAL = {status.value for status in TERMINAL_STATUSES}
JOB_STATUSES = {status.value for status in JobStatus}


class Store:
    """One process owns a durable queue, session mapping, interactions, and outbox."""

    def __init__(self, path: Path, *, initialize: bool = True):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = open(str(path) + ".lock", "a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError("已有桥接进程使用此 STATE_DB") from None
        try:
            self.db = sqlite3.connect(path)
        except BaseException:
            fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()
            raise
        self.closed = False
        self.initialized = False
        if initialize:
            try:
                self.initialize()
            except BaseException:
                self.close()
                raise

    def initialize(self) -> None:
        """Apply schema migrations and crash recovery exactly once at startup."""
        if self.initialized:
            return
        os.chmod(self.path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS sessions (
                context TEXT PRIMARY KEY, session_id TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS seen (
                context TEXT, event_id TEXT, created REAL NOT NULL,
                PRIMARY KEY(context, event_id)
            );
            CREATE TABLE IF NOT EXISTS staging (
                context TEXT, reference TEXT, payload TEXT, expires REAL,
                PRIMARY KEY(context, reference)
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, context TEXT NOT NULL, target TEXT NOT NULL,
                text TEXT NOT NULL, attachments TEXT NOT NULL, files TEXT,
                session_id TEXT, prompt_id TEXT NOT NULL, status TEXT NOT NULL,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                elapsed REAL NOT NULL DEFAULT 0, created REAL NOT NULL,
                result TEXT, error TEXT
            );
            CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status, created);
            CREATE TABLE IF NOT EXISTS interactions (
                code TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
                kind TEXT NOT NULL, session_id TEXT NOT NULL, remote_id TEXT NOT NULL,
                payload TEXT NOT NULL, answers TEXT NOT NULL DEFAULT '{}',
                created REAL NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                UNIQUE(job_id, kind, remote_id)
            );
            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY, dedupe_key TEXT NOT NULL UNIQUE,
                job_id TEXT REFERENCES jobs(id), target TEXT NOT NULL, text TEXT NOT NULL,
                first_chunk INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'ready',
                message_id TEXT, created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assistant_output_cursors (
                job_id TEXT NOT NULL REFERENCES jobs(id), message_id TEXT NOT NULL,
                part_index INTEGER NOT NULL, prefix TEXT NOT NULL,
                PRIMARY KEY(job_id,message_id,part_index)
            );
        """)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS group_sessions (
                conversation TEXT PRIMARY KEY, session_id TEXT,
                generation INTEGER NOT NULL DEFAULT 1,
                background_start INTEGER NOT NULL DEFAULT 0,
                cursor INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS group_messages (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, conversation TEXT NOT NULL,
                generation INTEGER NOT NULL, event_id TEXT NOT NULL,
                payload TEXT NOT NULL, created REAL NOT NULL,
                UNIQUE(conversation,event_id)
            );
            CREATE INDEX IF NOT EXISTS group_messages_scope ON group_messages(conversation,seq);
            CREATE TABLE IF NOT EXISTS diagnostic_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, conversation TEXT NOT NULL,
                event_id TEXT NOT NULL, user_id INTEGER NOT NULL, job_id TEXT,
                stage TEXT NOT NULL, reason TEXT NOT NULL, created REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS diagnostic_scope
                ON diagnostic_events(conversation,event_id,id);
        """)
        columns = {r["name"] for r in self.db.execute("PRAGMA table_info(jobs)")}
        for name, sql_type in {
            "conversation": "TEXT",
            "generation": "INTEGER",
            "source_event": "TEXT",
            "background_cutoff": "INTEGER",
            "background_snapshot": "TEXT",
            "submitted_text": "TEXT",
            "submit_cursor": "INTEGER",
            "admitted": "INTEGER NOT NULL DEFAULT 0",
            "source_payload": "TEXT",
            "memory_isolated": "INTEGER NOT NULL DEFAULT 0",
            "memory_source_text": "TEXT",
            "memory_capture": "INTEGER NOT NULL DEFAULT 0",
            "memory_archived": "INTEGER NOT NULL DEFAULT 0",
            "steer_parent_id": "TEXT REFERENCES jobs(id)",
        }.items():
            if name not in columns:
                self.db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {sql_type}")
        # Legacy jobs retain their per-member sessions and are never silently reassigned.
        self.db.execute("UPDATE jobs SET conversation=context WHERE conversation IS NULL")
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS jobs_conversation ON jobs(conversation,created)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS jobs_steer_parent ON jobs(steer_parent_id,created)"
        )
        self.db.commit()
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(outbox)")}
        if "kind" not in columns:
            self.db.execute("ALTER TABLE outbox ADD COLUMN kind TEXT NOT NULL DEFAULT 'text'")
        if "payload" not in columns:
            self.db.execute("ALTER TABLE outbox ADD COLUMN payload TEXT NOT NULL DEFAULT '{}'")
        # Uploading only populates the NapCat cache; no QQ message has been sent yet.
        self.db.execute("UPDATE outbox SET status='ready' WHERE status='uploading'")
        # A process may have died after sending but before recording the response.
        self.db.execute("UPDATE outbox SET status='uncertain' WHERE status='sending'")
        # Completion pokes were retired. Keep attempted receipts, suppress unsent legacy ones.
        self.db.execute("UPDATE outbox SET status='blocked' WHERE kind='poke' AND status='ready'")
        self.db.commit()
        for row in self.db.execute(
            "SELECT id FROM jobs WHERE status IN ('reply_ready','delivering')"
        ).fetchall():
            # Recover a crash after the final send was acknowledged but before completion.
            self.finish_delivery(row["id"])

        self.initialized = True

    def close(self) -> None:
        if getattr(self, "closed", False):
            return
        self.closed = True
        self.db.close()
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.lock.close()

    def claim_event(self, context: Context, event_id: str) -> bool:
        self.db.execute("DELETE FROM seen WHERE created < ?", (time.time() - 86400,))
        cursor = self.db.execute(
            "INSERT OR IGNORE INTO seen VALUES (?,?,?)",
            (context.conversation_key, event_id, time.time()),
        )
        self.db.commit()
        return cursor.rowcount == 1

    def stage(
        self, context: Context, attachments: list[Attachment], ttl: float, limit: int
    ) -> None:
        self.db.execute("DELETE FROM staging WHERE expires < ?", (time.time(),))
        current = self.staged(context)
        for item in unique_attachments(current + attachments)[-limit:]:
            self.db.execute(
                "INSERT OR REPLACE INTO staging VALUES (?,?,?,?)",
                (context.key, item.reference, json.dumps(item.to_dict()), time.time() + ttl),
            )
        allowed = {a.reference for a in unique_attachments(current + attachments)[-limit:]}
        for row in self.db.execute(
            "SELECT reference FROM staging WHERE context=?", (context.key,)
        ).fetchall():
            if row["reference"] not in allowed:
                self.db.execute(
                    "DELETE FROM staging WHERE context=? AND reference=?",
                    (context.key, row["reference"]),
                )
        self.db.commit()

    def staged(self, context: Context) -> list[Attachment]:
        return [
            Attachment(**json.loads(row["payload"]))
            for row in self.db.execute(
                "SELECT payload FROM staging WHERE context=? AND expires>? ORDER BY rowid",
                (context.key, time.time()),
            )
        ]

    def clear_staging(self, context: Context) -> None:
        self.db.execute("DELETE FROM staging WHERE context=?", (context.key,))
        self.db.commit()

    def enqueue(
        self,
        context: Context,
        text: str,
        attachments: list[Attachment],
        *,
        incoming=None,
        config=None,
        steer_parent_id: str | None = None,
    ) -> str:
        job_id = uuid.uuid4().hex
        with self.db:
            if steer_parent_id is not None:
                parent = self.job(steer_parent_id)
                if (
                    context.group_id is not None
                    or parent["context"] != context.key
                    or parent["steer_parent_id"] is not None
                    or parent["cancel_requested"]
                    or parent["status"] not in {"preparing", "submitting", "running", "waiting"}
                ):
                    raise ValueError("插话必须属于同一私聊的活动任务")
            generation, cutoff, snapshot, source = None, 0, [], {}
            if context.group_id is not None:
                state = self.group_state(context)
                generation = state["generation"]
                if incoming is not None:
                    cutoff = self.record_group(incoming, commit=False)
                    source = json.loads(
                        self.db.execute(
                            "SELECT payload FROM group_messages WHERE seq=?", (cutoff,)
                        ).fetchone()[0]
                    )
                if cutoff and config is not None:
                    snapshot = [
                        dict(r)
                        for r in self.db.execute(
                            """SELECT seq,payload FROM group_messages WHERE conversation=?
                        AND generation=? AND seq>? AND seq<? AND created>=?
                        ORDER BY seq DESC LIMIT ?""",
                            (
                                context.conversation_key,
                                generation,
                                state["background_start"],
                                cutoff,
                                time.time() - config.group_background_ttl_seconds,
                                config.group_background_max_messages,
                            ),
                        )
                    ][::-1]
            self.db.execute(
                """INSERT INTO jobs
                (id,context,target,text,attachments,prompt_id,status,created,conversation,
                 generation,source_event,background_cutoff,background_snapshot,source_payload,
                 memory_isolated,memory_source_text,memory_capture,steer_parent_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    job_id,
                    context.key,
                    json.dumps(context.to_dict()),
                    text,
                    json.dumps([a.to_dict() for a in attachments]),
                    "msg_" + uuid.uuid4().hex,
                    "steering" if steer_parent_id is not None else "queued",
                    time.time(),
                    context.conversation_key,
                    generation,
                    incoming.event_id if incoming else None,
                    cutoff,
                    json.dumps(snapshot, ensure_ascii=False),
                    json.dumps(source, ensure_ascii=False),
                    int(
                        bool(
                            config
                            and config.memory_enabled
                            and context.group_id is not None
                            and context.user_id == config.memory_owner_user_id
                        )
                    ),
                    incoming.text if incoming is not None else text,
                    int(
                        bool(
                            config
                            and config.memory_enabled
                            and context.user_id == config.memory_owner_user_id
                        )
                    ),
                    steer_parent_id,
                ),
            )
        return job_id

    def job(self, job_id: str) -> dict:
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return dict(row)

    def active_tool_jobs(self) -> list[dict]:
        """Snapshot active root jobs that may own a native tool call."""
        placeholders = ",".join("?" for _ in ACTIVE_TOOL_STATUSES)
        return [
            dict(row)
            for row in self.db.execute(
                f"""SELECT id,session_id,target,status,cancel_requested FROM jobs
                WHERE steer_parent_id IS NULL
                  AND status IN ({placeholders})
                  AND cancel_requested=0 AND session_id IS NOT NULL
                ORDER BY created DESC""",
                tuple(state.value for state in ACTIVE_TOOL_STATUSES),
            )
        ]

    def job_capture(self, job_id: str) -> dict:
        row = self.db.execute(
            "SELECT id,created,status,result,memory_archived,memory_isolated,memory_source_text,"
            "memory_capture,source_event,source_payload,target,text,steer_parent_id "
            "FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return dict(row)

    def memory_archive_candidates(self) -> list[dict]:
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT id,created,status,memory_archived,memory_isolated,memory_capture,"
                "memory_source_text,text,target,result "
                "FROM jobs WHERE memory_archived=0 ORDER BY created"
            )
        ]

    def clear_unadmitted_memory_capture(self, user_id: int, self_id: int) -> None:
        self.db.execute(
            "UPDATE jobs SET submitted_text=NULL WHERE admitted=0 AND memory_capture=1 "
            "AND json_extract(target,'$.user_id')=? AND json_extract(target,'$.self_id')=?",
            (user_id, self_id),
        )
        self.db.commit()

    def conversation_memory_events(self, job_id: str) -> list[dict]:
        """Return submitted source and steer inputs belonging to a task tree."""
        root = self.job(job_id)
        root_id = root["steer_parent_id"] or root["id"]
        rows = self.db.execute(
            "SELECT * FROM jobs WHERE id=? OR steer_parent_id=? ORDER BY created,rowid",
            (root_id, root_id),
        )
        return [
            {
                "id": row["id"],
                "job_id": row["id"],
                "kind": "steer" if row["steer_parent_id"] else "source",
                "stage": row["status"],
                "content": row["submitted_text"] or row["text"],
                "source": row["source_event"],
                "time": row["created"],
            }
            for row in rows
        ]

    def outbox_status(self, outbox_id: int) -> str:
        row = self.db.execute("SELECT status FROM outbox WHERE id=?", (outbox_id,)).fetchone()
        if row is None:
            raise KeyError(outbox_id)
        return row["status"]

    def group_state_for_compose(self, context: Context) -> dict:
        state = self.group_state(context)
        self.db.commit()
        return state

    def record_diagnostic(
        self,
        conversation: str,
        event_id: str,
        user_id: int,
        stage: str,
        reason: str,
        job_id: str | None,
        created: float,
    ) -> float | None:
        """Deduplicate and persist one event stage; return its first timestamp."""
        previous = self.db.execute(
            """SELECT stage,reason FROM diagnostic_events
            WHERE conversation=? AND event_id=? ORDER BY id DESC LIMIT 1""",
            (conversation, event_id),
        ).fetchone()
        if previous and tuple(previous) == (stage, reason):
            return None
        self.db.execute(
            """INSERT INTO diagnostic_events
            (conversation,event_id,user_id,job_id,stage,reason,created) VALUES (?,?,?,?,?,?,?)""",
            (conversation, event_id, user_id, job_id, stage, reason, created),
        )
        self.db.commit()
        row = self.db.execute(
            "SELECT MIN(created) FROM diagnostic_events WHERE conversation=? AND event_id=?",
            (conversation, event_id),
        ).fetchone()
        return row[0]

    def next_job(self) -> dict | None:
        placeholders = ",".join("?" for _ in RUNNABLE_STATUSES)
        row = self.db.execute(
            f"""SELECT * FROM jobs WHERE status IN ({placeholders})
               ORDER BY CASE WHEN status='queued' THEN 1 ELSE 0 END, created LIMIT 1""",
            tuple(state.value for state in RUNNABLE_STATUSES),
        ).fetchone()
        return dict(row) if row else None

    def typing_context(self, self_id: int) -> Context | None:
        for row in self.db.execute(
            """SELECT target FROM jobs WHERE status IN ('preparing','submitting','running')
               AND cancel_requested=0 ORDER BY created"""
        ):
            context = Context(**json.loads(row["target"]))
            if context.self_id == self_id:
                return context if context.group_id is None else None
        return None

    def update_job(self, job_id: str, **fields) -> None:
        allowed = {
            "status",
            "session_id",
            "files",
            "elapsed",
            "result",
            "error",
            "cancel_requested",
            "submitted_text",
            "submit_cursor",
            "memory_archived",
        }
        if not fields.keys() <= allowed:
            raise ValueError("Invalid job update")
        if "status" in fields and fields["status"] not in JOB_STATUSES:
            raise ValueError(f"Invalid job status: {fields['status']}")
        if "status" in fields:
            validate_transition(self.job(job_id)["status"], fields["status"])
        self.db.execute(
            "UPDATE jobs SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?",
            (*fields.values(), job_id),
        )
        if fields.get("status") in TERMINAL:
            self._settle_steers(job_id, fields["status"])
        self.db.commit()

    def transition_job(self, job_id: str, status: str, **fields) -> None:
        """Apply one legal task state transition with its associated field updates."""
        current = self.job(job_id)["status"]
        validate_transition(current, status)
        self.update_job(job_id, status=status, **fields)

    def steers(self, job_id: str, *, pending_only=False) -> list[dict]:
        sql = "SELECT * FROM jobs WHERE steer_parent_id=?"
        if pending_only:
            sql += " AND status='steering'"
        return [dict(row) for row in self.db.execute(sql + " ORDER BY created,rowid", (job_id,))]

    def _settle_steers(self, job_id: str, status: str) -> None:
        # Inputs share one execution and delivery; they never create their own reply.
        self.db.execute(
            "UPDATE jobs SET status=? WHERE steer_parent_id=? AND status IN ('steering','steered')",
            (status, job_id),
        )

    def unfinished(self, context: Context) -> list[dict]:
        return [
            dict(row)
            for row in self.db.execute(
                """SELECT * FROM jobs WHERE context=? AND status IN
                   ('queued','preparing','submitting','running','waiting','cancelling','delivering')
                   ORDER BY created""",
                (context.key,),
            )
        ]

    def latest(self, context: Context) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM jobs WHERE context=? AND steer_parent_id IS NULL "
            "ORDER BY created DESC LIMIT 1",
            (context.key,),
        ).fetchone()
        return dict(row) if row else None

    def cancel_context(self, context: Context, *, all_members=False) -> int:
        rows = self.conversation_jobs(context)
        if not all_members:
            rows = [r for r in rows if json.loads(r["target"])["user_id"] == context.user_id]
        for row in rows:
            self.cancel_job(row["id"])
        self.clear_staging(context)
        return len(rows)

    def cancel_job(self, job_id: str) -> None:
        row = self.job(job_id)
        if row is None:
            raise KeyError(job_id)
        if row["status"] in TERMINAL:
            return
        if row["status"] in {"delivering", "reply_ready"}:
            self.db.execute(
                "UPDATE outbox SET status='blocked' WHERE job_id=? "
                "AND status IN ('ready','uploading')",
                (job_id,),
            )
        self.update_job(
            job_id,
            cancel_requested=1,
            status="cancelled"
            if row["status"] in {"queued", "preparing", "delivering", "reply_ready"}
            else "cancelling",
        )

    def session(self, context: Context) -> str | None:
        if context.group_id is not None:
            state = self.group_state(context)
            self.db.commit()
            return state["session_id"]
        row = self.db.execute(
            "SELECT session_id FROM sessions WHERE context=?", (context.key,)
        ).fetchone()
        return row["session_id"] if row else None

    def set_session(self, context: Context, session_id: str) -> None:
        if context.group_id is not None:
            self.group_state(context)
            self.db.execute(
                "UPDATE group_sessions SET session_id=? WHERE conversation=?",
                (session_id, context.conversation_key),
            )
            self.db.commit()
            return
        self.db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?)", (context.key, session_id))
        self.db.commit()

    def switch_session(self, context: Context, session_id: str) -> None:
        """Explicit admin switch; preserve old history and atomically start a group generation."""
        with self.db:
            if context.group_id is not None:
                self.group_state(context)
                cutoff = self.db.execute(
                    "SELECT COALESCE(MAX(seq),0) FROM group_messages"
                ).fetchone()[0]
                self.db.execute(
                    "UPDATE group_sessions SET session_id=?,generation=generation+1,"
                    "background_start=?,cursor=? WHERE conversation=?",
                    (session_id, cutoff, cutoff, context.conversation_key),
                )
            else:
                self.db.execute(
                    "INSERT OR REPLACE INTO sessions VALUES (?,?)", (context.key, session_id)
                )

    def reset_session(self, context: Context) -> None:
        if context.group_id is not None:
            with self.db:
                self.group_state(context)
                cutoff = self.db.execute(
                    "SELECT COALESCE(MAX(seq),0) FROM group_messages"
                ).fetchone()[0]
                self.db.execute(
                    """UPDATE group_sessions SET session_id=NULL,
                    generation=generation+1, background_start=?, cursor=? WHERE conversation=?""",
                    (cutoff, cutoff, context.conversation_key),
                )
            return
        self.db.execute("DELETE FROM sessions WHERE context=?", (context.key,))
        self.clear_staging(context)

    def pending(self, job_id: str, kind: str, session_id: str, remote: dict) -> dict:
        row = self.db.execute(
            "SELECT * FROM interactions WHERE job_id=? AND kind=? AND remote_id=?",
            (job_id, kind, remote["id"]),
        ).fetchone()
        if row:
            return dict(row)
        while True:
            code = secrets.token_hex(3)
            if not self.db.execute("SELECT 1 FROM interactions WHERE code=?", (code,)).fetchone():
                break
        self.db.execute(
            """INSERT INTO interactions
               (code,job_id,kind,session_id,remote_id,payload,created) VALUES (?,?,?,?,?,?,?)""",
            (code, job_id, kind, session_id, remote["id"], json.dumps(remote), time.time()),
        )
        self.db.commit()
        return self.interaction(code)

    def interaction(self, code: str) -> dict | None:
        row = self.db.execute(
            "SELECT * FROM interactions WHERE code=?", (code.casefold(),)
        ).fetchone()
        return dict(row) if row else None

    def pending_for(self, job_id: str) -> list[dict]:
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM interactions WHERE job_id=? AND state='pending'", (job_id,)
            )
        ]

    def group_permissions(self, context: Context) -> list[dict]:
        if context.group_id is None:
            return []
        return [
            dict(row)
            for row in self.db.execute(
                """SELECT interactions.* FROM interactions
                   JOIN jobs ON jobs.id=interactions.job_id
                   WHERE jobs.context LIKE ? AND interactions.kind='permission'
                   AND interactions.state='pending' AND jobs.cancel_requested=0
                   AND jobs.status IN ('running','waiting','submitting','preparing')""",
                (f"{context.self_id}:group:{context.group_id}:%",),
            )
        ]

    def update_interaction(self, code: str, *, state: str | None = None, answers=None) -> None:
        if state is not None:
            self.db.execute("UPDATE interactions SET state=? WHERE code=?", (state, code))
        if answers is not None:
            self.db.execute(
                "UPDATE interactions SET answers=? WHERE code=?", (json.dumps(answers), code)
            )
        self.db.commit()

    def settle_interactions(self, job_id: str) -> None:
        self.db.execute(
            "UPDATE interactions SET state='expired' WHERE job_id=? AND state='pending'",
            (job_id,),
        )
        self.db.commit()

    def put_outbox(
        self,
        context: Context,
        text: str,
        key: str,
        chunk_size: int,
        job_id: str | None = None,
        *,
        split_paragraphs: bool = False,
    ) -> None:
        paragraphs = re.split(r"\r?\n[ \t]*\r?\n", text) if split_paragraphs else [text]
        chunks = [
            paragraph[i : i + chunk_size]
            for paragraph in paragraphs
            if paragraph.strip()
            for i in range(0, len(paragraph), chunk_size)
        ] or [""]
        for index, chunk in enumerate(chunks):
            self.db.execute(
                """INSERT OR IGNORE INTO outbox
                   (dedupe_key,job_id,target,text,first_chunk,created) VALUES (?,?,?,?,?,?)""",
                (
                    f"{key}:{index}",
                    job_id,
                    json.dumps(context.to_dict()),
                    chunk,
                    int(index == 0),
                    time.time(),
                ),
            )
        self.db.commit()

    def enqueue_media(
        self, job_id: str, context: Context, artifacts: list[dict], *, request_id: str
    ) -> None:
        """把附件立刻放进发送队列，不必等任务结束。"""
        with self.db:
            for index, artifact in enumerate(artifacts):
                self.db.execute(
                    """INSERT OR IGNORE INTO outbox
                       (dedupe_key,job_id,target,text,first_chunk,kind,payload,created)
                       VALUES (?,?,?,'',0,?,?,?)""",
                    (
                        f"immediate:{job_id}:media:{request_id}:{index}",
                        job_id,
                        json.dumps(context.to_dict()),
                        artifact["kind"],
                        json.dumps({**artifact, "immediate": True}),
                        time.time(),
                    ),
                )

    def has_outbox(self, key: str) -> bool:
        return (
            self.db.execute("SELECT 1 FROM outbox WHERE dedupe_key=?", (f"{key}:0",)).fetchone()
            is not None
        )

    def output_prefix(self, job_id: str, message_id: str, part_index: int) -> str:
        row = self.db.execute(
            """SELECT prefix FROM assistant_output_cursors
               WHERE job_id=? AND message_id=? AND part_index=?""",
            (job_id, message_id, part_index),
        ).fetchone()
        return row["prefix"] if row else ""

    def put_progress(
        self,
        context: Context,
        job_id: str,
        message_id: str,
        part_index: int,
        prefix: str,
        text: str,
        chunk_size: int,
    ) -> None:
        # Persist the consumed source prefix and queued segment in one transaction.
        with self.db:
            self.db.execute(
                """INSERT INTO assistant_output_cursors(job_id,message_id,part_index,prefix)
                   VALUES (?,?,?,?) ON CONFLICT(job_id,message_id,part_index)
                   DO UPDATE SET prefix=excluded.prefix""",
                (job_id, message_id, part_index, prefix),
            )
            if text.strip():
                self.put_outbox(
                    context,
                    text,
                    f"progress:{job_id}:{message_id}:part:{part_index}:end:{len(prefix)}",
                    chunk_size,
                    job_id,
                )

    def complete(
        self,
        job_id: str,
        context: Context,
        result: str,
        chunk_size: int,
        error: str | None = None,
        artifacts: list[dict] | None = None,
        reply_text: str | None = None,
        split_reply: bool = False,
    ) -> None:
        # Persist completion and its output in the same transaction.
        validate_transition(
            self.job(job_id)["status"], "delivering" if artifacts else "reply_ready"
        )
        self.db.execute(
            "UPDATE jobs SET status=?,result=?,error=? WHERE id=?",
            ("delivering" if artifacts else "reply_ready", result, error, job_id),
        )
        self.db.execute(
            "UPDATE interactions SET state='expired' WHERE job_id=? AND state='pending'",
            (job_id,),
        )
        for index, artifact in enumerate(artifacts or []):
            if artifact.get("immediate"):
                # 已在提交时进入发送队列，完成时不再重复插入。
                continue
            self.db.execute(
                """INSERT OR IGNORE INTO outbox
                   (dedupe_key,job_id,target,text,first_chunk,kind,payload,created)
                   VALUES (?,?,?,'',0,?,?,?)""",
                (
                    f"result:{job_id}:media:{index}",
                    job_id,
                    json.dumps(context.to_dict()),
                    artifact["kind"],
                    json.dumps(artifact),
                    time.time(),
                ),
            )
        reply_text = result if reply_text is None else reply_text
        if reply_text:
            self.put_outbox(
                context,
                reply_text,
                f"result:{job_id}",
                chunk_size,
                job_id,
                split_paragraphs=split_reply,
            )
        else:
            self.db.commit()
            self.finish_delivery(job_id)

    def next_outbox(self, self_id: int) -> dict | None:
        for row in self.db.execute(
            "SELECT * FROM outbox WHERE status='ready' ORDER BY id"
        ).fetchall():
            if json.loads(row["target"])["self_id"] == self_id:
                return dict(row)
        return None

    def update_outbox(self, outbox_id: int, status: str, message_id=None) -> None:
        self.db.execute(
            "UPDATE outbox SET status=?,message_id=? WHERE id=?",
            (status, str(message_id) if message_id is not None else None, outbox_id),
        )
        self.db.commit()

    def failed_media(self) -> list[dict]:
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT * FROM outbox WHERE kind IN ('image','video','audio','file') "
                "AND status IN ('failed','uncertain') ORDER BY id"
            )
        ]

    def finish_delivery(self, job_id: str) -> None:
        job = self.job(job_id)
        if job["cancel_requested"] or job["status"] not in {"reply_ready", "delivering"}:
            return
        # 即时发送的附件：任务失败时，还没发出去的不再补发。
        if job["error"]:
            self.db.execute(
                "UPDATE outbox SET status='blocked' "
                "WHERE job_id=? AND status='ready' AND dedupe_key LIKE 'immediate:%'",
                (job_id,),
            )
            self.db.commit()
        rows = self.db.execute(
            "SELECT dedupe_key,status FROM outbox WHERE job_id=? AND kind!='poke'", (job_id,)
        ).fetchall()
        # An uncertain progress message must not prevent the final answer from being sent.
        # If the last answer was already forwarded as progress, it is the delivery to track.
        final_rows = [row for row in rows if not row["dedupe_key"].startswith("progress:")]
        # blocked 表示已确定不再发送，不参与“是否交付成功”的判定。
        states = {row["status"] for row in final_rows or rows} - {"blocked"}
        if "uncertain" in states or "failed" in states:
            self.db.execute(
                "UPDATE outbox SET status='blocked' WHERE job_id=? AND status='ready'", (job_id,)
            )
            self.db.commit()
            self.update_job(
                job_id, status="send_uncertain" if "uncertain" in states else "send_failed"
            )
        elif not states or states == {"sent"}:
            status = "failed" if job["error"] else "done"
            with self.db:
                self.db.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))
                self._settle_steers(job_id, status)
                if status == "done":
                    if job["memory_isolated"]:
                        self._record_public_memory_reply(job)

    def _record_public_memory_reply(self, job):
        context = Context(**json.loads(job["target"]))
        state = self.group_state(context)
        if state["generation"] != job["generation"] or not job["result"]:
            return
        payload = {
            "sender_id": context.self_id,
            "nickname": "机器人",
            "time": time.time(),
            "message_id": "public:" + job["id"],
            "text": job["result"],
            "mentions": [],
            "reply_id": None,
            "attachments": [],
            "forwards": [],
        }
        self.db.execute(
            "INSERT OR IGNORE INTO group_messages"
            "(conversation,generation,event_id,payload,created) VALUES (?,?,?,?,?)",
            (
                context.conversation_key,
                job["generation"],
                "public:" + job["id"],
                json.dumps(payload, ensure_ascii=False),
                time.time(),
            ),
        )

    def group_state(self, context: Context) -> dict:
        self.db.execute(
            "INSERT OR IGNORE INTO group_sessions(conversation) VALUES (?)",
            (context.conversation_key,),
        )
        return dict(
            self.db.execute(
                "SELECT * FROM group_sessions WHERE conversation=?", (context.conversation_key,)
            ).fetchone()
        )

    def record_group(self, incoming, *, commit=True) -> int:
        context = incoming.context
        if context.group_id is None:
            return 0
        state = self.group_state(context)
        payload = {
            "sender_id": context.user_id,
            "nickname": incoming.nickname,
            "time": incoming.timestamp,
            "message_id": incoming.event_id,
            "text": incoming.text,
            "mentions": incoming.mentions,
            "reply_id": incoming.reply_id,
            "attachments": [a.to_dict() for a in incoming.attachments],
            "forwards": [
                {"type": "forward", "id": str(f.get("id", ""))} for f in incoming.forwards
            ],
        }
        self.db.execute(
            """INSERT OR IGNORE INTO group_messages
            (conversation,generation,event_id,payload,created) VALUES (?,?,?,?,?)""",
            (
                context.conversation_key,
                state["generation"],
                incoming.event_id,
                json.dumps(payload, ensure_ascii=False),
                time.time(),
            ),
        )
        seq = self.db.execute(
            "SELECT seq FROM group_messages WHERE conversation=? AND event_id=?",
            (context.conversation_key, incoming.event_id),
        ).fetchone()[0]
        if commit:
            self.db.commit()
        return seq

    def conversation_jobs(self, context: Context, *, unfinished=True) -> list[dict]:
        sql = "SELECT * FROM jobs WHERE conversation=? AND steer_parent_id IS NULL"
        if unfinished:
            sql += " AND status NOT IN ('done','failed','cancelled','send_uncertain','send_failed')"
        return [
            dict(r) for r in self.db.execute(sql + " ORDER BY created", (context.conversation_key,))
        ]

    def acknowledge(self, job_id: str) -> None:
        job = self.job(job_id)
        validate_transition(job["status"], "steered" if job["steer_parent_id"] else "running")
        with self.db:
            if job["generation"] is not None and not job["memory_isolated"]:
                self.db.execute(
                    """UPDATE group_sessions SET cursor=MAX(cursor,?)
                    WHERE conversation=? AND generation=?""",
                    (job["submit_cursor"] or 0, job["conversation"], job["generation"]),
                )
            self.db.execute(
                "UPDATE jobs SET admitted=1,status=? WHERE id=?",
                ("steered" if job["steer_parent_id"] else "running", job_id),
            )

    def cleanup(self, config) -> None:
        now = time.time()
        with self.db:
            self.db.execute(
                "DELETE FROM group_messages WHERE created<?",
                (now - config.group_background_ttl_seconds,),
            )
            self.db.execute(
                """DELETE FROM group_messages WHERE seq IN (
                SELECT seq FROM (SELECT seq, ROW_NUMBER() OVER (
                PARTITION BY conversation ORDER BY seq DESC) AS n FROM group_messages)
                WHERE n>?)""",
                (config.group_background_max_messages,),
            )
            self.db.execute(
                "DELETE FROM diagnostic_events WHERE created<?",
                (now - config.diagnostic_ttl_seconds,),
            )
            self.db.execute(
                """DELETE FROM diagnostic_events WHERE id IN
                (SELECT id FROM diagnostic_events ORDER BY id DESC LIMIT -1 OFFSET ?)""",
                (config.diagnostic_max_events,),
            )

    def trace(self, context: Context, event_id: str) -> list[dict]:
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM diagnostic_events WHERE conversation=? AND event_id=? ORDER BY id",
                (context.conversation_key, event_id),
            )
        ]

    def sent_to(self, context: Context, message_id: str) -> bool:
        return any(
            json.loads(row["target"]) == context.to_dict()
            for row in self.db.execute(
                "SELECT target FROM outbox WHERE message_id=? AND status='sent'", (message_id,)
            )
        )
