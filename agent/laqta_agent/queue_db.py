from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from laqta_agent.config import RETRY_BASE_DELAY_SECONDS, RETRY_MAX_DELAY_SECONDS

_SCHEMA = """
CREATE TABLE IF NOT EXISTS uploads (
    path TEXT PRIMARY KEY,
    md5 TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | uploading | done | failed
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    next_retry_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_uploads_status ON uploads(status);
CREATE INDEX IF NOT EXISTS idx_uploads_md5 ON uploads(md5);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def backoff_seconds(attempts: int) -> float:
    """attempts=1 (first failure) -> RETRY_BASE_DELAY_SECONDS, doubling
    from there, capped at RETRY_MAX_DELAY_SECONDS -- a burst of failures
    (e.g. WiFi drops mid-event) backs off instead of hammering the API
    or draining a metered connection.
    """
    delay = RETRY_BASE_DELAY_SECONDS * (2 ** max(0, attempts - 1))
    return min(delay, RETRY_MAX_DELAY_SECONDS)


@dataclass(frozen=True)
class UploadRecord:
    path: str
    md5: str | None
    status: str
    attempts: int
    last_error: str | None
    updated_at: str


class UploadQueue:
    """SQLite so the queue survives an app restart and a network outage
    without losing track of anything -- every state transition is a
    committed write, not in-memory state that a crash would drop.
    check_same_thread=False plus an internal lock: the watcher thread
    enqueues, the uploader thread transitions status, and the GUI thread
    reads counts, all against the same connection.
    """

    def __init__(self, db_path: Path) -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def is_already_done(self, md5: str) -> bool:
        """True if a file with this exact content has already been
        successfully uploaded -- from this path or any other. Covers the
        common "agent restarted, the file is still sitting in the
        folder" case (same path, already done) and the rarer "same photo
        reappeared under a different path" case (renamed, or the same
        card re-imported) without a second upload either way.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM uploads WHERE md5 = ? AND status = 'done' LIMIT 1", (md5,)
            ).fetchone()
            return row is not None

    def enqueue(self, path: str, md5: str) -> None:
        """Idempotent by path -- re-enqueuing a path already in the queue
        (any status) is a no-op; the uploader owns transitions from
        there. Callers should check is_already_done(md5) first to avoid
        even creating a pending row for a known duplicate.
        """
        now = _now_iso()
        with self._lock:
            self._conn.execute(
                "INSERT INTO uploads (path, md5, status, attempts, created_at, updated_at) "
                "VALUES (?, ?, 'pending', 0, ?, ?) "
                "ON CONFLICT(path) DO NOTHING",
                (path, md5, now, now),
            )
            self._conn.commit()

    def mark_done_without_uploading(self, path: str, md5: str) -> None:
        """For a file whose MD5 is already is_already_done() elsewhere --
        recorded as done so it shows in counts and never gets re-checked,
        without ever calling the API for it.
        """
        now = _now_iso()
        with self._lock:
            self._conn.execute(
                "INSERT INTO uploads (path, md5, status, attempts, created_at, updated_at) "
                "VALUES (?, ?, 'done', 0, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET status='done', md5=excluded.md5, updated_at=excluded.updated_at",
                (path, md5, now, now),
            )
            self._conn.commit()

    def next_ready(self) -> UploadRecord | None:
        """One row that's either fresh ('pending') or past its backoff
        window ('failed' with next_retry_at <= now) -- oldest first, so a
        long queue drains in upload order, matching the order guests are
        likely to expect their photos to appear.
        """
        now = _now_iso()
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM uploads WHERE status = 'pending' "
                "OR (status = 'failed' AND next_retry_at IS NOT NULL AND next_retry_at <= ?) "
                "ORDER BY created_at ASC LIMIT 1",
                (now,),
            ).fetchone()
        return _row_to_record(row) if row else None

    def mark_uploading(self, path: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE uploads SET status = 'uploading', updated_at = ? WHERE path = ?", (_now_iso(), path)
            )
            self._conn.commit()

    def mark_done(self, path: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE uploads SET status = 'done', last_error = NULL, next_retry_at = NULL, updated_at = ? "
                "WHERE path = ?",
                (_now_iso(), path),
            )
            self._conn.commit()

    def mark_failed(self, path: str, error: str) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            row = self._conn.execute("SELECT attempts FROM uploads WHERE path = ?", (path,)).fetchone()
            attempts = (row["attempts"] if row else 0) + 1
            next_retry_at = (now + timedelta(seconds=backoff_seconds(attempts))).isoformat()
            self._conn.execute(
                "UPDATE uploads SET status = 'failed', attempts = ?, last_error = ?, next_retry_at = ?, "
                "updated_at = ? WHERE path = ?",
                (attempts, error[:500], next_retry_at, now.isoformat(), path),
            )
            self._conn.commit()

    def counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute("SELECT status, COUNT(*) AS n FROM uploads GROUP BY status").fetchall()
        result = {"pending": 0, "uploading": 0, "done": 0, "failed": 0}
        for row in rows:
            result[row["status"]] = row["n"]
        return result

    def recent_errors(self, limit: int = 20) -> list[UploadRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM uploads WHERE status = 'failed' ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row_to_record(r) for r in rows]

    def all_paths(self) -> set[str]:
        """Used by the startup catch-up scan to skip files the queue
        already knows about (in any status) rather than re-enqueuing.
        """
        with self._lock:
            rows = self._conn.execute("SELECT path FROM uploads").fetchall()
        return {r["path"] for r in rows}


def _row_to_record(row: sqlite3.Row) -> UploadRecord:
    return UploadRecord(
        path=row["path"],
        md5=row["md5"],
        status=row["status"],
        attempts=row["attempts"],
        last_error=row["last_error"],
        updated_at=row["updated_at"],
    )
