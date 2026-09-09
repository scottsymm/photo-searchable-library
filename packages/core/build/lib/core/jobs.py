"""SQLite-backed single-worker job queue."""

from __future__ import annotations

import json
import sqlite3


def push(conn: sqlite3.Connection, kind: str, params: dict | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO jobs(kind, params) VALUES (?, ?)",
        (kind, json.dumps(params or {})),
    )
    conn.commit()
    return int(cur.lastrowid)


def claim(conn: sqlite3.Connection) -> sqlite3.Row | None:
    row = conn.execute(
        "SELECT * FROM jobs WHERE status = 'queued' ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    conn.execute(
        "UPDATE jobs SET status = 'working', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (row["id"],),
    )
    conn.commit()
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()


def set_progress(conn: sqlite3.Connection, job_id: int, progress: float) -> None:
    conn.execute(
        "UPDATE jobs SET progress = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (max(0, min(progress, 1)), job_id),
    )
    conn.commit()


def complete(conn: sqlite3.Connection, job_id: int) -> None:
    conn.execute(
        "UPDATE jobs SET status = 'done', progress = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (job_id,),
    )
    conn.commit()


def fail(conn: sqlite3.Connection, job_id: int, error: str) -> None:
    conn.execute(
        "UPDATE jobs SET status = 'error', error = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (error[:4000], job_id),
    )
    conn.commit()
