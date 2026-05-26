"""SQLite-backed session context memory."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from drift_agent.memory.types import ToolCallRecord, TurnRecord


class SQLiteContextStore:
    def __init__(self, memory_dir: str | Path = ".memory") -> None:
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.memory_dir / "context.sqlite3"
        self._ensure_schema()

    def record_turn(self, record: TurnRecord) -> int:
        now = utc_now()
        with self._connect() as con:
            self._ensure_session(con, record.session_id)
            cursor = con.execute(
                """
                INSERT INTO turns(session_id, user_prompt, assistant_answer, status, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    record.session_id,
                    record.user_prompt,
                    record.assistant_answer,
                    record.status,
                    now,
                ),
            )
            turn_id = int(cursor.lastrowid)
            for tool_call in record.tool_calls:
                con.execute(
                    """
                    INSERT INTO tool_calls(turn_id, name, arguments_json, result_preview, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        turn_id,
                        tool_call.name,
                        tool_call.arguments,
                        tool_call.result_preview,
                        now,
                    ),
                )
            con.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, record.session_id),
            )
            self.update_summary(con, record.session_id)
            return turn_id

    def record_memory_event(self, session_id: str, memory_name: str, event_type: str) -> None:
        with self._connect() as con:
            self._ensure_session(con, session_id)
            con.execute(
                """
                INSERT INTO memory_events(session_id, memory_name, event_type, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, memory_name, event_type, utc_now()),
            )

    def load_session_context(
        self,
        session_id: str,
        recent_limit: int = 5,
    ) -> tuple[str, list[tuple[str, str]]]:
        with self._connect() as con:
            self._ensure_session(con, session_id)
            row = con.execute(
                "SELECT summary FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            summary = str(row["summary"] or "") if row else ""
            rows = con.execute(
                """
                SELECT user_prompt, assistant_answer FROM turns
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, recent_limit),
            ).fetchall()
        recent = [
            (str(row["user_prompt"]), str(row["assistant_answer"]))
            for row in reversed(rows)
        ]
        return summary, recent

    def update_summary(self, con: sqlite3.Connection, session_id: str) -> None:
        rows = con.execute(
            """
            SELECT user_prompt, assistant_answer, status FROM turns
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT 8
            """,
            (session_id,),
        ).fetchall()
        if not rows:
            return
        lines = ["Recent session context:"]
        for row in reversed(rows):
            user_prompt = compact(str(row["user_prompt"]), 300)
            assistant_answer = compact(str(row["assistant_answer"]), 500)
            status = str(row["status"])
            lines.append(f"- user: {user_prompt}")
            lines.append(f"  assistant({status}): {assistant_answer}")
        summary = compact("\n".join(lines), 4000)
        con.execute(
            "UPDATE sessions SET summary = ?, updated_at = ? WHERE id = ?",
            (summary, utc_now(), session_id),
        )

    def _ensure_schema(self) -> None:
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    summary TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    user_prompt TEXT NOT NULL,
                    assistant_answer TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tool_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    turn_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    result_preview TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    memory_name TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def _ensure_session(self, con: sqlite3.Connection, session_id: str) -> None:
        now = utc_now()
        con.execute(
            """
            INSERT OR IGNORE INTO sessions(id, summary, created_at, updated_at)
            VALUES (?, '', ?, ?)
            """,
            (session_id, now, now),
        )

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def compact(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "... (truncated)"


def json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
