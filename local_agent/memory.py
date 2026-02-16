from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Message:
    role: str
    content: str


class SessionStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._conn.commit()

    def append(self, session_id: str, role: str, content: str) -> None:
        self._conn.execute(
            "INSERT INTO messages(session_id, role, content) VALUES (?, ?, ?)",
            (session_id, role, content),
        )
        self._conn.commit()

    def load(self, session_id: str, limit: int = 30) -> list[Message]:
        rows = self._conn.execute(
            """
            SELECT role, content
            FROM messages
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
        rows.reverse()
        return [Message(role=row[0], content=row[1]) for row in rows]

    def clear(self, session_id: str) -> None:
        self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        self._conn.commit()
