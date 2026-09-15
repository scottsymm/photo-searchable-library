"""Holistic catalog overview endpoint."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from core.sources import classify_path
from core.settings import get as get_setting

from .admin import cached_library_inventory, inventory_scanned_at
from .deps import get_conn
from .sources import _source_with_bridge_status

router = APIRouter()

STAGE_KEYS = (
    "discovered", "ready_to_import", "importing", "imported", "processing",
    "searchable", "failed_or_blocked",
)


def _empty_stages() -> dict[str, int]:
    return {key: 0 for key in STAGE_KEYS}


def _latest_sync(conn: sqlite3.Connection, source_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM source_syncs WHERE source_id = ? ORDER BY id DESC LIMIT 1",
        (source_id,),
    ).fetchone()


def _job_paths(conn: sqlite3.Connection, statuses: tuple[str, ...]) -> dict[str, set[str]]:
    """Classify paths referenced by import/scan jobs into per-source sets."""
    placeholders = ", ".join("?" for _ in statuses)
    rows = conn.execute(
        f"SELECT params FROM jobs WHERE kind IN ('import', 'scan') AND status IN ({placeholders})",
        statuses,
    ).fetchall()
    result: dict[str, set[str]] = {}
    for row in rows:
        for path in json.loads(row["params"] or "{}").get("paths", []):
            kind = classify_path(path)
            if kind is not None:
                result.setdefault(kind, set()).add(path)
    return result


def _failed_job_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT params FROM jobs WHERE kind IN ('import', 'scan') AND status = 'error'"
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        paths = json.loads(row["params"] or "{}").get("paths", [])
        if not paths:
            continue
        kind = classify_path(paths[0])
        if kind is not None:
            counts[kind] = counts.get(kind, 0) + 1
    return counts


def _processing_counts(conn: sqlite3.Connection, source_id: int, active_paths: set[str]) -> dict[str, int]:
    rows = conn.execute(
        """SELECT a.path,
          EXISTS (SELECT 1 FROM content_embeds e WHERE e.asset_id = a.id) AS embedded
        FROM assets a WHERE a.source_id = ? AND a.deleted = 0""",
        (source_id,),
    ).fetchall()
    return {
        "imported": len(rows),
        "searchable": sum(1 for row in rows if row["embedded"]),
        "processing": sum(1 for row in rows if not row["embedded"] and row["path"] in active_paths),
        "stuck": sum(1 for row in rows if not row["embedded"] and row["path"] not in active_paths),
    }


def _readiness(source: sqlite3.Row, latest_sync: sqlite3.Row | None) -> tuple[str, str | None]:
    auth = source["authorization_state"]
    if auth in ("denied", "restricted", "notDetermined"):
        return "authorization_required", f"Photos authorization is {auth}"
    if latest_sync is not None and latest_sync["status"] == "error":
        return "failed", latest_sync["error"] or "last sync failed"
    if source["last_error"]:
        return "failed", source["last_error"]
    if source["status"] == "not_connected" and source["last_sync_at"] is None and latest_sync is None:
        return "not_configured", None
    if source["asset_count"] == 0 and not (
        latest_sync is not None and latest_sync["status"] in ("done", "partial")
    ):
        return "inventory_pending", "waiting for the bridge to report library totals"
    return "connected", None


def _apple_entry(conn, source, latest_sync, active):
    counts = _processing_counts(conn, source["id"], active.get("apple_photos", set()))
    stages = _empty_stages()
    stages["discovered"] = source["asset_count"]
    stages["imported"] = counts["imported"]
    stages["ready_to_import"] = max(0, source["asset_count"] - counts["imported"])
    if latest_sync is not None and latest_sync["status"] in ("queued", "running"):
        stages["importing"] = (
            stages["ready_to_import"] if latest_sync["full_sync"]
            else min(latest_sync["limit_count"], stages["ready_to_import"])
        )
    stages["processing"] = counts["processing"]
    stages["searchable"] = counts["searchable"]
    stages["failed_or_blocked"] = counts["stuck"] + (
        latest_sync["failed_count"]
        if latest_sync is not None and latest_sync["status"] in ("partial", "error") else 0
    )
    readiness, detail = _readiness(source, latest_sync)
    return {
        "kind": "apple_photos", "display_name": source["display_name"],
        "readiness": readiness, "readiness_detail": detail,
        "reported_at": source["last_sync_at"], "stages": stages,
        "bridge_status": source["bridge_status"],
        "bridge_last_seen_at": source["bridge_last_seen_at"],
        "authorization_state": source["authorization_state"],
        "watch_enabled": False,
        "ingest_mode": "bridge",
        "sync": dict(latest_sync) if latest_sync is not None else None,
        "actions": {"can_sync": True},
    }


def _mounted_entry(conn, source, inventory, active, failed_jobs):
    counts = _processing_counts(conn, source["id"], active.get("mounted_folder", set()))
    available = inventory["available"]
    stages = _empty_stages()
    stages["discovered"] = inventory["media_files"] if available else 0
    stages["imported"] = counts["imported"]
    stages["ready_to_import"] = max(0, stages["discovered"] - counts["imported"])
    stages["importing"] = len(active.get("mounted_folder", set()))
    stages["processing"] = counts["processing"]
    stages["searchable"] = counts["searchable"]
    stages["failed_or_blocked"] = counts["stuck"] + failed_jobs.get("mounted_folder", 0)
    readiness, detail = ("connected", None) if available else ("failed", f"watch root is not available: {inventory['root']}")
    return {
        "kind": "mounted_folder", "display_name": source["display_name"],
        "readiness": readiness, "readiness_detail": detail,
        "reported_at": inventory_scanned_at(), "stages": stages, "sync": None,
        "watch_enabled": get_setting(conn, "watch_enabled", "0") == "1",
        "ingest_mode": "watch",
        "actions": {"can_sync": False},
    }


def _uploads_entry(conn, source, active, failed_jobs):
    counts = _processing_counts(conn, source["id"], active.get("uploads", set()))
    stages = _empty_stages()
    stages["discovered"] = counts["imported"]
    stages["imported"] = counts["imported"]
    stages["importing"] = len(active.get("uploads", set()))
    stages["processing"] = counts["processing"]
    stages["searchable"] = counts["searchable"]
    stages["failed_or_blocked"] = counts["stuck"] + failed_jobs.get("uploads", 0)
    return {
        "kind": "uploads", "display_name": source["display_name"],
        "readiness": "connected", "readiness_detail": None, "reported_at": None,
        "stages": stages, "sync": None, "watch_enabled": False,
        "ingest_mode": "manual", "actions": {"can_sync": False},
    }


def _context(conn: sqlite3.Connection, inventory: dict) -> dict:
    recent = conn.execute(
        """SELECT a.id, s.kind AS source_kind, a.original_filename,
          a.created_at AS imported_at, a.taken_at
        FROM assets a LEFT JOIN sources s ON s.id = a.source_id
        WHERE a.deleted = 0
        ORDER BY a.thumbnail_id IS NULL, a.created_at IS NULL, a.created_at DESC, a.taken_at DESC LIMIT 6"""
    ).fetchall()
    faces_total = conn.execute("SELECT COUNT(*) FROM faces").fetchone()[0]
    assigned = conn.execute("SELECT COUNT(DISTINCT face_id) FROM person_faces").fetchone()[0]
    located = conn.execute("SELECT COUNT(*) FROM assets WHERE deleted = 0 AND gps_lat IS NOT NULL").fetchone()[0]
    total_assets = conn.execute("SELECT COUNT(*) FROM assets WHERE deleted = 0").fetchone()[0]
    return {
        "recent_imports": [dict(row) for row in recent],
        "photos_libraries": inventory["photos_libraries"],
        "faces": {"total": faces_total, "assigned": assigned, "unassigned": faces_total - assigned},
        "places": {"located": located, "unlocated": total_assets - located},
    }


@router.get("/overview")
def catalog_overview(conn=Depends(get_conn)):
    inventory = cached_library_inventory()
    active = _job_paths(conn, ("queued", "working"))
    failed_jobs = _failed_job_counts(conn)
    rows = {row["kind"]: row for row in conn.execute("SELECT * FROM sources")}
    apple_source = _source_with_bridge_status(rows["apple_photos"])
    entries = [
        _apple_entry(conn, apple_source, _latest_sync(conn, apple_source["id"]), active),
        _mounted_entry(conn, rows["mounted_folder"], inventory, active, failed_jobs),
        _uploads_entry(conn, rows["uploads"], active, failed_jobs),
    ]
    funnel = _empty_stages()
    for entry in entries:
        for key in STAGE_KEYS:
            funnel[key] += entry["stages"][key]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "funnel": funnel, "sources": entries, "context": _context(conn, inventory),
    }
