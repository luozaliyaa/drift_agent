"""SQLite-backed semantic memory store with local deterministic embeddings."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from drift_agent.memory.types import MemoryRecord, RetrievalRequest, RetrievalResult


EMBEDDING_DIMENSIONS = 64


class VectorMemoryStore:
    def __init__(self, memory_dir: str | Path = ".memory") -> None:
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.memory_dir / "memory2.sqlite3"
        self._ensure_schema()

    def ingest(self, record: MemoryRecord) -> MemoryRecord:
        now = utc_now()
        record_id = record.id or stable_record_id(record.memory_type, record.content)
        created_at = record.created_at or now
        updated_at = now
        embedding = embed_text(" ".join([record.memory_type, record.summary, record.content]))
        stored = MemoryRecord(
            id=record_id,
            memory_type=record.memory_type,
            content=record.content,
            summary=record.summary or summarize(record.content),
            source_ref=record.source_ref,
            created_at=created_at,
            updated_at=updated_at,
        )
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO memory_records(
                    id, memory_type, content, summary, source_ref_json,
                    created_at, updated_at, deleted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(id) DO UPDATE SET
                    memory_type = excluded.memory_type,
                    content = excluded.content,
                    summary = excluded.summary,
                    source_ref_json = excluded.source_ref_json,
                    updated_at = excluded.updated_at,
                    deleted_at = NULL
                """,
                (
                    stored.id,
                    stored.memory_type,
                    stored.content,
                    stored.summary,
                    json.dumps(list(stored.source_ref), ensure_ascii=False),
                    stored.created_at,
                    stored.updated_at,
                ),
            )
            con.execute(
                """
                INSERT INTO memory_embeddings(record_id, embedding_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                    embedding_json = excluded.embedding_json,
                    updated_at = excluded.updated_at
                """,
                (stored.id, json.dumps(embedding), updated_at),
            )
            con.execute(
                """
                INSERT INTO memory_events(record_id, event_type, created_at)
                VALUES (?, 'ingest', ?)
                """,
                (stored.id, updated_at),
            )
        return stored

    def remember(
        self,
        content: str,
        memory_type: str = "requested_memory",
        summary: str = "",
        source_ref: tuple[str, ...] = (),
    ) -> MemoryRecord:
        return self.ingest(
            MemoryRecord(
                id=stable_record_id(memory_type, content),
                memory_type=memory_type,
                content=content,
                summary=summary or summarize(content),
                source_ref=source_ref,
            )
        )

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        query_embedding = embed_text(request.query)
        records = self.list_records(memory_type=request.memory_type)
        scored: list[tuple[float, MemoryRecord]] = []
        for record in records:
            embedding = self._load_embedding(record.id)
            score = cosine_similarity(query_embedding, embedding)
            lexical = lexical_score(request.query, record)
            total = score + lexical
            if total > 0:
                scored.append((total, record))
        scored.sort(key=lambda pair: (-pair[0], pair[1].updated_at, pair[1].id))
        return RetrievalResult([record for _, record in scored[: request.limit]])

    def retrieve_explicit(self, request: RetrievalRequest) -> RetrievalResult:
        return self.retrieve(request)

    def forget(self, record_id: str) -> bool:
        now = utc_now()
        with self._connect() as con:
            cursor = con.execute(
                """
                UPDATE memory_records
                SET deleted_at = ?, updated_at = ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                (now, now, record_id),
            )
            deleted = cursor.rowcount > 0
            if deleted:
                con.execute(
                    """
                    INSERT INTO memory_events(record_id, event_type, created_at)
                    VALUES (?, 'forget', ?)
                    """,
                    (record_id, now),
                )
        return deleted

    def list_records(self, memory_type: str | None = None) -> list[MemoryRecord]:
        sql = """
            SELECT id, memory_type, content, summary, source_ref_json,
                   created_at, updated_at
            FROM memory_records
            WHERE deleted_at IS NULL
        """
        params: tuple[str, ...] = ()
        if memory_type:
            sql += " AND memory_type = ?"
            params = (memory_type,)
        sql += " ORDER BY updated_at DESC, id ASC"
        with self._connect() as con:
            rows = con.execute(sql, params).fetchall()
        return [row_to_record(row) for row in rows]

    def get_record(self, record_id: str) -> MemoryRecord | None:
        with self._connect() as con:
            row = con.execute(
                """
                SELECT id, memory_type, content, summary, source_ref_json,
                       created_at, updated_at
                FROM memory_records
                WHERE id = ? AND deleted_at IS NULL
                """,
                (record_id,),
            ).fetchone()
        if row is None:
            return None
        return row_to_record(row)

    def update_record(
        self,
        record_id: str,
        *,
        content: str | None = None,
        summary: str | None = None,
        memory_type: str | None = None,
    ) -> MemoryRecord | None:
        current = self.get_record(record_id)
        if current is None:
            return None
        return self.ingest(
            MemoryRecord(
                id=current.id,
                memory_type=memory_type or current.memory_type,
                content=content if content is not None else current.content,
                summary=summary if summary is not None else current.summary,
                source_ref=current.source_ref,
                created_at=current.created_at,
            )
        )

    def delete_item(self, record_id: str) -> bool:
        return self.forget(record_id)

    def delete_items_batch(self, record_ids: list[str]) -> int:
        return sum(1 for record_id in record_ids if self.forget(record_id))

    def find_similar_items(self, record_id: str, limit: int = 5) -> RetrievalResult:
        record = self.get_record(record_id)
        if record is None:
            return RetrievalResult()
        results = self.retrieve(
            RetrievalRequest(
                query=" ".join([record.summary, record.content]),
                memory_type=record.memory_type,
                limit=limit + 1,
            )
        )
        return RetrievalResult([item for item in results.records if item.id != record_id][:limit])

    def _load_embedding(self, record_id: str) -> list[float]:
        with self._connect() as con:
            row = con.execute(
                "SELECT embedding_json FROM memory_embeddings WHERE record_id = ?",
                (record_id,),
            ).fetchone()
        if row is None:
            return [0.0] * EMBEDDING_DIMENSIONS
        return [float(value) for value in json.loads(str(row["embedding_json"]))]

    def _ensure_schema(self) -> None:
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_records (
                    id TEXT PRIMARY KEY,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    source_ref_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS memory_embeddings (
                    record_id TEXT PRIMARY KEY,
                    embedding_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con


def embed_text(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for token in tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % EMBEDDING_DIMENSIONS
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def tokens(text: str) -> list[str]:
    lowered = text.lower()
    ascii_tokens = re.findall(r"[a-zA-Z0-9_]{2,}", lowered)
    cjk_tokens = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    return ascii_tokens + cjk_tokens


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def lexical_score(query: str, record: MemoryRecord) -> float:
    haystack = f"{record.memory_type} {record.summary} {record.content}".lower()
    score = 0.0
    for token in tokens(query):
        if token in haystack:
            score += 0.25
    return score


def stable_record_id(memory_type: str, content: str) -> str:
    digest = hashlib.sha256(f"{memory_type}\0{content}".encode("utf-8")).hexdigest()
    return digest[:16]


def summarize(content: str) -> str:
    cleaned = re.sub(r"\s+", " ", content).strip()
    if len(cleaned) <= 120:
        return cleaned
    return cleaned[:117] + "..."


def row_to_record(row: sqlite3.Row) -> MemoryRecord:
    try:
        source_ref = tuple(str(value) for value in json.loads(str(row["source_ref_json"])))
    except json.JSONDecodeError:
        source_ref = ()
    return MemoryRecord(
        id=str(row["id"]),
        memory_type=str(row["memory_type"]),
        content=str(row["content"]),
        summary=str(row["summary"]),
        source_ref=source_ref,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
