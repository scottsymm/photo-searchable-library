"""Upload and thumbnail endpoints."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile

from core import jobs

from .deps import get_conn

router = APIRouter()
LIBRARY = Path(os.environ.get("PICS_LIBRARY", "library"))


@router.post("/upload")
async def upload(file: UploadFile = File(...), conn=Depends(get_conn)):
    suffix = (Path(file.filename or "photo.jpg").suffix or ".jpg").lower()
    destination = LIBRARY / "imports" / f"{uuid.uuid4().hex}{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as output:
        shutil.copyfileobj(file.file, output)
    job_id = jobs.push(conn, "import", {"paths": [str(destination)]})
    return {"job_id": job_id, "status": "queued", "path": str(destination)}


@router.get("/{asset_id}/thumbnail")
def thumbnail(asset_id: int, conn=Depends(get_conn)):
    row = conn.execute(
        """SELECT files.bytes FROM assets JOIN files ON files.id = assets.thumbnail_id
        WHERE assets.id = ? AND assets.deleted = 0""",
        (asset_id,),
    ).fetchone()
    if row is None or row["bytes"] is None:
        raise HTTPException(status_code=404, detail="thumbnail not found")
    return Response(content=row["bytes"], media_type="image/jpeg")
