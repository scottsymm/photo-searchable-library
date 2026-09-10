"""Typed access to runtime catalog settings."""

from __future__ import annotations

import sqlite3

DEFAULTS = {
    "watch_enabled": "0",
    "watch_backfill": "prompt",
    "watch_initialized": "0",
}


def seed(conn: sqlite3.Connection) -> None:
    for key, value in DEFAULTS.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
            (key, value),
        )
    conn.commit()


def get(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_value(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """INSERT INTO settings(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value,
        updated_at = CURRENT_TIMESTAMP""",
        (key, value),
    )
    conn.commit()


def get_all(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
    return {row["key"]: row["value"] for row in rows}
