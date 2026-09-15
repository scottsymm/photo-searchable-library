"""External source ingest and status endpoints."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile

from core import jobs
from core.assets import sha256_file
from core.sources import get_source, mark_source_status

from .deps import get_conn

router = APIRouter()
LIBRARY = Path(os.environ.get("PICS_LIBRARY", "library"))


@router.get("/apple-photos/status")
def apple_photos_status(conn=Depends(get_conn)):
    source = dict(get_source(conn, "apple_photos"))
    imported = conn.execute(
        """SELECT COUNT(*) FROM assets
        WHERE source_id = ? AND deleted = 0 AND sha256 != ''""",
        (source["id"],),
    ).fetchone()[0]
    source["imported_count"] = imported
    return {"source": source}


@router.post("/apple-photos/assets")
async def ingest_apple_photos_asset(
    file: UploadFile = File(...),
    source_asset_id: str = Form(...),
    original_filename: str | None = Form(default=None),
    media_type: str | None = Form(default=None),
    taken_at: str | None = Form(default=None),
    authorization_state: str | None = Form(default=None),
    asset_count: int | None = Form(default=None),
    conn=Depends(get_conn),
):
    source = get_source(conn, "apple_photos")
    existing = conn.execute(
        """SELECT id, path FROM assets
        WHERE source_id = ? AND source_asset_id = ? AND deleted = 0""",
        (source["id"], source_asset_id),
    ).fetchone()
    if existing is not None and existing["path"]:
        mark_source_status(
            conn,
            source_id=source["id"],
            status="connected",
            authorization_state=authorization_state,
            asset_count=asset_count,
        )
        return {
            "status": "duplicate",
            "duplicate": True,
            "asset_id": existing["id"],
            "source_asset_id": source_asset_id,
        }

    suffix = Path(original_filename or file.filename or "photo.jpg").suffix.lower() or ".jpg"
    destination = LIBRARY / "apple-photos" / f"{uuid.uuid4().hex}{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as output:
        shutil.copyfileobj(file.file, output)

    conn.execute(
        """INSERT INTO assets(
          source_id, source_asset_id, original_filename, path, sha256, size_bytes, mime, taken_at, extra
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id, source_asset_id) DO UPDATE SET
          original_filename = excluded.original_filename,
          path = excluded.path,
          deleted = 0""",
        (
            source["id"],
            source_asset_id,
            original_filename or file.filename,
            str(destination),
            sha256_file(str(destination)),
            destination.stat().st_size,
            file.content_type or "application/octet-stream",
            taken_at,
            "{}",
        ),
    )
    asset_id = conn.execute(
        "SELECT id FROM assets WHERE source_id = ? AND source_asset_id = ?",
        (source["id"], source_asset_id),
    ).fetchone()["id"]
    job_id = jobs.push(conn, "import", {"paths": [str(destination)]})
    mark_source_status(
        conn,
        source_id=source["id"],
        status="connected",
        authorization_state=authorization_state,
        asset_count=asset_count,
    )
    return {
        "status": "queued",
        "duplicate": False,
        "asset_id": asset_id,
        "job_id": job_id,
        "source_asset_id": source_asset_id,
        "path": str(destination),
    }
