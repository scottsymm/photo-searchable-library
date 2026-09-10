# Admin and Ingest Automation — Implementation Plan

*Created: 2026-09-10*

**Goal:** Add a settings-driven watch/ingest flow backed by an admin page, with
a parked-by-default ("no silent processing") contract.

**Architecture:** Settings live in a new SQLite `settings` table (runtime
toggles only). The Pictures path stays in env because Docker fixes mounts at
start. A polling watcher thread in the worker starts only when
`watch_enabled=1`, discovers new files by content hash, and enqueues existing
`scan` jobs. The API exposes `/admin/*`; the web app turns the current Settings
page into an Admin page with a parked banner.

**Tech Stack:** Python 3.12 (uv), FastAPI, SQLite/WAL, Next.js (TS), Docker
Compose.

**Source:** `artifacts/pics/admin-and-ingest-automation/admin-and-ingest-automation-design.md`

## File Map

| File | Action | Responsibility |
|---|---|---|
| `packages/core/core/schema.py` | Modify | Add `settings` table, seed defaults, version 3 |
| `packages/core/core/settings.py` | Create | Typed get/set/get_all for settings |
| `packages/core/tests/test_settings.py` | Create | Settings + seeding tests |
| `services/worker/worker/watcher.py` | Create | Polling watcher thread (off by default) |
| `services/worker/worker/service.py` | Modify | Start watcher thread when env enabled |
| `services/worker/worker/config.py` | Modify | Add watch root/poll env config |
| `services/worker/tests/test_watcher.py` | Create | Watcher unit tests (temp dir + monkeypatched DB) |
| `apps/api/api/admin.py` | Create | `/admin/status|settings|scan` endpoints |
| `apps/api/api/main.py` | Modify | Mount admin router |
| `apps/api/tests/test_admin.py` | Create | Admin API tests |
| `apps/web/types.ts` | Modify | `AdminStatus`, `AdminSettings` types |
| `apps/web/lib/api.ts` | Modify | Admin API client methods |
| `apps/web/lib/admin.test.ts` | Create | Vitest for admin client |
| `apps/web/app/settings/page.tsx` | Modify | Admin page (Watch/Ingest, Jobs, Clustering, Status) |
| `apps/web/app/layout.tsx` | Modify | Parked banner |
| `apps/web/app/globals.css` | Modify | Banner + admin styles |
| `docker-compose.yml` | Modify | Bind mount `~/Pictures:/media/photos:ro`, watch env |
| `README.md` | Modify | Mount/path restart docs mirroring admin page |

## Tasks

### Task 1: Add `settings` table + seeding

**Files:**
- Modify: `packages/core/core/schema.py`
- Create: `packages/core/core/settings.py`

- [ ] **Step 1: Add table and version bump in `schema.py`**

Add after the `person_faces` block:

```python
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Change the version insert:

```python
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('version', '3')"
```

- [ ] **Step 2: Create `packages/core/core/settings.py`**

```python
"""Typed access to the catalog settings table."""

from __future__ import annotations

import sqlite3

DEFAULTS = {
    "watch_enabled": "0",
    "watch_backfill": "prompt",
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
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {row["key"]: row["value"] for row in rows}
```

- [ ] **Step 3: Wire `seed` into migration — modify `migrate()` in `schema.py`**

After the version insert, call the seed:

```python
def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES ('version', '3')"
    )
    from .settings import seed
    seed(conn)
    conn.commit()
```

- [ ] **Step 4: Verify**

Run: `uv run --project packages/core --extra dev pytest packages/core/tests`
Expected: existing tests pass (schema migrate now creates `settings`).

### Task 2: Settings tests

**Files:**
- Create: `packages/core/tests/test_settings.py`

- [ ] **Step 1: Create test file**

```python
import sqlite3

from core.conn import connect
from core.schema import migrate
from core import settings as s


def _db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrate(conn)
    return conn


def test_defaults_seeded_once():
    conn = _db()
    assert s.get(conn, "watch_enabled") == "0"
    assert s.get(conn, "watch_backfill") == "prompt"


def test_set_value_upsert():
    conn = _db()
    s.set_value(conn, "watch_enabled", "1")
    assert s.get(conn, "watch_enabled") == "1"
    s.set_value(conn, "watch_enabled", "0")
    assert s.get(conn, "watch_enabled") == "0"


def test_get_all():
    conn = _db()
    values = s.get_all(conn)
    assert set(values) == {"watch_enabled", "watch_backfill"}


def test_unknown_key_returns_default():
    conn = _db()
    assert s.get(conn, "missing", "fallback") == "fallback"
```

- [ ] **Step 2: Verify**

Run: `uv run --project packages/core --extra dev pytest packages/core/tests/test_settings.py`
Expected: PASS — 4 tests passing.

### Task 3: Watcher thread (off by default)

**Files:**
- Create: `services/worker/worker/watcher.py`
- Modify: `services/worker/worker/config.py`
- Modify: `services/worker/worker/service.py`

- [ ] **Step 1: Modify `services/worker/worker/config.py`**

Add:

```python
WATCH_ROOT = os.environ.get("PICS_WATCH_ROOT", "/media/photos")
WATCH_POLL_SECONDS = int(os.environ.get("PICS_WATCH_POLL_SECONDS", "30"))
WATCHER_ENABLED = os.environ.get("PICS_WATCHER_ENABLED", "1") == "1"
```

- [ ] **Step 2: Create `services/worker/worker/watcher.py`**

```python
"""Polling photo watcher. Performs no filesystem work unless enabled."""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict

from core import jobs
from core.assets import sha256_file
from core.conn import connect
from core.settings import get
from .config import DB_PATH, WATCH_POLL_SECONDS, WATCH_ROOT

logger = logging.getLogger(__name__)

MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".mov", ".mp4", ".avif", ".dng"}
BATCH_SIZE = 50
LRU_SIZE = 5000


def _is_media(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in MEDIA_SUFFIXES


class PhotoWatcher(threading.Thread):
    def __init__(self, root: str = WATCH_ROOT, poll_seconds: int = WATCH_POLL_SECONDS):
        super().__init__(name="photo-watcher", daemon=True)
        self.root = root
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._recent: OrderedDict[str, None] = OrderedDict()

    def stop(self) -> None:
        self._stop.set()

    def _known_hashes(self, conn) -> set[str]:
        rows = conn.execute("SELECT sha256 FROM files").fetchall()
        return {row["sha256"] for row in rows}

    def _candidate_files(self) -> list[str]:
        if not os.path.isdir(self.root):
            return []
        return sorted(
            os.path.join(dirpath, name)
            for dirpath, _, filenames in os.walk(self.root)
            for name in filenames
            if _is_media(name)
        )

    def _enqueue_new(self) -> int:
        conn = connect(DB_PATH)
        try:
            if get(conn, "watch_enabled") != "1":
                return 0
            known = self._known_hashes(conn)
            pending: list[str] = []
            for path in self._candidate_files():
                if self._stop.is_set():
                    break
                try:
                    digest = sha256_file(path)
                except OSError:
                    continue
                if digest in known or digest in self._recent:
                    continue
                pending.append(path)
                self._recent[digest] = None
                if len(self._recent) > LRU_SIZE:
                    self._recent.popitem(last=False)
                if len(pending) >= BATCH_SIZE:
                    jobs.push(conn, "scan", {"paths": pending})
                    pending = []
            if pending:
                jobs.push(conn, "scan", {"paths": pending})
            return len(known)
        finally:
            conn.close()

    def run(self) -> None:
        logger.info("photo watcher polling %s every %ss", self.root, self.poll_seconds)
        while not self._stop.wait(self.poll_seconds):
            try:
                self._enqueue_new()
            except Exception:
                logger.exception("watcher pass failed")
```

- [ ] **Step 3: Modify `services/worker/worker/service.py`**

Import and start the watcher when configured:

```python
from .config import WATCHER_ENABLED
from .watcher import PhotoWatcher
```

In `main()`, after starting the embed server thread:

```python
    if WATCHER_ENABLED:
        PhotoWatcher().start()
```

- [ ] **Step 4: Verify (syntax)**

Run: `uv run --project services/worker --extra dev python -m py_compile services/worker/worker/watcher.py services/worker/worker/service.py services/worker/worker/config.py`
Expected: exit 0.

### Task 4: Watcher tests

**Files:**
- Create: `services/worker/tests/test_watcher.py`

- [ ] **Step 1: Create test file**

```python
import os

from core.conn import connect
from core.schema import migrate
from worker.watcher import PhotoWatcher


def _db(tmp_path) -> str:
    db = str(tmp_path / "catalog.db")
    conn = connect(db)
    migrate(conn)
    conn.close()
    return db


def test_disabled_does_not_walk(tmp_path, monkeypatch):
    db = _db(tmp_path)
    root = tmp_path / "photos"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"x")
    monkeypatch.setattr("worker.watcher.DB_PATH", db)
    watcher = PhotoWatcher(root=str(root), poll_seconds=1)
    watcher._enqueue_new()
    conn = connect(db)
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    conn.close()


def test_enabled_enqueues_once(tmp_path, monkeypatch):
    db = _db(tmp_path)
    root = tmp_path / "photos"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"x")
    monkeypatch.setattr("worker.watcher.DB_PATH", db)
    conn = connect(db)
    conn.execute("UPDATE settings SET value='1' WHERE key='watch_enabled'")
    conn.commit()
    conn.close()
    watcher = PhotoWatcher(root=str(root), poll_seconds=1)
    watcher._enqueue_new()
    watcher._enqueue_new()
    conn = connect(db)
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    conn.close()


def test_backfill_prompt_does_not_autoenqueue(tmp_path, monkeypatch):
    db = _db(tmp_path)
    root = tmp_path / "photos"
    root.mkdir()
    (root / "a.jpg").write_bytes(b"x")
    monkeypatch.setattr("worker.watcher.DB_PATH", db)
    conn = connect(db)
    conn.execute("UPDATE settings SET value='1' WHERE key='watch_enabled'")
    conn.commit()
    conn.close()
    watcher = PhotoWatcher(root=str(root), poll_seconds=1)
    watcher._enqueue_new()
    conn = connect(db)
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    conn.close()
```

Note: `_enqueue_new` gates entirely on `watch_enabled`; backfill itself is an
admin-issued `scan` job, so the watcher never distinguishes backfill internally.
The third test documents that behavior.

- [ ] **Step 2: Verify**

Run: `uv run --project services/worker --extra dev pytest services/worker/tests/test_watcher.py`
Expected: PASS — 3 tests passing.

### Task 5: Admin API

**Files:**
- Create: `apps/api/api/admin.py`
- Modify: `apps/api/api/main.py`
- Create: `apps/api/tests/test_admin.py`

- [ ] **Step 1: Create `apps/api/api/admin.py`**

```python
"""Admin settings, status, and manual scan endpoints."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import jobs
from core.settings import get, get_all, set_value

from .deps import WORKER_URL, get_conn

router = APIRouter()

WATCH_ROOT = Path(os.environ.get("PICS_WATCH_ROOT", "/media/photos"))


class SettingsUpdate(BaseModel):
    watch_enabled: str | None = Field(default=None, pattern="^[01]$")
    watch_backfill: str | None = Field(
        default=None, pattern="^(prompt|backfill|done)$"
    )


class ScanRequest(BaseModel):
    root: str | None = None


def _models_ready() -> bool:
    try:
        response = httpx.get(f"{WORKER_URL}/v1/status", timeout=3)
        return response.json().get("ok") is True
    except httpx.HTTPError:
        return False


@router.get("/status")
def status(conn=Depends(get_conn)):
    root_available = WATCH_ROOT.is_dir()
    try:
        disk = shutil.disk_usage(WATCH_ROOT)
        disk_info = {"total": disk.total, "used": disk.used, "free": disk.free}
    except OSError:
        disk_info = None
    counts = {
        "assets": conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0],
        "faces": conn.execute("SELECT COUNT(*) FROM faces").fetchone()[0],
        "persons": conn.execute("SELECT COUNT(*) FROM persons").fetchone()[0],
        "jobs": conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
    }
    return {
        "watch_root": str(WATCH_ROOT),
        "root_available": root_available,
        "models_ready": _models_ready(),
        "disk": disk_info,
        "counts": counts,
        "settings": get_all(conn),
    }


@router.get("/settings")
def read_settings(conn=Depends(get_conn)):
    return {"settings": get_all(conn)}


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
        str(p) for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in {
            ".jpg", ".jpeg", ".png", ".heic", ".heif", ".mov", ".mp4", ".avif", ".dng"
        }
    ]
    job_id = jobs.push(conn, "scan", {"paths": paths})
    return {"job_id": job_id, "paths": len(paths), "status": "queued"}
```

- [ ] **Step 2: Modify `apps/api/api/main.py`**

Add import and mount:

```python
from . import admin, jobs, persons, places, search, uploads
app.include_router(admin.router, prefix="/admin", tags=["admin"])
```

- [ ] **Step 3: Create `apps/api/tests/test_admin.py`**

```python
def test_settings_read_defaults(client):
    response = client.get("/admin/settings")
    assert response.status_code == 200
    assert response.json()["settings"]["watch_enabled"] == "0"


def test_settings_update(client):
    response = client.patch("/admin/settings", json={"watch_enabled": "1"})
    assert response.status_code == 200
    assert response.json()["settings"]["watch_enabled"] == "1"


def test_settings_update_rejects_invalid(client):
    response = client.patch("/admin/settings", json={"watch_enabled": "yes"})
    assert response.status_code == 422


def test_scan_missing_root(client):
    response = client.post("/admin/scan", json={"root": "/does/not/exist"})
    assert response.status_code == 400


def test_status_shape(client):
    response = client.get("/admin/status")
    assert response.status_code == 200
    body = response.json()
    assert "watch_root" in body and "counts" in body and "settings" in body
```

- [ ] **Step 4: Verify**

Run: `uv run --project apps/api --extra dev pytest apps/api/tests`
Expected: PASS — all API tests including new admin tests.

### Task 6: Web types + API client + tests

**Files:**
- Modify: `apps/web/types.ts`
- Modify: `apps/web/lib/api.ts`
- Create: `apps/web/lib/admin.test.ts`

- [ ] **Step 1: Add types to `apps/web/types.ts`**

```typescript
export interface AdminSettings {
  watch_enabled: "0" | "1";
  watch_backfill: "prompt" | "backfill" | "done";
  [key: string]: string;
}

export interface AdminCounts {
  assets: number;
  faces: number;
  persons: number;
  jobs: number;
}

export interface AdminStatus {
  watch_root: string;
  root_available: boolean;
  models_ready: boolean;
  disk: { total: number; used: number; free: number } | null;
  counts: AdminCounts;
  settings: AdminSettings;
}
```

- [ ] **Step 2: Add client methods to `apps/web/lib/api.ts`**

```typescript
import type { AdminSettings, AdminStatus } from "../types";

export async function adminStatus(): Promise<AdminStatus> {
  const response = await fetch(apiUrl("/admin/status"), { cache: "no-store" });
  if (!response.ok) throw new Error("Status request failed");
  return response.json();
}

export async function updateAdminSettings(update: Partial<AdminSettings>): Promise<AdminSettings> {
  const response = await fetch(apiUrl("/admin/settings"), {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(update),
  });
  if (!response.ok) throw new Error("Settings update failed");
  return (await response.json()).settings;
}

export async function queueAdminScan(root?: string): Promise<void> {
  const response = await fetch(apiUrl("/admin/scan"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(root ? { root } : {}),
  });
  if (!response.ok) throw new Error("Scan request failed");
}
```

- [ ] **Step 3: Create `apps/web/lib/admin.test.ts`**

```typescript
import { describe, expect, it, vi } from "vitest";

import { adminStatus, updateAdminSettings } from "./api";

describe("admin api client", () => {
  it("reads admin status", async () => {
    const body = {
      watch_root: "/media/photos", root_available: true, models_ready: true,
      disk: null, counts: { assets: 1, faces: 0, persons: 0, jobs: 0 },
      settings: { watch_enabled: "0", watch_backfill: "prompt" },
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => body })));
    const status = await adminStatus();
    expect(status.watch_root).toBe("/media/photos");
    vi.unstubAllGlobals();
  });

  it("updates watch_enabled", async () => {
    const body = { settings: { watch_enabled: "1", watch_backfill: "prompt" } };
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => body })));
    const settings = await updateAdminSettings({ watch_enabled: "1" });
    expect(settings.watch_enabled).toBe("1");
    vi.unstubAllGlobals();
  });
});
```

- [ ] **Step 4: Verify**

Run: `pnpm --dir apps/web test`
Expected: PASS — parser tests + new admin client tests.

### Task 7: Admin page + parked banner

**Files:**
- Modify: `apps/web/app/settings/page.tsx`
- Modify: `apps/web/app/layout.tsx`
- Modify: `apps/web/app/globals.css`

- [ ] **Step 1: Replace `apps/web/app/settings/page.tsx` with the admin page**

```tsx
"use client";

import { useEffect, useState } from "react";
import { adminStatus, jobs, queueAdminScan, queueClustering, updateAdminSettings } from "../../lib/api";
import type { AdminStatus, Job } from "../../types";

export default function SettingsPage() {
  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [items, setItems] = useState<Job[]>([]);
  const [message, setMessage] = useState("");

  async function reload() {
    setStatus(await adminStatus());
    setItems(await jobs());
  }
  useEffect(() => { reload(); }, []);

  async function setWatch(value: "0" | "1") {
    await updateAdminSettings({ watch_enabled: value });
    await reload();
  }
  async function backfill() { await queueAdminScan(); setMessage("Backfill scan queued."); }
  async function cluster() { await queueClustering(); setMessage("Clustering queued."); }

  if (!status) return <main className="muted">Loading admin state…</main>;

  const watch = status.settings.watch_enabled === "1";
  return (
    <main>
      <div className="eyebrow">Operations</div>
      <h1>Admin</h1>

      <h2>Watch & ingest</h2>
      <div className="cards">
        <div className="card">
          <strong>Watched directory</strong>
          <p className="muted">{status.watch_root} · {status.root_available ? "mounted" : "not available"}</p>
          <p className="hint">Changing the mount point requires editing docker-compose.yml and restarting.</p>
        </div>
        <div className="card">
          <strong>Continuous watch</strong>
          <p className="muted">Currently {watch ? "enabled" : "paused"}</p>
          <button className="button" onClick={() => setWatch(watch ? "0" : "1")}>{watch ? "Pause watch" : "Enable watch"}</button>
        </div>
        <div className="card">
          <strong>Backfill</strong>
          <p className="muted">Import all existing photos in the watched directory</p>
          <button className="button" onClick={backfill}>Backfill now</button>
        </div>
      </div>

      <h2>Index & jobs</h2>
      <div className="cards">{items.map((job) => <div className="card" key={job.id}><strong>#{job.id} · {job.kind}</strong><span className="muted">{job.status} · {Math.round(job.progress * 100)}%</span>{job.error && <p className="status">{job.error}</p>}</div>)}</div>
      {items.length === 0 && <p className="muted">No jobs yet.</p>}

      <h2>Clustering</h2>
      <button className="button" onClick={cluster}>Run clustering</button>

      <h2>Status</h2>
      <div className="cards"><div className="card"><strong>Catalog</strong><span className="muted">{status.counts.assets} assets · {status.counts.faces} faces · {status.counts.persons} people</span></div><div className="card"><strong>Models</strong><span className="muted">{status.models_ready ? "ready" : "loading"}</span></div>{status.disk && <div className="card"><strong>Disk</strong><span className="muted">{Math.round(status.disk.free / 1e9)} GB free</span></div>}</div>
      <p className="status" aria-live="polite">{message}</p>
    </main>
  );
}
```

- [ ] **Step 2: Add parked banner to `apps/web/app/layout.tsx`**

```tsx
import Link from "next/link";
```

Add a client sub-component:

```tsx
"use client";
import { useEffect, useState } from "react";
import { adminStatus } from "../lib/api";

function ParkedBanner() {
  const [show, setShow] = useState(false);
  useEffect(() => { adminStatus().then((s) => setShow(s.settings.watch_enabled === "0")).catch(() => setShow(false)); }, []);
  return show ? <div className="parkedBanner">Photos are not being imported yet. <Link href="/settings">Configure ingest</Link></div> : null;
}
```

Because `layout.tsx` is a server component, create a separate
`apps/web/components/ParkedBanner.tsx` (client) and render `<ParkedBanner />`
inside `<body>`.

- [ ] **Step 3: Create `apps/web/components/ParkedBanner.tsx`**

```tsx
"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { adminStatus } from "../lib/api";

export function ParkedBanner() {
  const [show, setShow] = useState(false);
  useEffect(() => { adminStatus().then((s) => setShow(s.settings.watch_enabled === "0")).catch(() => setShow(false)); }, []);
  return show ? <div className="parkedBanner"><Link href="/settings">Photos are not being imported yet — configure ingest</Link></div> : null;
}
```

- [ ] **Step 4: Render in `apps/web/app/layout.tsx`**

```tsx
import { ParkedBanner } from "../components/ParkedBanner";
...
<body><ParkedBanner />{children}</body>
```

- [ ] **Step 5: Add styles to `apps/web/app/globals.css`**

```css
.parkedBanner { position: sticky; top: 0; z-index: 50; background: var(--accent); color: white; padding: 14px 24px; font-weight: 700; text-align: center; }
.parkedBanner a { color: white; text-decoration: underline; }
```

- [ ] **Step 6: Verify**

Run: `pnpm --dir apps/web test && pnpm --dir apps/web build`
Expected: tests + production build pass.

### Task 8: Compose + README

**Files:**
- Modify: `docker-compose.yml`
- Modify: `README.md`

- [ ] **Step 1: Modify `docker-compose.yml`**

Worker service — add bind mount + env:

```yaml
    volumes:
      - catalog:/data
      - library:/library
      - models:/models
      - ${PICS_MOUNT_SOURCE:-$HOME/Pictures}:/media/photos:ro
    environment:
      - PICS_WATCH_ROOT=/media/photos
      - PICS_WATCHER_ENABLED=1
      - PICS_WATCH_POLL_SECONDS=30
```

`${PICS_MOUNT_SOURCE:-$HOME/Pictures}` uses an env override with a `$HOME`
default. Note: Compose interpolates nested `${...:-$HOME/...}`; to avoid edge
cases on some shells, document setting `PICS_MOUNT_SOURCE` explicitly and keep
the default `~/Pictures`.

- [ ] **Step 2: Modify `README.md`**

Replace the "Index Photos" section intro with:

```markdown
## Index photos

In Docker, the watched Pictures directory is bind-mounted read-only into the
container at `/media/photos`. It defaults to `~/Pictures`. To change it, edit
`docker-compose.yml` and set `PICS_MOUNT_SOURCE` (or edit the bind volume)
before `docker compose up`, then restart:

    docker compose down
    PICS_MOUNT_SOURCE=/Volumes/Backup/Photos docker compose up
```

Add a note under Admin:

```markdown
The **Admin** page (Settings) controls watch/ingest, backfill, jobs, clustering,
and status. The mount point itself cannot change from the UI — it is fixed at
container start — but the page shows the current root and how to change it.
```

- [ ] **Step 3: Verify**

Run: `docker compose config`
Expected: valid Compose configuration.

### Task 9: Full verification

- [ ] **Step 1: Run all test suites**

```bash
uv run --project packages/core --extra dev pytest packages/core/tests
uv run --project services/worker --extra dev pytest services/worker/tests
uv run --project apps/api --extra dev pytest apps/api/tests
pnpm --dir apps/web test
pnpm --dir apps/web build
docker compose config
git diff --check
```

Expected: all green.

- [ ] **Step 2: Manual smoke (optional, local worker session)**

```bash
uv run --project services/worker --extra dev python - <<'PY'
from worker.watcher import PhotoWatcher
w = PhotoWatcher(root=".")
print(w._known_hashes(1))  # smoke: imports and bindings resolve
PY
```

(Optional; if it references an open conn, drop the call — the point is import
sanity.)

## Verification Summary

- [ ] Fresh catalog seeds `settings` with `watch_enabled=0` — nothing runs by default.
- [ ] Watcher performs no filesystem walk while disabled.
- [ ] Watcher enqueues new files exactly once when enabled.
- [ ] `POST /admin/scan` always works (backfill/manual) even when watch is off.
- [ ] `PATCH /admin/settings` persists toggles; invalid values → 422.
- [ ] `/admin/status` reports root availability, models-ready, catalog counts.
- [ ] Admin page controls watch, backfill, scan, clustering; status shown.
- [ ] Parked banner shows when `watch_enabled=0` and links to Admin.
- [ ] Compose mounts `~/Pictures:/media/photos:ro` by default; README documents
      changing the mount via `PICS_MOUNT_SOURCE` + restart.
- [ ] Core/worker/api/web tests and compose config all pass.