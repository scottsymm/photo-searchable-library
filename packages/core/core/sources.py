"""Source registration and source-backed asset identity."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

LIBRARY = Path(os.environ.get("PICS_LIBRARY", "library"))
WATCH_ROOT = Path(os.environ.get("PICS_WATCH_ROOT", "/media/photos"))


def classify_path(path: str) -> str | None:
    """Map an asset path to a source kind, or None if it matches no source."""
    resolved = Path(path).resolve()
    library = LIBRARY.resolve()
    for subdir, kind in (("apple-photos", "apple_photos"), ("imports", "uploads")):
        if resolved.is_relative_to(library / subdir):
            return kind
    if resolved.is_relative_to(WATCH_ROOT.resolve()):
        return "mounted_folder"
    return None


def get_source(conn: sqlite3.Connection, kind: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM sources WHERE kind = ?", (kind,)).fetchone()
    if row is None:
        raise ValueError(f"unknown source: {kind}")
    return row


def mark_source_status(
    conn: sqlite3.Connection,
    *,
    source_id: int,
    status: str,
    authorization_state: str | None = None,
    asset_count: int | None = None,
    imported_count: int | None = None,
    last_error: str | None = None,
) -> None:
    current = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    if current is None:
        raise ValueError(f"unknown source id: {source_id}")
    conn.execute(
        """UPDATE sources SET
        status = ?, authorization_state = ?, asset_count = ?, imported_count = ?,
        last_error = ?, last_sync_at = ?, updated_at = ?
        WHERE id = ?""",
        (
            status,
            authorization_state,
            current["asset_count"] if asset_count is None else asset_count,
            current["imported_count"] if imported_count is None else imported_count,
            last_error,
            datetime.now(timezone.utc).isoformat(),
            datetime.now(timezone.utc).isoformat(),
            source_id,
        ),
    )
    conn.commit()


def upsert_source_asset(
    conn: sqlite3.Connection,
    *,
    source_id: int,
    source_asset_id: str,
    path: str,
    original_filename: str | None,
) -> int:
    conn.execute(
        """INSERT INTO assets(source_id, source_asset_id, original_filename, path, sha256, size_bytes, mime)
        VALUES (?, ?, ?, ?, '', 0, 'application/octet-stream')
        ON CONFLICT(source_id, source_asset_id) DO UPDATE SET
          original_filename = excluded.original_filename,
          deleted = 0""",
        (source_id, source_asset_id, original_filename, path),
    )
    row = conn.execute(
        "SELECT id FROM assets WHERE source_id = ? AND source_asset_id = ?",
        (source_id, source_asset_id),
    ).fetchone()
    if row is None:
        raise RuntimeError("source asset row was not persisted")
    conn.commit()
    return int(row["id"])
