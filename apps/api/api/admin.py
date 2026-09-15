"""Admin settings, status, and manual scan endpoints."""

from __future__ import annotations

import os
import shutil
from collections import Counter
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import jobs
from core.settings import get_all, set_value

from .deps import WORKER_URL, get_conn

router = APIRouter()
WATCH_ROOT = Path(os.environ.get("PICS_WATCH_ROOT", "/media/photos"))
MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".mov", ".mp4", ".avif", ".dng"}


class SettingsUpdate(BaseModel):
    watch_enabled: str | None = Field(default=None, pattern="^[01]$")
    watch_backfill: str | None = Field(default=None, pattern="^(prompt|backfill|done)$")


class ScanRequest(BaseModel):
    root: str | None = None


def _models_ready() -> bool:
    try:
        response = httpx.get(f"{WORKER_URL}/v1/status", timeout=3)
        return response.json().get("ok") is True
    except httpx.HTTPError:
        return False


def _library_inventory() -> dict:
    """Report what the mounted source exposes without importing anything."""
    suffixes = Counter()
    photos_libraries = []
    media_files = 0
    directories_with_errors = []

    if not WATCH_ROOT.is_dir():
        return {
            "root": str(WATCH_ROOT),
            "available": False,
            "media_files": 0,
            "extensions": {},
            "photos_libraries": [],
            "directory_errors": [],
        }

    for directory, dirnames, filenames in os.walk(
        WATCH_ROOT, onerror=lambda error: directories_with_errors.append(str(error))
    ):
        directory_path = Path(directory)
        for dirname in dirnames:
            if dirname.endswith(".photoslibrary"):
                photos_libraries.append({"name": dirname, "path": str(directory_path / dirname)})
        for filename in filenames:
            suffix = Path(filename).suffix.lower()
            if suffix in MEDIA_SUFFIXES:
                media_files += 1
                suffixes[suffix] += 1

    return {
        "root": str(WATCH_ROOT),
        "available": True,
        "media_files": media_files,
        "extensions": dict(sorted(suffixes.items())),
        "photos_libraries": photos_libraries,
        "directory_errors": directories_with_errors[:20],
    }


@router.get("/status")
def status(conn=Depends(get_conn)):
    root_available = WATCH_ROOT.is_dir()
    try:
        usage = shutil.disk_usage(WATCH_ROOT)
        disk = {"total": usage.total, "used": usage.used, "free": usage.free}
    except OSError:
        disk = None
    counts = {
        "assets": conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0],
        "faces": conn.execute("SELECT COUNT(*) FROM faces").fetchone()[0],
        "persons": conn.execute("SELECT COUNT(*) FROM persons").fetchone()[0],
        "jobs": conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
    }
    return {
        "mount_source": os.environ.get("PICS_MOUNT_SOURCE"),
        "watch_root": str(WATCH_ROOT),
        "root_available": root_available,
        "models_ready": _models_ready(),
        "disk": disk,
        "counts": counts,
        "settings": get_all(conn),
    }


@router.get("/settings")
def read_settings(conn=Depends(get_conn)):
    return {"settings": get_all(conn)}


@router.get("/library")
def library_inventory(conn=Depends(get_conn)):
    inventory = _library_inventory()
    root = str(WATCH_ROOT.resolve())
    prefix = f"{root}{os.sep}%"
    inventory["catalog"] = {
        "assets": conn.execute("SELECT COUNT(*) FROM assets WHERE deleted = 0").fetchone()[0],
        "mounted_assets": conn.execute(
            "SELECT COUNT(*) FROM assets WHERE deleted = 0 AND path LIKE ?", (prefix,)
        ).fetchone()[0],
        "faces": conn.execute("SELECT COUNT(*) FROM faces").fetchone()[0],
    }
    return inventory


@router.patch("/settings")
def update_settings(update: SettingsUpdate, conn=Depends(get_conn)):
    if update.watch_enabled is not None:
        set_value(conn, "watch_enabled", update.watch_enabled)
    if update.watch_backfill is not None:
        set_value(conn, "watch_backfill", update.watch_backfill)
    return {"settings": get_all(conn)}


@router.post("/scan")
def scan(request: ScanRequest | None = None, conn=Depends(get_conn)):
    root = Path(request.root) if request and request.root else WATCH_ROOT
    if not root.is_dir():
        raise HTTPException(status_code=400, detail=f"root is not a directory: {root}")
    paths = [
        str(path)
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in MEDIA_SUFFIXES
    ]
    job_id = jobs.push(conn, "scan", {"paths": paths})
    return {"job_id": job_id, "paths": len(paths), "status": "queued"}
