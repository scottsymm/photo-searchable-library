"""Asset and thumbnail persistence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_file(
    conn: sqlite3.Connection,
    sha256: str,
    kind: str,
    data: bytes | None = None,
) -> int:
    conn.execute(
        "INSERT OR IGNORE INTO files(sha256, kind, bytes, created_at) VALUES (?, ?, ?, ?)",
        (sha256, kind, data, datetime.now(timezone.utc).isoformat()),
    )
    row = conn.execute("SELECT id FROM files WHERE sha256 = ?", (sha256,)).fetchone()
    if row is None:
        raise RuntimeError("file row was not persisted")
    return int(row["id"])


def upsert_asset(
    conn: sqlite3.Connection,
    *,
    path: str,
    sha256: str,
    size_bytes: int,
    mime: str,
    taken_at: str | None,
    gps_lat: float | None,
    gps_lon: float | None,
    place_city: str | None,
    place_country: str | None,
    thumbnail: bytes | None,
    extra: dict | None,
) -> int:
    thumbnail_id = None
    if thumbnail is not None:
        thumbnail_id = add_file(conn, f"{sha256}:thumbnail", "thumbnail", thumbnail)
    conn.execute(
        """INSERT INTO assets
        (path, sha256, size_bytes, mime, taken_at, gps_lat, gps_lon,
         place_city, place_country, thumbnail_id, extra)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
          sha256 = excluded.sha256, size_bytes = excluded.size_bytes,
          mime = excluded.mime, taken_at = excluded.taken_at,
          gps_lat = excluded.gps_lat, gps_lon = excluded.gps_lon,
          place_city = excluded.place_city, place_country = excluded.place_country,
          thumbnail_id = excluded.thumbnail_id, extra = excluded.extra,
          deleted = 0""",
        (
            path,
            sha256,
            size_bytes,
            mime,
            taken_at,
            gps_lat,
            gps_lon,
            place_city,
            place_country,
            thumbnail_id,
            json.dumps(extra or {}),
        ),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM assets WHERE path = ?", (path,)).fetchone()
    if row is None:
        raise RuntimeError("asset row was not persisted")
    return int(row["id"])
