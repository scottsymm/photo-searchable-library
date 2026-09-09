"""Natural-language and structured catalog search."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from core.embeds import content_knn

from .deps import embed_text, get_conn

router = APIRouter()


def _filter_ids(
    conn: sqlite3.Connection,
    *,
    who: str | None,
    place: str | None,
    before: str | None,
    after: str | None,
    tag: str | None,
) -> set[int]:
    query = "SELECT id FROM assets WHERE deleted = 0"
    params: list[str] = []
    if place:
        query += " AND (place_city LIKE ? OR place_country LIKE ?)"
        params.extend([f"%{place}%", f"%{place}%"])
    if before:
        query += " AND taken_at IS NOT NULL AND taken_at <= ?"
        params.append(before)
    if after:
        query += " AND taken_at IS NOT NULL AND taken_at >= ?"
        params.append(after)
    if tag:
        query += " AND id IN (SELECT asset_id FROM tags WHERE tag = ?)"
        params.append(tag)
    if who:
        query += """ AND id IN (
          SELECT faces.asset_id FROM faces JOIN persons ON persons.id = faces.cluster_id
          WHERE persons.name = ?
        )"""
        params.append(who)
    return {int(row["id"]) for row in conn.execute(query, params)}


def _asset_result(conn: sqlite3.Connection, asset_id: int, distance: float | None = None) -> dict:
    row = conn.execute(
        "SELECT id, path, mime, taken_at, place_city, place_country, thumbnail_id FROM assets WHERE id = ?",
        (asset_id,),
    ).fetchone()
    if row is None:
        return {}
    result = dict(row)
    result["thumbnail_url"] = f"/assets/{asset_id}/thumbnail"
    if distance is not None:
        result["distance"] = distance
    return result


@router.get("")
async def search(
    q: str | None = None,
    who: str | None = None,
    place: str | None = None,
    before: str | None = None,
    after: str | None = None,
    tag: str | None = None,
    limit: int = 50,
    conn=Depends(get_conn),
):
    limit = max(1, min(limit, 200))
    allowed = _filter_ids(conn, who=who, place=place, before=before, after=after, tag=tag)
    if q:
        try:
            vector = await embed_text(q)
        except Exception as error:
            raise HTTPException(status_code=503, detail="models_pending") from error
        ranked = content_knn(conn, vector, limit * 4)
        results = [_asset_result(conn, asset_id, distance) for asset_id, distance in ranked]
        results = [result for result in results if result.get("id") in allowed]
    else:
        rows = conn.execute(
            "SELECT id FROM assets WHERE deleted = 0 ORDER BY taken_at DESC, id DESC LIMIT ?",
            (limit * 4,),
        ).fetchall()
        results = [_asset_result(conn, int(row["id"])) for row in rows if int(row["id"]) in allowed]
    return {"results": results[:limit]}
