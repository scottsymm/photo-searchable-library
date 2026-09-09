"""Embedding serialization and sqlite-vec operations."""

from __future__ import annotations

import array
import sqlite3


def to_blob(vector: list[float]) -> bytes:
    return array.array("f", vector).tobytes()


def add_content(
    conn: sqlite3.Connection,
    asset_id: int,
    model: str,
    model_version: str,
    vector: list[float],
) -> None:
    blob = to_blob(vector)
    conn.execute(
        """INSERT INTO content_embeds(asset_id, model, model_version, embed)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(asset_id) DO UPDATE SET model = excluded.model,
          model_version = excluded.model_version, embed = excluded.embed""",
        (asset_id, model, model_version, blob),
    )
    conn.execute("DELETE FROM vec0_content WHERE rowid = ?", (asset_id,))
    conn.execute(
        "INSERT INTO vec0_content(rowid, content_embed) VALUES (?, ?)",
        (asset_id, blob),
    )
    conn.commit()


def add_face(conn: sqlite3.Connection, face_id: int, model: str, vector: list[float]) -> None:
    blob = to_blob(vector)
    conn.execute(
        """INSERT INTO face_embeds(face_id, model, embed) VALUES (?, ?, ?)
        ON CONFLICT(face_id) DO UPDATE SET model = excluded.model, embed = excluded.embed""",
        (face_id, model, blob),
    )
    conn.execute("DELETE FROM vec0_face WHERE rowid = ?", (face_id,))
    conn.execute("INSERT INTO vec0_face(rowid, face_embed) VALUES (?, ?)", (face_id, blob))
    conn.commit()


def content_knn(conn: sqlite3.Connection, vector: list[float], limit: int = 50) -> list[tuple[int, float]]:
    rows = conn.execute(
        """SELECT rowid, distance FROM vec0_content
        WHERE content_embed MATCH ? ORDER BY distance LIMIT ?""",
        (to_blob(vector), limit),
    ).fetchall()
    return [(int(row["rowid"]), float(row["distance"])) for row in rows]
