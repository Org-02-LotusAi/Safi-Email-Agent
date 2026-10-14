"""SQLite persistence (doc §35). Persistent state belongs to the Service, not to any
open LLM session (doc §18, §28).

Schema follows the minimal model in §35, plus a ``processed_messages`` table for
duplicate-message protection (§36). "Equivalent simple schema is acceptable" (§35).
"""

from __future__ import annotations

import os
import sqlite3
import time
import uuid
from contextlib import contextmanager

from .models import AgentConfig

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    mailbox  TEXT NOT NULL UNIQUE,
    model    TEXT NOT NULL,
    enabled  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS private_senders (
    agent_id     TEXT NOT NULL,
    sender_email TEXT NOT NULL,
    PRIMARY KEY (agent_id, sender_email)
);

CREATE TABLE IF NOT EXISTS training (
    training_id       TEXT PRIMARY KEY,
    agent_id          TEXT NOT NULL,
    category          TEXT NOT NULL,
    content           TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    source_message_id TEXT
);

CREATE TABLE IF NOT EXISTS files (
    file_id           TEXT PRIMARY KEY,
    agent_id          TEXT NOT NULL,
    filename          TEXT NOT NULL,
    location          TEXT NOT NULL,
    extracted_text    TEXT,
    source_message_id TEXT,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subject_context (
    agent_id          TEXT NOT NULL,
    client_id         TEXT NOT NULL,
    canonical_subject TEXT NOT NULL,   -- stored as casefolded namespace key
    display_subject   TEXT NOT NULL,   -- last seen display form
    summary           TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    PRIMARY KEY (agent_id, client_id, canonical_subject)
);

CREATE TABLE IF NOT EXISTS micro_sessions (
    micro_session_id    TEXT PRIMARY KEY,
    agent_id            TEXT NOT NULL,
    client_id           TEXT NOT NULL,
    canonical_subject   TEXT NOT NULL,
    incoming_message_id TEXT,
    result_summary      TEXT,
    started_at          TEXT NOT NULL,
    ended_at            TEXT
);

CREATE TABLE IF NOT EXISTS processed_messages (
    agent_id     TEXT NOT NULL,
    message_id   TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    PRIMARY KEY (agent_id, message_id)
);
"""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def init_db(path: str) -> None:
    """Create the schema if it does not exist. Idempotent."""
    if path != ":memory:":
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


class Store:
    """Thin data-access layer over one SQLite connection.

    The service loop is single-threaded per process, so one connection is sufficient.
    """

    def __init__(self, path: str):
        self.path = path
        init_db(path)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def _tx(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # --- agents -------------------------------------------------------------
    def upsert_agent(self, agent: AgentConfig) -> None:
        with self._tx() as c:
            c.execute(
                """INSERT INTO agents (agent_id, name, mailbox, model, enabled)
                       VALUES (?,?,?,?,?)
                   ON CONFLICT(agent_id) DO UPDATE SET
                       name=excluded.name, mailbox=excluded.mailbox,
                       model=excluded.model, enabled=excluded.enabled""",
                (agent.agent_id, agent.name, agent.mailbox, agent.model,
                 1 if agent.enabled else 0),
            )

    def get_agent_row(self, agent_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM agents WHERE agent_id=?", (agent_id,)
        ).fetchone()

    # --- private senders (doc §10) -----------------------------------------
    def add_private_sender(self, agent_id: str, sender_email: str) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT OR IGNORE INTO private_senders (agent_id, sender_email) VALUES (?,?)",
                (agent_id, sender_email.strip().lower()),
            )

    def is_private_sender(self, agent_id: str, sender_email: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM private_senders WHERE agent_id=? AND sender_email=?",
            (agent_id, sender_email.strip().lower()),
        ).fetchone()
        return row is not None

    # --- training (doc §26, §28) -------------------------------------------
    def add_training(self, agent_id: str, category: str, content: str,
                     source_message_id: str | None = None) -> str:
        tid = uuid.uuid4().hex
        with self._tx() as c:
            c.execute(
                """INSERT INTO training
                       (training_id, agent_id, category, content, created_at, source_message_id)
                   VALUES (?,?,?,?,?,?)""",
                (tid, agent_id, category, content, _now(), source_message_id),
            )
        return tid

    def get_training(self, agent_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM training WHERE agent_id=? ORDER BY created_at, training_id",
            (agent_id,),
        ).fetchall()

    # --- reference files (doc §24, §25) ------------------------------------
    def add_file(self, agent_id: str, filename: str, location: str,
                 extracted_text: str | None, source_message_id: str | None = None) -> str:
        fid = uuid.uuid4().hex
        with self._tx() as c:
            c.execute(
                """INSERT INTO files
                       (file_id, agent_id, filename, location, extracted_text,
                        source_message_id, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (fid, agent_id, filename, location, extracted_text,
                 source_message_id, _now()),
            )
        return fid

    def get_files(self, agent_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM files WHERE agent_id=? ORDER BY created_at, file_id",
            (agent_id,),
        ).fetchall()

    # --- persistent (client, subject) context (doc §15, §28) ---------------
    def get_subject_context(self, agent_id: str, client_id: str,
                            canonical_key: str) -> sqlite3.Row | None:
        return self.conn.execute(
            """SELECT * FROM subject_context
               WHERE agent_id=? AND client_id=? AND canonical_subject=?""",
            (agent_id, client_id.lower(), canonical_key),
        ).fetchone()

    def upsert_subject_context(self, agent_id: str, client_id: str, canonical_key: str,
                               display_subject: str, summary: str) -> None:
        with self._tx() as c:
            c.execute(
                """INSERT INTO subject_context
                       (agent_id, client_id, canonical_subject, display_subject, summary, updated_at)
                       VALUES (?,?,?,?,?,?)
                   ON CONFLICT(agent_id, client_id, canonical_subject) DO UPDATE SET
                       summary=excluded.summary, display_subject=excluded.display_subject,
                       updated_at=excluded.updated_at""",
                (agent_id, client_id.lower(), canonical_key, display_subject, summary, _now()),
            )

    # --- micro-sessions (doc §19, §20) -------------------------------------
    def start_micro_session(self, agent_id: str, client_id: str, canonical_subject: str,
                            incoming_message_id: str | None) -> tuple[str, str]:
        msid = uuid.uuid4().hex
        started = _now()
        with self._tx() as c:
            c.execute(
                """INSERT INTO micro_sessions
                       (micro_session_id, agent_id, client_id, canonical_subject,
                        incoming_message_id, started_at)
                   VALUES (?,?,?,?,?,?)""",
                (msid, agent_id, client_id.lower(), canonical_subject,
                 incoming_message_id, started),
            )
        return msid, started

    def end_micro_session(self, micro_session_id: str, result_summary: str) -> str:
        ended = _now()
        with self._tx() as c:
            c.execute(
                "UPDATE micro_sessions SET result_summary=?, ended_at=? WHERE micro_session_id=?",
                (result_summary, ended, micro_session_id),
            )
        return ended

    # --- duplicate-message protection (doc §36) ----------------------------
    def is_processed(self, agent_id: str, message_id: str) -> bool:
        if not message_id:
            return False
        row = self.conn.execute(
            "SELECT 1 FROM processed_messages WHERE agent_id=? AND message_id=?",
            (agent_id, message_id),
        ).fetchone()
        return row is not None

    def mark_processed(self, agent_id: str, message_id: str) -> None:
        if not message_id:
            return
        with self._tx() as c:
            c.execute(
                "INSERT OR IGNORE INTO processed_messages (agent_id, message_id, processed_at) "
                "VALUES (?,?,?)",
                (agent_id, message_id, _now()),
            )

    # --- tenant reset (HTTP API "reset a user") -----------------------------
    def purge_agent(self, agent_id: str) -> dict:
        """Delete all rows for one (possibly instance) ``agent_id`` across every
        per-agent table. Returns ``{table: rows_deleted}``. Runs in one transaction
        so a failure partway through leaves no partial purge.

        Deliberately does NOT touch the ``agents`` table: a tenant instance id is
        never a row there (see safi/tenancy.py), and purging a base agent's own
        row is not this method's job.
        """
        tables = (
            "training",
            "files",
            "subject_context",
            "micro_sessions",
            "processed_messages",
            "private_senders",
        )
        deleted: dict[str, int] = {}
        with self._tx() as c:
            for table in tables:
                cur = c.execute(f"DELETE FROM {table} WHERE agent_id=?", (agent_id,))
                deleted[table] = cur.rowcount if cur.rowcount >= 0 else 0
        return deleted
