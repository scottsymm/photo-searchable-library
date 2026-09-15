"""External source ingest and status endpoints."""

from __future__ import annotations

import os
import json
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field

from core import jobs
from core.assets import sha256_file
from core.sources import get_source, mark_source_status

from .deps import get_conn

router = APIRouter()
LIBRARY = Path(os.environ.get("PICS_LIBRARY", "library"))
SYNC_LEASE_SECONDS = int(os.environ.get("PICS_SOURCE_SYNC_LEASE_SECONDS", "3600"))
BRIDGE_LEASE_SECONDS = int(os.environ.get("PICS_BRIDGE_LEASE_SECONDS", "15"))


class SyncRequest(BaseModel):
    limit: int = Field(default=25, ge=1, le=500)
    full: bool = False


class KnownAssetsRequest(BaseModel):
    source_asset_ids: list[str] = Field(min_length=1, max_length=500)


class BridgeHeartbeat(BaseModel):
    authorization_state: str
    asset_count: int = Field(ge=0)


def _sync_dict(row):
    return dict(row) if row is not None else None


def _bridge_status(authorization_state: str, asset_count: int) -> str:
    if authorization_state in ("denied", "restricted", "notDetermined"):
        return "authorization_required"
    return "inventory_pending" if asset_count == 0 else "connected"


def _source_with_bridge_status(source):
    result = dict(source)
    last_seen = result.get("bridge_last_seen_at")
    if last_seen is None:
        result["bridge_status"] = "offline"
    else:
        seen_at = datetime.fromisoformat(last_seen)
        age = datetime.now(timezone.utc) - seen_at
        if age.total_seconds() > BRIDGE_LEASE_SECONDS:
            result["bridge_status"] = "offline"
    return result


def _active_import_exists(conn, path: str) -> bool:
    rows = conn.execute(
        "SELECT params FROM jobs WHERE kind = 'import' AND status IN ('queued', 'working')"
    ).fetchall()
    return any(path in json.loads(row["params"] or "{}").get("paths", []) for row in rows)


def _recover_stale_syncs(conn, source_id: int) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=SYNC_LEASE_SECONDS)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """UPDATE source_syncs SET status = 'error', completed_at = ?,
        error = 'bridge lease expired'
        WHERE source_id = ? AND status = 'running' AND started_at < ?""",
        (now, source_id, cutoff),
    )
    conn.commit()


@router.post("/apple-photos/sync")
def request_apple_photos_sync(request: SyncRequest, conn=Depends(get_conn)):
    source = get_source(conn, "apple_photos")
    _recover_stale_syncs(conn, source["id"])
    active = conn.execute(
        """SELECT * FROM source_syncs
        WHERE source_id = ? AND status IN ('queued', 'running')
        ORDER BY id DESC LIMIT 1""",
        (source["id"],),
    ).fetchone()
    if active is not None:
        return {"sync": _sync_dict(active), "already_active": True}
    cursor = conn.execute(
        "INSERT INTO source_syncs(source_id, limit_count, full_sync) VALUES (?, ?, ?)",
        (source["id"], request.limit, int(request.full)),
    )
    conn.commit()
    sync = conn.execute("SELECT * FROM source_syncs WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return {"sync": _sync_dict(sync), "already_active": False}


@router.post("/apple-photos/assets/known")
def known_apple_photos_assets(request: KnownAssetsRequest, conn=Depends(get_conn)):
    source = get_source(conn, "apple_photos")
    placeholders = ", ".join("?" for _ in request.source_asset_ids)
    rows = conn.execute(
        f"""SELECT source_asset_id FROM assets
        WHERE source_id = ? AND source_asset_id IN ({placeholders}) AND deleted = 0""",
        (source["id"], *request.source_asset_ids),
    ).fetchall()
    return {"source_asset_ids": [row["source_asset_id"] for row in rows]}


@router.get("/apple-photos/sync/status")
def apple_photos_sync_status(conn=Depends(get_conn)):
    source = get_source(conn, "apple_photos")
    _recover_stale_syncs(conn, source["id"])
    sync = conn.execute(
        "SELECT * FROM source_syncs WHERE source_id = ? ORDER BY id DESC LIMIT 1",
        (source["id"],),
    ).fetchone()
    return {"sync": _sync_dict(sync)}


@router.post("/apple-photos/bridge/heartbeat")
def apple_photos_bridge_heartbeat(heartbeat: BridgeHeartbeat, conn=Depends(get_conn)):
    source = get_source(conn, "apple_photos")
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """UPDATE sources SET bridge_status = ?, bridge_last_seen_at = ?,
        authorization_state = ?, asset_count = ?, updated_at = ? WHERE id = ?""",
        (_bridge_status(heartbeat.authorization_state, heartbeat.asset_count), now,
         heartbeat.authorization_state, heartbeat.asset_count, now, source["id"]),
    )
    conn.commit()
    return {"source": _source_with_bridge_status(get_source(conn, "apple_photos"))}


@router.post("/apple-photos/sync/claim")
def claim_apple_photos_sync(conn=Depends(get_conn)):
    source = get_source(conn, "apple_photos")
    _recover_stale_syncs(conn, source["id"])
    sync = conn.execute(
        """SELECT * FROM source_syncs
        WHERE source_id = ? AND status = 'queued'
        ORDER BY id LIMIT 1""",
        (source["id"],),
    ).fetchone()
    if sync is None:
        return {"sync": None}
    now = datetime.now(timezone.utc).isoformat()
    updated = conn.execute(
        """UPDATE source_syncs SET status = 'running', started_at = ?
        WHERE id = ? AND status = 'queued'""",
        (now, sync["id"]),
    )
    conn.commit()
    if updated.rowcount != 1:
        return {"sync": None}
    claimed = conn.execute("SELECT * FROM source_syncs WHERE id = ?", (sync["id"],)).fetchone()
    return {"sync": _sync_dict(claimed)}


@router.post("/apple-photos/sync/{sync_id}/complete")
def complete_apple_photos_sync(sync_id: int, imported_count: int = Form(0), failed_count: int = Form(0), error: str | None = Form(None), conn=Depends(get_conn)):
    status = "partial" if error and imported_count else "error" if error else "done"
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """UPDATE source_syncs SET status = ?, completed_at = ?, imported_count = ?, failed_count = ?, error = ?
        WHERE id = ?""",
        (status, now, imported_count, failed_count, error, sync_id),
    )
    conn.commit()
    sync = conn.execute("SELECT * FROM source_syncs WHERE id = ?", (sync_id,)).fetchone()
    return {"sync": _sync_dict(sync)}


@router.get("/apple-photos/status")
def apple_photos_status(conn=Depends(get_conn)):
    source = _source_with_bridge_status(get_source(conn, "apple_photos"))
    imported = conn.execute(
        """SELECT COUNT(*) FROM assets
        WHERE source_id = ? AND deleted = 0
          AND EXISTS (SELECT 1 FROM content_embeds WHERE asset_id = assets.id)""",
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
        """SELECT assets.id, assets.path,
          EXISTS (SELECT 1 FROM content_embeds WHERE asset_id = assets.id) AS processed
        FROM assets
        WHERE source_id = ? AND source_asset_id = ? AND deleted = 0""",
        (source["id"], source_asset_id),
    ).fetchone()
    if existing is not None and existing["path"] and Path(existing["path"]).is_file():
        mark_source_status(
            conn,
            source_id=source["id"],
            status="connected",
            authorization_state=authorization_state,
            asset_count=asset_count,
        )
        if existing["processed"] or _active_import_exists(conn, existing["path"]):
            return {
                "status": "duplicate",
                "duplicate": True,
                "asset_id": existing["id"],
                "source_asset_id": source_asset_id,
            }
        job_id = jobs.push(conn, "import", {"paths": [existing["path"]]})
        return {
            "status": "queued",
            "duplicate": True,
            "retried": True,
            "asset_id": existing["id"],
            "job_id": job_id,
            "source_asset_id": source_asset_id,
            "path": existing["path"],
        }

    suffix = Path(original_filename or file.filename or "photo.jpg").suffix.lower() or ".jpg"
    destination = LIBRARY / "apple-photos" / f"{uuid.uuid4().hex}{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as output:
        shutil.copyfileobj(file.file, output)

    conn.execute(
        """INSERT INTO assets(
          source_id, source_asset_id, original_filename, path, sha256, size_bytes, mime, taken_at, extra, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            datetime.now(timezone.utc).isoformat(),
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
