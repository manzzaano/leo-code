"""Persistencia de sesiones SQLite para conversaciones multi-turn."""

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Session:
    id: str
    repo_path: str
    model: str = ""
    created_at: float = 0
    updated_at: float = 0
    message_count: int = 0
    total_tokens: int = 0

@dataclass
class Message:
    id: int
    session_id: str
    role: str  # user, assistant, system, tool
    content: str
    tool_calls: list[dict] = field(default_factory=list)
    tokens: int = 0
    created_at: float = 0


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    repo_path TEXT NOT NULL,
    model TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    message_count INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    tool_calls TEXT DEFAULT '[]',
    tokens INTEGER DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
"""


class SessionManager:
    def __init__(self, db_path: str = "./cache/leo_sessions.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        with self._lock:
            self._conn.executescript(_SCHEMA)

    def create_session(self, repo_path: str, model: str = "") -> Session:
        import uuid
        sid = uuid.uuid4().hex[:16]
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO sessions (id, repo_path, model, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (sid, repo_path, model, now, now),
            )
        return Session(id=sid, repo_path=repo_path, model=model, created_at=now, updated_at=now)

    def add_message(self, session_id: str, role: str, content: str = "",
                    tool_calls: list[dict] | None = None, tokens: int = 0) -> Message:
        now = time.time()
        tc_json = json.dumps(tool_calls or [], ensure_ascii=False)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO messages (session_id, role, content, tool_calls, tokens, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, role, content, tc_json, tokens, now),
            )
            self._conn.execute(
                "UPDATE sessions SET updated_at = ?, message_count = message_count + 1, total_tokens = total_tokens + ? WHERE id = ?",
                (now, tokens, session_id),
            )
            msg_id = cur.lastrowid
        return Message(id=msg_id, session_id=session_id, role=role, content=content,
                       tool_calls=tool_calls or [], tokens=tokens, created_at=now)

    def get_history(self, session_id: str, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content, tool_calls FROM messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        result = []
        for role, content, tc_json in reversed(rows):
            msg = {"role": role, "content": content}
            if tc_json and tc_json != "[]":
                try:
                    tcs = json.loads(tc_json)
                    if tcs:
                        msg["tool_calls"] = tcs
                except json.JSONDecodeError:
                    msg["tool_calls"] = []
            result.append(msg)
        return result

    def get_session(self, session_id: str) -> Optional[Session]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, repo_path, model, created_at, updated_at, message_count, total_tokens FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        if row:
            return Session(*row)
        return None

    def list_sessions(self, limit: int = 20) -> list[Session]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, repo_path, model, created_at, updated_at, message_count, total_tokens FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [Session(*r) for r in rows]

    def delete_session(self, session_id: str):
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
