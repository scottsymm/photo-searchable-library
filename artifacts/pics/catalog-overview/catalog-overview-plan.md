# Catalog Overview Implementation Plan

*Created: 2026-09-15*

**Goal:** Rebuild the Photos page as a holistic catalog overview — rollup asset funnel, per-source readiness and drill-down, context blocks — backed by a single `GET /catalog/overview` endpoint.

**Architecture:** All derivation is server-side in a new `apps/api/api/catalog.py` router, computed per source from existing tables and summed for the rollup. `mounted_folder` and `uploads` become real `sources` rows; `assets.source_id` is assigned automatically by `core/assets.py::upsert_asset` via a shared `classify_path` and backfilled by migration. The web page is a thin renderer.

**Tech Stack:** FastAPI + SQLite (pics-api/pics-core), pytest; Next.js 16 + React 19 + TypeScript, vitest (node env).

**Source:** `catalog-overview-design.md` (approved 2026-09-15, incl. wireframe `catalog-overview-design-diagram.svg`)

**Deviations from design (approved in planning):**

- Design §2.3 said the worker sets `assets.source_id`. Instead `upsert_asset` (core) classifies and sets it, covering worker, scan, and future importers from one place. `services/worker/worker/pipeline.py` is unchanged; the worker task is test-only.
- Design §8 mentioned vitest page-rendering tests. The web package has no React Testing Library/jsdom; UI logic is extracted into `apps/web/lib/funnel.ts` and unit-tested in node env, with manual browser verification for page states.

## File Map

| File | Action | Responsibility |
|---|---|---|
| `packages/core/core/sources.py` | Modify | `classify_path` + env constants |
| `packages/core/tests/test_sources.py` | Modify | classify_path tests |
| `packages/core/core/schema.py` | Modify | seed new sources, `created_at` column, backfill |
| `packages/core/tests/test_schema.py` | Create | migration/seed/backfill tests |
| `packages/core/core/assets.py` | Modify | upsert_asset sets `source_id` + `created_at` |
| `packages/core/tests/test_core.py` | Modify | upsert source/created_at tests |
| `services/worker/tests/test_worker.py` | Modify | import assigns source_id |
| `apps/api/api/sources.py` | Modify | ingest INSERT sets `created_at` |
| `apps/api/tests/test_sources.py` | Modify | ingest created_at test |
| `apps/api/api/admin.py` | Modify | wall-clock scan timestamp + public inventory wrappers |
| `apps/api/tests/test_admin.py` | Modify | scanned-at test |
| `apps/api/api/catalog.py` | Create | overview endpoint + all derivation |
| `apps/api/api/main.py` | Modify | register catalog router |
| `apps/api/tests/test_catalog.py` | Create | overview endpoint tests |
| `apps/web/types.ts` | Modify | overview types |
| `apps/web/lib/api.ts` | Modify | `catalogOverview()` + `thumbnailUrl()` |
| `apps/web/lib/funnel.ts` | Create | stage metadata + readiness/freshness labels |
| `apps/web/lib/funnel.test.ts` | Create | helper unit tests |
| `apps/web/app/globals.css` | Modify | funnel/drilldown/badge/context styles |
| `apps/web/app/photos/page.tsx` | Modify | rebuild page as thin renderer |

## Tasks

### Task 1: Add `classify_path` to core sources

**Files:**
- Modify: `packages/core/core/sources.py`
- Test: `packages/core/tests/test_sources.py`

- [x] **Step 1: Write the failing test**

Append to `packages/core/tests/test_sources.py`:

```python
def test_classify_path_maps_library_and_watch_root(tmp_path, monkeypatch):
    from core.sources import classify_path

    library = tmp_path / "library"
    watch = tmp_path / "watch"
    (library / "apple-photos").mkdir(parents=True)
    (library / "imports").mkdir(parents=True)
    watch.mkdir()
    monkeypatch.setattr("core.sources.LIBRARY", library)
    monkeypatch.setattr("core.sources.WATCH_ROOT", watch)

    assert classify_path(str(library / "apple-photos" / "a.heic")) == "apple_photos"
    assert classify_path(str(library / "imports" / "b.jpg")) == "uploads"
    assert classify_path(str(watch / "c.jpg")) == "mounted_folder"
    assert classify_path(str(tmp_path / "elsewhere.jpg")) is None
```

- [x] **Step 2: Verify it fails**

Run: `uv run --frozen --package pics-core --extra dev pytest tests/test_sources.py -x` (workdir `packages/core`)
Expected: FAIL — `ImportError`/`AttributeError` for `classify_path` (and `core.sources.LIBRARY` does not exist for monkeypatch).

- [x] **Step 3: Implement**

In `packages/core/core/sources.py`, replace the module docstring/import block:

```python
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
```

Keep all existing functions below unchanged.

- [x] **Step 4: Verify green**

Run: `uv run --frozen --package pics-core --extra dev pytest tests/test_sources.py -x` (workdir `packages/core`)
Expected: PASS — 5 tests.

- [x] **Step 5: Commit**

```bash
git add packages/core/core/sources.py packages/core/tests/test_sources.py
git commit -m "feat: add source path classification to core"
```

### Task 2: Schema — seed new sources, add `created_at`, backfill `source_id`

**Files:**
- Modify: `packages/core/core/schema.py`
- Test: `packages/core/tests/test_schema.py` (create)

- [x] **Step 1: Write the failing tests**

Create `packages/core/tests/test_schema.py`:

```python
from core.conn import connect
from core.schema import migrate


def test_migrate_seeds_all_sources(tmp_path):
    conn = connect(str(tmp_path / "catalog.db"))
    migrate(conn)
    kinds = {row["kind"] for row in conn.execute("SELECT kind FROM sources")}
    conn.close()
    assert {"apple_photos", "mounted_folder", "uploads"} <= kinds


def test_migrate_adds_created_at_column(tmp_path):
    conn = connect(str(tmp_path / "catalog.db"))
    migrate(conn)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(assets)")}
    conn.close()
    assert "created_at" in columns


def test_migrate_backfills_source_ids(tmp_path, monkeypatch):
    library = tmp_path / "library"
    watch = tmp_path / "watch"
    (library / "apple-photos").mkdir(parents=True)
    (library / "imports").mkdir(parents=True)
    watch.mkdir()
    monkeypatch.setenv("PICS_LIBRARY", str(library))
    monkeypatch.setenv("PICS_WATCH_ROOT", str(watch))

    conn = connect(str(tmp_path / "catalog.db"))
    migrate(conn)
    paths = {
        "apple": str((library / "apple-photos" / "a.heic").resolve()),
        "upload": str((library / "imports" / "b.jpg").resolve()),
        "mounted": str((watch / "c.jpg").resolve()),
        "other": "/somewhere/else/d.jpg",
    }
    conn.executemany(
        "INSERT INTO assets(path, sha256, size_bytes, mime) VALUES (?, ?, 1, 'image/jpeg')",
        [
            (paths["apple"], "a" * 64),
            (paths["upload"], "b" * 64),
            (paths["mounted"], "c" * 64),
            (paths["other"], "d" * 64),
        ],
    )
    conn.commit()

    migrate(conn)

    rows = {row["path"]: row["source_id"] for row in conn.execute("SELECT path, source_id FROM assets")}
    expected = {row["kind"]: row["id"] for row in conn.execute("SELECT id, kind FROM sources")}
    conn.close()
    assert rows[paths["apple"]] == expected["apple_photos"]
    assert rows[paths["upload"]] == expected["uploads"]
    assert rows[paths["mounted"]] == expected["mounted_folder"]
    assert rows[paths["other"]] is None
```

- [x] **Step 2: Verify they fail**

Run: `uv run --frozen --package pics-core --extra dev pytest tests/test_schema.py -x` (workdir `packages/core`)
Expected: FAIL — `test_migrate_seeds_all_sources` assertion (missing kinds) and `created_at` missing.

- [x] **Step 3: Implement**

In `packages/core/core/schema.py`:

1. Change imports:

```python
"""Catalog schema and migration entry point."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
```

2. In the `SCHEMA` string's `assets` table, add `created_at TEXT,` on its own line immediately after `taken_at TEXT,`.

3. In `migrate`, extend the column-alter tuple to include created_at:

```python
    for column, definition in (
        ("source_id", "INTEGER REFERENCES sources(id)"),
        ("source_asset_id", "TEXT"),
        ("original_filename", "TEXT"),
        ("created_at", "TEXT"),
    ):
```

4. Add helpers above `migrate`:

```python
def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _backfill_source_ids(conn: sqlite3.Connection) -> None:
    library = Path(os.environ.get("PICS_LIBRARY", "library")).resolve()
    watch_root = Path(os.environ.get("PICS_WATCH_ROOT", "/media/photos")).resolve()
    for prefix, kind in (
        (library / "apple-photos", "apple_photos"),
        (library / "imports", "uploads"),
        (watch_root, "mounted_folder"),
    ):
        pattern = f"{_escape_like(str(prefix))}{_escape_like(os.sep)}%"
        conn.execute(
            """UPDATE assets SET source_id = (SELECT id FROM sources WHERE kind = ?)
            WHERE source_id IS NULL AND path LIKE ? ESCAPE '\\'""",
            (kind, pattern),
        )
```

5. At the end of `migrate`, immediately after the existing `INSERT OR IGNORE INTO sources ... apple_photos` statement and before `conn.commit()`, add:

```python
    conn.execute(
        """INSERT OR IGNORE INTO sources(kind, display_name, status)
        VALUES ('mounted_folder', 'Mounted folder', 'not_connected')"""
    )
    conn.execute(
        """INSERT OR IGNORE INTO sources(kind, display_name, status)
        VALUES ('uploads', 'Uploads', 'not_connected')"""
    )
    _backfill_source_ids(conn)
```

- [x] **Step 4: Verify green**

Run: `uv run --frozen --package pics-core --extra dev pytest tests -x` (workdir `packages/core`)
Expected: PASS — all core tests (existing + 3 new).

- [x] **Step 5: Commit**

```bash
git add packages/core/core/schema.py packages/core/tests/test_schema.py
git commit -m "feat: seed folder/upload sources and backfill asset source ids"
```

### Task 3: `upsert_asset` assigns `source_id` and `created_at`

**Files:**
- Modify: `packages/core/core/assets.py`
- Test: `packages/core/tests/test_core.py`

- [x] **Step 1: Write the failing test**

Append to `packages/core/tests/test_core.py`:

```python
def test_upsert_asset_assigns_source_and_created_at(tmp_path, monkeypatch):
    watch = tmp_path / "watch"
    watch.mkdir()
    monkeypatch.setattr("core.sources.WATCH_ROOT", watch)
    conn = db()
    path = str((watch / "photo.jpg").resolve())
    asset_id = upsert_asset(
        conn,
        path=path,
        sha256="e" * 64,
        size_bytes=3,
        mime="image/jpeg",
        taken_at=None,
        gps_lat=None,
        gps_lon=None,
        place_city=None,
        place_country=None,
        thumbnail=None,
        extra={},
    )
    row = conn.execute("SELECT source_id, created_at FROM assets WHERE id = ?", (asset_id,)).fetchone()
    mounted_id = conn.execute("SELECT id FROM sources WHERE kind = 'mounted_folder'").fetchone()["id"]
    assert row["source_id"] == mounted_id
    assert row["created_at"] is not None

    upsert_asset(
        conn,
        path=path,
        sha256="f" * 64,
        size_bytes=4,
        mime="image/jpeg",
        taken_at=None,
        gps_lat=None,
        gps_lon=None,
        place_city=None,
        place_country=None,
        thumbnail=None,
        extra={},
    )
    again = conn.execute("SELECT created_at FROM assets WHERE id = ?", (asset_id,)).fetchone()
    assert again["created_at"] == row["created_at"]
```

- [x] **Step 2: Verify it fails**

Run: `uv run --frozen --package pics-core --extra dev pytest tests/test_core.py -x` (workdir `packages/core`)
Expected: FAIL — `source_id` is NULL (and `created_at` NULL on the in-memory DB created before Task 2's column existed — note: `db()` runs `migrate`, so the column exists; the failure is the NULL values).

- [x] **Step 3: Implement**

In `packages/core/core/assets.py`, add the import after the existing imports:

```python
from .sources import classify_path
```

Replace the body of `upsert_asset` (from `thumbnail_id = None` through the final `conn.execute(...)`) with:

```python
    thumbnail_id = None
    if thumbnail is not None:
        thumbnail_id = add_file(conn, f"{sha256}:thumbnail", "thumbnail", thumbnail)
    source_kind = classify_path(path)
    source_id = None
    if source_kind is not None:
        row = conn.execute("SELECT id FROM sources WHERE kind = ?", (source_kind,)).fetchone()
        source_id = None if row is None else int(row["id"])
    conn.execute(
        """INSERT INTO assets
        (path, sha256, size_bytes, mime, taken_at, gps_lat, gps_lon,
         place_city, place_country, thumbnail_id, extra, source_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
          sha256 = excluded.sha256, size_bytes = excluded.size_bytes,
          mime = excluded.mime, taken_at = excluded.taken_at,
          gps_lat = excluded.gps_lat, gps_lon = excluded.gps_lon,
          place_city = excluded.place_city, place_country = excluded.place_country,
          thumbnail_id = excluded.thumbnail_id, extra = excluded.extra,
          source_id = COALESCE(excluded.source_id, assets.source_id),
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
            source_id,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
```

Keep the trailing `conn.commit()`, row fetch, and return unchanged. Note: `created_at` is intentionally absent from the `ON CONFLICT` update so re-imports preserve the original import time.

- [x] **Step 4: Verify green**

Run: `uv run --frozen --package pics-core --extra dev pytest tests -x` (workdir `packages/core`)
Expected: PASS — all core tests.

- [x] **Step 5: Commit**

```bash
git add packages/core/core/assets.py packages/core/tests/test_core.py
git commit -m "feat: assign source id and import timestamp on asset upsert"
```

### Task 4: Worker test — import assigns `source_id`

**Files:**
- Test: `services/worker/tests/test_worker.py`

No worker code changes: `import_one` calls `upsert_asset`, which now classifies.

- [x] **Step 1: Write the test**

Append to `services/worker/tests/test_worker.py`:

```python
def test_import_assigns_mounted_source(tmp_path, monkeypatch):
    watch = tmp_path / "watch"
    watch.mkdir()
    image_path = watch / "sample.jpg"
    Image.new("RGB", (64, 64), (0, 200, 0)).save(image_path, "JPEG")
    db_path = tmp_path / "catalog.db"
    monkeypatch.setattr(config, "DB_PATH", str(db_path))
    monkeypatch.setattr(config, "LIBRARY_ROOT", str(tmp_path / "library"))
    os.makedirs(config.LIBRARY_ROOT)
    monkeypatch.setattr("core.sources.WATCH_ROOT", watch)
    monkeypatch.setattr("core.sources.LIBRARY", tmp_path / "library")

    conn = connect(str(db_path))
    migrate(conn)
    conn.close()

    asset_id = import_one(FakeClip(), NoFaces(), str(image_path))
    conn = connect(str(db_path))
    mounted_id = conn.execute("SELECT id FROM sources WHERE kind = 'mounted_folder'").fetchone()["id"]
    assert conn.execute("SELECT source_id FROM assets WHERE id = ?", (asset_id,)).fetchone()[0] == mounted_id
```

- [x] **Step 2: Verify green (behavior landed in Task 3)**

Run: `uv run --frozen --package pics-worker --extra dev pytest tests -x` (workdir `services/worker`)
Expected: PASS — 2 tests.

- [x] **Step 3: Commit**

```bash
git add services/worker/tests/test_worker.py
git commit -m "test: verify worker import assigns mounted source id"
```

### Task 5: Apple Photos ingest sets `created_at`

**Files:**
- Modify: `apps/api/api/sources.py`
- Test: `apps/api/tests/test_sources.py`

- [x] **Step 1: Write the failing test**

Append to `apps/api/tests/test_sources.py`:

```python
def test_apple_photos_ingest_sets_created_at(client, tmp_path, monkeypatch):
    monkeypatch.setattr("api.sources.LIBRARY", tmp_path)
    response = client.post(
        "/sources/apple-photos/assets",
        files={"file": ("IMG_0003.JPG", b"jpeg-bytes", "image/jpeg")},
        data={"source_asset_id": "ABC/L0/003", "original_filename": "IMG_0003.JPG"},
    )
    assert response.status_code == 200

    from api.deps import DB_PATH

    conn = connect(DB_PATH)
    row = conn.execute(
        "SELECT created_at FROM assets WHERE source_asset_id = 'ABC/L0/003'"
    ).fetchone()
    conn.close()
    assert row["created_at"] is not None
```

- [x] **Step 2: Verify it fails**

Run: `uv run --frozen --package pics-api --extra dev pytest tests/test_sources.py -x` (workdir `apps/api`)
Expected: FAIL — `created_at` is NULL.

- [x] **Step 3: Implement**

In `apps/api/api/sources.py`, in `ingest_apple_photos_asset`, replace the INSERT statement and its parameters:

```python
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
```

(`datetime`/`timezone` are already imported in this module.)

- [x] **Step 4: Verify green**

Run: `uv run --frozen --package pics-api --extra dev pytest tests/test_sources.py -x` (workdir `apps/api`)
Expected: PASS — 4 tests.

- [x] **Step 5: Commit**

```bash
git add apps/api/api/sources.py apps/api/tests/test_sources.py
git commit -m "feat: timestamp apple photos ingested assets"
```

### Task 6: Admin inventory — wall-clock scan time + public wrappers

**Files:**
- Modify: `apps/api/api/admin.py`
- Test: `apps/api/tests/test_admin.py`

- [x] **Step 1: Write the failing test**

Append to `apps/api/tests/test_admin.py`:

```python
def test_inventory_scanned_at_tracks_last_scan(client):
    assert api.admin.inventory_scanned_at() is None
    response = client.get("/admin/library")
    assert response.status_code == 200
    assert api.admin.inventory_scanned_at() is not None
```

- [x] **Step 2: Verify it fails**

Run: `uv run --frozen --package pics-api --extra dev pytest tests/test_admin.py -x` (workdir `apps/api`)
Expected: FAIL — `AttributeError: module 'api.admin' has no attribute 'inventory_scanned_at'`.

- [x] **Step 3: Implement**

In `apps/api/api/admin.py`:

1. Add to imports: `from datetime import datetime, timezone`
2. Add a global under `_inventory_cached_at: float | None = None`:

```python
_inventory_cached_wall_at: float | None = None
```

3. In `_clear_inventory_cache`, update the `global` statement to include `_inventory_cached_wall_at` and reset it to `None`.
4. In `_cached_library_inventory`, at both sites where `_inventory_cached_at = time.monotonic()` is assigned after a fresh scan (inside the non-blocking acquire and inside the final `with _inventory_lock:`), add on the next line:

```python
            _inventory_cached_wall_at = time.time()
```

(Also update the `global` statement in `_cached_library_inventory` to include `_inventory_cached_wall_at`.)

5. Add public wrappers after `_cached_library_inventory`:

```python
def cached_library_inventory() -> dict:
    """Public wrapper around the cached inventory scan."""
    return _cached_library_inventory()


def inventory_scanned_at() -> str | None:
    """ISO timestamp of the last completed inventory scan, if any."""
    if _inventory_cached_wall_at is None:
        return None
    return datetime.fromtimestamp(_inventory_cached_wall_at, timezone.utc).isoformat()
```

- [x] **Step 4: Verify green**

Run: `uv run --frozen --package pics-api --extra dev pytest tests/test_admin.py -x` (workdir `apps/api`)
Expected: PASS — all admin tests.

- [x] **Step 5: Commit**

```bash
git add apps/api/api/admin.py apps/api/tests/test_admin.py
git commit -m "feat: expose inventory scan timestamp for freshness labels"
```

### Task 7: Catalog overview endpoint — sources, stages, rollup, readiness

**Files:**
- Create: `apps/api/api/catalog.py`
- Modify: `apps/api/api/main.py`
- Test: `apps/api/tests/test_catalog.py` (create)

- [x] **Step 1: Write the failing tests**

Create `apps/api/tests/test_catalog.py`:

```python
import json

import pytest

import api.admin
from core.conn import connect


@pytest.fixture(autouse=True)
def _clear_inventory_cache():
    api.admin._clear_inventory_cache()


def _db(client):
    from api.deps import get_conn

    generator = client.app.dependency_overrides[get_conn]()
    return generator, next(generator)


def _source_id(conn, kind):
    return conn.execute("SELECT id FROM sources WHERE kind = ?", (kind,)).fetchone()["id"]


def _add_asset(conn, kind, path, sha, embedded=False, created_at=None, gps=False):
    conn.execute(
        """INSERT INTO assets(source_id, path, sha256, size_bytes, mime, created_at, gps_lat, gps_lon)
        VALUES (?, ?, ?, 1, 'image/jpeg', ?, ?, ?)""",
        (_source_id(conn, kind), path, sha, created_at, 1.0 if gps else None, 2.0 if gps else None),
    )
    asset_id = conn.execute("SELECT id FROM assets WHERE path = ?", (path,)).fetchone()["id"]
    if embedded:
        conn.execute(
            "INSERT INTO content_embeds(asset_id, model, model_version, embed) VALUES (?, 'm', 'v', ?)",
            (asset_id, b"x"),
        )
    conn.commit()
    return asset_id


def _get(client):
    response = client.get("/catalog/overview")
    assert response.status_code == 200
    return response.json()


def _source(data, kind):
    return next(s for s in data["sources"] if s["kind"] == kind)


def test_rollup_is_sum_of_per_source_stages(client):
    generator, conn = _db(client)
    try:
        conn.execute(
            "UPDATE sources SET status = 'connected', authorization_state = 'authorized', asset_count = 10 WHERE kind = 'apple_photos'"
        )
        _add_asset(conn, "apple_photos", "/library/apple-photos/1.heic", "a" * 64, embedded=True)
        _add_asset(conn, "apple_photos", "/library/apple-photos/2.heic", "b" * 64, embedded=True)
        _add_asset(conn, "apple_photos", "/library/apple-photos/3.heic", "c" * 64)
        _add_asset(conn, "mounted_folder", "/media/photos/x.jpg", "d" * 64, embedded=True)
    finally:
        generator.close()

    data = _get(client)
    apple = _source(data, "apple_photos")
    assert apple["stages"]["discovered"] == 10
    assert apple["stages"]["imported"] == 3
    assert apple["stages"]["ready_to_import"] == 7
    assert apple["stages"]["searchable"] == 2
    assert apple["stages"]["failed_or_blocked"] == 1  # stuck: imported, no embeds, no active job
    for key, value in data["funnel"].items():
        assert value == sum(s["stages"][key] for s in data["sources"])


def test_importing_estimate_reflects_active_sync(client):
    generator, conn = _db(client)
    try:
        conn.execute(
            "UPDATE sources SET status = 'connected', authorization_state = 'authorized', asset_count = 10 WHERE kind = 'apple_photos'"
        )
        conn.execute(
            "INSERT INTO source_syncs(source_id, limit_count, full_sync) VALUES (?, 5, 0)",
            (_source_id(conn, "apple_photos"),),
        )
        conn.commit()
    finally:
        generator.close()

    apple = _source(_get(client), "apple_photos")
    assert apple["stages"]["importing"] == 5
    assert apple["sync"]["status"] == "queued"


def test_importing_estimate_full_sync_uses_ready_count(client):
    generator, conn = _db(client)
    try:
        conn.execute(
            "UPDATE sources SET status = 'connected', authorization_state = 'authorized', asset_count = 10 WHERE kind = 'apple_photos'"
        )
        _add_asset(conn, "apple_photos", "/library/apple-photos/1.heic", "a" * 64, embedded=True)
        conn.execute(
            "INSERT INTO source_syncs(source_id, limit_count, full_sync) VALUES (?, 25, 1)",
            (_source_id(conn, "apple_photos"),),
        )
        conn.commit()
    finally:
        generator.close()

    apple = _source(_get(client), "apple_photos")
    assert apple["stages"]["importing"] == 9


def test_processing_counts_active_job_paths(client, tmp_path, monkeypatch):
    library = tmp_path / "library"
    (library / "apple-photos").mkdir(parents=True)
    monkeypatch.setattr("core.sources.LIBRARY", library)
    active_path = str((library / "apple-photos" / "active.heic").resolve())
    stuck_path = str((library / "apple-photos" / "stuck.heic").resolve())
    generator, conn = _db(client)
    try:
        conn.execute(
            "UPDATE sources SET status = 'connected', authorization_state = 'authorized', asset_count = 2 WHERE kind = 'apple_photos'"
        )
        _add_asset(conn, "apple_photos", active_path, "a" * 64)
        _add_asset(conn, "apple_photos", stuck_path, "b" * 64)
        conn.execute(
            "INSERT INTO jobs(kind, params) VALUES ('import', ?)",
            (json.dumps({"paths": [active_path]}),),
        )
        conn.commit()
    finally:
        generator.close()

    apple = _source(_get(client), "apple_photos")
    assert apple["stages"]["processing"] == 1
    assert apple["stages"]["failed_or_blocked"] == 1


def test_readiness_not_configured_by_default(client):
    apple = _source(_get(client), "apple_photos")
    assert apple["readiness"] == "not_configured"


def test_readiness_authorization_required(client):
    generator, conn = _db(client)
    try:
        conn.execute("UPDATE sources SET authorization_state = 'denied' WHERE kind = 'apple_photos'")
        conn.commit()
    finally:
        generator.close()

    apple = _source(_get(client), "apple_photos")
    assert apple["readiness"] == "authorization_required"


def test_readiness_failed_preserves_last_known_inventory(client):
    generator, conn = _db(client)
    try:
        conn.execute(
            "UPDATE sources SET status = 'connected', authorization_state = 'authorized', asset_count = 8105 WHERE kind = 'apple_photos'"
        )
        conn.execute(
            "INSERT INTO source_syncs(source_id, status, error) VALUES (?, 'error', 'bridge lease expired')",
            (_source_id(conn, "apple_photos"),),
        )
        conn.commit()
    finally:
        generator.close()

    apple = _source(_get(client), "apple_photos")
    assert apple["readiness"] == "failed"
    assert apple["readiness_detail"] == "bridge lease expired"
    assert apple["stages"]["discovered"] == 8105


def test_readiness_inventory_pending(client):
    generator, conn = _db(client)
    try:
        conn.execute(
            "UPDATE sources SET status = 'connected', authorization_state = 'authorized', asset_count = 0 WHERE kind = 'apple_photos'"
        )
        conn.commit()
    finally:
        generator.close()

    apple = _source(_get(client), "apple_photos")
    assert apple["readiness"] == "inventory_pending"


def test_mounted_readiness_failed_when_root_missing(client, tmp_path, monkeypatch):
    monkeypatch.setattr("api.admin.WATCH_ROOT", tmp_path / "missing")
    mounted = _source(_get(client), "mounted_folder")
    assert mounted["readiness"] == "failed"
    assert "not available" in mounted["readiness_detail"]


def test_mounted_discovered_uses_inventory_scan(client, tmp_path, monkeypatch):
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "b.jpg").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("nope")
    monkeypatch.setattr("api.admin.WATCH_ROOT", tmp_path)

    mounted = _source(_get(client), "mounted_folder")
    assert mounted["readiness"] == "connected"
    assert mounted["stages"]["discovered"] == 2
    assert mounted["reported_at"] is not None


def test_apple_reported_at_uses_last_sync_timestamp(client):
    generator, conn = _db(client)
    try:
        conn.execute(
            "UPDATE sources SET last_sync_at = '2026-09-15T14:59:16+00:00' WHERE kind = 'apple_photos'"
        )
        conn.commit()
    finally:
        generator.close()

    apple = _source(_get(client), "apple_photos")
    assert apple["reported_at"] == "2026-09-15T14:59:16+00:00"
```

- [x] **Step 2: Verify they fail**

Run: `uv run --frozen --package pics-api --extra dev pytest tests/test_catalog.py -x` (workdir `apps/api`)
Expected: FAIL — 404 on `/catalog/overview`.

- [x] **Step 3: Implement**

Create `apps/api/api/catalog.py`:

```python
"""Holistic catalog overview endpoint."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from core.sources import classify_path

from .admin import cached_library_inventory, inventory_scanned_at
from .deps import get_conn

router = APIRouter()

STAGE_KEYS = (
    "discovered",
    "ready_to_import",
    "importing",
    "imported",
    "processing",
    "searchable",
    "failed_or_blocked",
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
            stages["ready_to_import"]
            if latest_sync["full_sync"]
            else min(latest_sync["limit_count"], stages["ready_to_import"])
        )
    stages["processing"] = counts["processing"]
    stages["searchable"] = counts["searchable"]
    stages["failed_or_blocked"] = counts["stuck"] + (
        latest_sync["failed_count"]
        if latest_sync is not None and latest_sync["status"] in ("partial", "error")
        else 0
    )
    readiness, detail = _readiness(source, latest_sync)
    return {
        "kind": "apple_photos",
        "display_name": source["display_name"],
        "readiness": readiness,
        "readiness_detail": detail,
        "reported_at": source["last_sync_at"],
        "stages": stages,
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
    if available:
        readiness, detail = "connected", None
    else:
        readiness, detail = "failed", f"watch root is not available: {inventory['root']}"
    return {
        "kind": "mounted_folder",
        "display_name": source["display_name"],
        "readiness": readiness,
        "readiness_detail": detail,
        "reported_at": inventory_scanned_at(),
        "stages": stages,
        "sync": None,
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
        "kind": "uploads",
        "display_name": source["display_name"],
        "readiness": "connected",
        "readiness_detail": None,
        "reported_at": None,
        "stages": stages,
        "sync": None,
        "actions": {"can_sync": False},
    }


def _context(conn: sqlite3.Connection) -> dict:
    recent = conn.execute(
        """SELECT a.id, s.kind AS source_kind, a.original_filename,
          a.created_at AS imported_at, a.taken_at
        FROM assets a LEFT JOIN sources s ON s.id = a.source_id
        WHERE a.deleted = 0
        ORDER BY a.created_at IS NULL, a.created_at DESC, a.taken_at DESC
        LIMIT 6"""
    ).fetchall()
    faces_total = conn.execute("SELECT COUNT(*) FROM faces").fetchone()[0]
    assigned = conn.execute("SELECT COUNT(DISTINCT face_id) FROM person_faces").fetchone()[0]
    located = conn.execute(
        "SELECT COUNT(*) FROM assets WHERE deleted = 0 AND gps_lat IS NOT NULL"
    ).fetchone()[0]
    total_assets = conn.execute("SELECT COUNT(*) FROM assets WHERE deleted = 0").fetchone()[0]
    return {
        "recent_imports": [dict(row) for row in recent],
        "faces": {"total": faces_total, "assigned": assigned, "unassigned": faces_total - assigned},
        "places": {"located": located, "unlocated": total_assets - located},
    }


@router.get("/overview")
def catalog_overview(conn=Depends(get_conn)):
    inventory = cached_library_inventory()
    active = _job_paths(conn, ("queued", "working"))
    failed_jobs = _failed_job_counts(conn)
    rows = {row["kind"]: row for row in conn.execute("SELECT * FROM sources")}
    entries = [
        _apple_entry(conn, rows["apple_photos"], _latest_sync(conn, rows["apple_photos"]["id"]), active),
        _mounted_entry(conn, rows["mounted_folder"], inventory, active, failed_jobs),
        _uploads_entry(conn, rows["uploads"], active, failed_jobs),
    ]
    funnel = _empty_stages()
    for entry in entries:
        for key in STAGE_KEYS:
            funnel[key] += entry["stages"][key]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "funnel": funnel,
        "sources": entries,
        "context": _context(conn),
    }
```

In `apps/api/api/main.py`, change the import line to `from . import admin, catalog, jobs, persons, places, search, sources, uploads` and add after the admin router registration:

```python
app.include_router(catalog.router, prefix="/catalog", tags=["catalog"])
```

- [x] **Step 4: Verify green**

Run: `uv run --frozen --package pics-api --extra dev pytest tests -x` (workdir `apps/api`)
Expected: PASS — all API tests including 11 new catalog tests.

- [x] **Step 5: Commit**

```bash
git add apps/api/api/catalog.py apps/api/api/main.py apps/api/tests/test_catalog.py
git commit -m "feat: add catalog overview endpoint with per-source funnel stages"
```

### Task 8: Context blocks test — verify faces/places/recent imports

**Files:**
- Test: `apps/api/tests/test_catalog.py`

The `_context` implementation landed in Task 7; this task locks it in with a test.

- [x] **Step 1: Write the test**

Append to `apps/api/tests/test_catalog.py`:

```python
def test_context_blocks(client):
    generator, conn = _db(client)
    try:
        first = _add_asset(
            conn, "apple_photos", "/library/apple-photos/old.heic", "a" * 64,
            embedded=True, created_at="2026-09-14T10:00:00+00:00", gps=True,
        )
        second = _add_asset(
            conn, "uploads", "/library/imports/new.jpg", "b" * 64,
            embedded=True, created_at="2026-09-15T10:00:00+00:00",
        )
        conn.execute("INSERT INTO persons(name) VALUES ('Jane')")
        person_id = conn.execute("SELECT id FROM persons").fetchone()["id"]
        conn.execute("INSERT INTO faces(asset_id, bbox) VALUES (?, '[0,0,1,1]')", (first,))
        face_id = conn.execute("SELECT id FROM faces").fetchone()["id"]
        conn.execute("INSERT INTO faces(asset_id, bbox) VALUES (?, '[1,1,2,2]')", (second,))
        conn.execute(
            "INSERT INTO person_faces(person_id, face_id, source) VALUES (?, ?, 'manual')",
            (person_id, face_id),
        )
        conn.commit()
    finally:
        generator.close()

    data = _get(client)
    assert data["context"]["faces"] == {"total": 2, "assigned": 1, "unassigned": 1}
    assert data["context"]["places"] == {"located": 1, "unlocated": 1}
    recent = data["context"]["recent_imports"]
    assert recent[0]["id"] == second
    assert recent[0]["source_kind"] == "uploads"
    assert recent[1]["id"] == first
```

- [x] **Step 2: Verify green**

Run: `uv run --frozen --package pics-api --extra dev pytest tests/test_catalog.py -x` (workdir `apps/api`)
Expected: PASS — 12 tests.

- [x] **Step 3: Commit**

```bash
git add apps/api/tests/test_catalog.py
git commit -m "test: verify catalog overview context blocks"
```

### Task 9: Web — types, API fetcher, funnel helpers + tests

**Files:**
- Modify: `apps/web/types.ts`
- Modify: `apps/web/lib/api.ts`
- Create: `apps/web/lib/funnel.ts`
- Test: `apps/web/lib/funnel.test.ts` (create)

- [x] **Step 1: Write the failing test**

Create `apps/web/lib/funnel.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { freshnessLabel, readinessLabel, STAGES } from "./funnel";
import type { SourceOverview } from "../types";

function source(partial: Partial<SourceOverview>): SourceOverview {
  return {
    kind: "apple_photos",
    display_name: "Apple Photos",
    readiness: "connected",
    readiness_detail: null,
    reported_at: null,
    stages: {
      discovered: 0,
      ready_to_import: 0,
      importing: 0,
      imported: 0,
      processing: 0,
      searchable: 0,
      failed_or_blocked: 0,
    },
    sync: null,
    actions: { can_sync: false },
    ...partial,
  };
}

describe("STAGES", () => {
  it("covers every funnel key in order", () => {
    expect(STAGES.map((s) => s.key)).toEqual([
      "discovered",
      "ready_to_import",
      "importing",
      "imported",
      "processing",
      "searchable",
      "failed_or_blocked",
    ]);
  });

  it("marks importing and failed_or_blocked as approximate", () => {
    expect(STAGES.find((s) => s.key === "importing")?.approximate).toBe(true);
    expect(STAGES.find((s) => s.key === "failed_or_blocked")?.approximate).toBe(true);
    expect(STAGES.find((s) => s.key === "searchable")?.approximate).toBe(false);
  });
});

describe("readinessLabel", () => {
  it("labels every readiness state", () => {
    expect(readinessLabel("not_configured")).toBe("Not configured");
    expect(readinessLabel("authorization_required")).toBe("Authorization required");
    expect(readinessLabel("inventory_pending")).toBe("Inventory pending");
    expect(readinessLabel("connected")).toBe("Connected");
    expect(readinessLabel("failed")).toBe("Failed");
  });
});

describe("freshnessLabel", () => {
  const now = new Date("2026-09-15T15:00:00Z");

  it("treats uploads as live", () => {
    expect(freshnessLabel(source({ kind: "uploads" }), now)).toBe("live");
  });

  it("flags sources that never reported", () => {
    expect(freshnessLabel(source({}), now)).toBe("never synced");
  });

  it("relates mounted scans to now", () => {
    expect(
      freshnessLabel(source({ kind: "mounted_folder", reported_at: "2026-09-15T14:59:00Z" }), now),
    ).toBe("scanned 1 min ago");
    expect(
      freshnessLabel(source({ kind: "mounted_folder", reported_at: "2026-09-15T13:00:00Z" }), now),
    ).toBe("scanned 2 h ago");
  });

  it("dates bridge-reported totals", () => {
    const label = freshnessLabel(source({ reported_at: "2026-09-15T14:59:16Z" }), now);
    expect(label.startsWith("as of last sync ")).toBe(true);
  });
});
```

- [x] **Step 2: Verify it fails**

Run: `pnpm --filter web test` (workdir repo root)
Expected: FAIL — `./funnel` module not found (and `SourceOverview` type missing).

- [x] **Step 3: Implement**

Append to `apps/web/types.ts`:

```typescript
export type Readiness =
  | "not_configured"
  | "authorization_required"
  | "inventory_pending"
  | "connected"
  | "failed";

export interface FunnelStages {
  discovered: number;
  ready_to_import: number;
  importing: number;
  imported: number;
  processing: number;
  searchable: number;
  failed_or_blocked: number;
}

export interface SourceOverview {
  kind: string;
  display_name: string;
  readiness: Readiness;
  readiness_detail: string | null;
  reported_at: string | null;
  stages: FunnelStages;
  sync: SourceSync | null;
  actions: { can_sync: boolean };
}

export interface CatalogOverview {
  generated_at: string;
  funnel: FunnelStages;
  sources: SourceOverview[];
  context: {
    recent_imports: {
      id: number;
      source_kind: string | null;
      original_filename: string | null;
      imported_at: string | null;
      taken_at: string | null;
    }[];
    faces: { total: number; assigned: number; unassigned: number };
    places: { located: number; unlocated: number };
  };
}
```

In `apps/web/lib/api.ts`, add `CatalogOverview` to the type import on line 1, then append:

```typescript
export async function catalogOverview(): Promise<CatalogOverview> {
  const response = await fetch(apiUrl("/catalog/overview"), { cache: "no-store" });
  if (!response.ok) throw new Error("Catalog overview request failed");
  return response.json();
}

export function thumbnailUrl(assetId: number): string {
  return apiUrl(`/assets/${assetId}/thumbnail`);
}
```

Create `apps/web/lib/funnel.ts`:

```typescript
import type { FunnelStages, Readiness, SourceOverview } from "../types";

export interface StageMeta {
  key: keyof FunnelStages;
  label: string;
  approximate: boolean;
  tone: "default" | "goal" | "bad";
}

export const STAGES: StageMeta[] = [
  { key: "discovered", label: "Discovered", approximate: false, tone: "default" },
  { key: "ready_to_import", label: "Ready to import", approximate: false, tone: "default" },
  { key: "importing", label: "Importing", approximate: true, tone: "default" },
  { key: "imported", label: "Imported", approximate: false, tone: "default" },
  { key: "processing", label: "Processing", approximate: false, tone: "default" },
  { key: "searchable", label: "Searchable", approximate: false, tone: "goal" },
  { key: "failed_or_blocked", label: "Failed / Blocked", approximate: true, tone: "bad" },
];

const READINESS_LABELS: Record<Readiness, string> = {
  not_configured: "Not configured",
  authorization_required: "Authorization required",
  inventory_pending: "Inventory pending",
  connected: "Connected",
  failed: "Failed",
};

export function readinessLabel(state: Readiness): string {
  return READINESS_LABELS[state];
}

export function freshnessLabel(source: SourceOverview, now: Date = new Date()): string {
  if (source.kind === "uploads") return "live";
  if (!source.reported_at) return "never synced";
  const then = new Date(source.reported_at);
  if (source.kind !== "mounted_folder") {
    return `as of last sync ${then.toLocaleString()}`;
  }
  const minutes = Math.max(0, Math.round((now.getTime() - then.getTime()) / 60000));
  if (minutes < 1) return "scanned just now";
  if (minutes < 60) return `scanned ${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `scanned ${hours} h ago`;
  return `scanned ${Math.floor(hours / 24)} d ago`;
}
```

- [x] **Step 4: Verify green**

Run: `pnpm --filter web test` and `pnpm --filter web check` (workdir repo root)
Expected: PASS — vitest 2 files (search-parser + funnel); tsc no errors.

- [x] **Step 5: Commit**

```bash
git add apps/web/types.ts apps/web/lib/api.ts apps/web/lib/funnel.ts apps/web/lib/funnel.test.ts
git commit -m "feat: add catalog overview types and funnel helpers"
```

### Task 10: Web — funnel and context styles

**Files:**
- Modify: `apps/web/app/globals.css`

- [x] **Step 1: Append styles**

Append to `apps/web/app/globals.css`:

```css
.funnel { display: flex; flex-wrap: wrap; gap: 8px; margin: 4px 0 6px; }
.funnelStage { flex: 1 1 130px; display: grid; gap: 2px; border: 1px solid var(--line); border-radius: 14px; padding: 12px 14px; background: #fffdf899; text-align: left; color: var(--ink); }
button.funnelStage:hover { border-color: var(--accent); }
.funnelStage[aria-pressed="true"] { outline: 2px solid var(--accent); }
.stageLabel { font-size: .68rem; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
.stageValue { font-size: 1.6rem; font-weight: 700; }
.stageApprox { font-size: .7rem; font-style: italic; color: var(--muted); }
.funnelStageGoal { border-color: #2e7d4f; background: #eaf2ec; }
.funnelStageBad { border-color: var(--accent-dark); background: #faf0ec; }
.funnelStageBad .stageValue { color: var(--accent-dark); }
.funnelStageApprox { border-style: dashed; }
.funnelNote { margin: 0 0 14px; color: var(--muted); font-size: .8rem; font-style: italic; }
.drilldown { margin-bottom: 18px; border: 1px solid var(--line); border-radius: 14px; padding: 14px 18px; background: var(--panel); }
.barRow { display: grid; grid-template-columns: 140px 1fr auto; align-items: center; gap: 12px; padding: 6px 0; }
.barTrack { height: 12px; overflow: hidden; border-radius: 6px; background: var(--paper); }
.barFill { display: block; height: 100%; background: var(--accent-dark); }
.badge { display: inline-block; margin-left: 8px; border-radius: 999px; padding: 3px 12px; font-size: .72rem; font-weight: 700; vertical-align: middle; }
.badgeOk { color: white; background: #2e7d4f; }
.badgeWarn { color: white; background: var(--accent-dark); }
.badgeMuted { color: var(--ink); background: var(--line); }
.sourceFacts { display: grid; gap: 4px; margin-bottom: 10px; }
.thumbRow { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 12px; }
.contextValue { display: block; margin-bottom: 4px; font-size: 1.5rem; font-weight: 700; }
.proportionBar { display: flex; height: 12px; margin-top: 10px; overflow: hidden; border-radius: 6px; background: var(--paper); }
.proportionBar > span { display: block; height: 100%; }
```

- [x] **Step 2: Verify**

Run: `pnpm --filter web check` (workdir repo root)
Expected: PASS (CSS is not type-checked; this confirms nothing else broke). Visual check happens in Task 11/12.

- [x] **Step 3: Commit**

```bash
git add apps/web/app/globals.css
git commit -m "feat: add funnel and catalog context styles"
```

### Task 11: Web — rebuild the Photos page

**Files:**
- Modify: `apps/web/app/photos/page.tsx`

- [x] **Step 1: Replace the page**

Replace the entire contents of `apps/web/app/photos/page.tsx` with:

```tsx
"use client";

import { useEffect, useState } from "react";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { applePhotosSyncStatus, catalogOverview, requestApplePhotosSync, thumbnailUrl } from "../../lib/api";
import { STAGES, freshnessLabel, readinessLabel } from "../../lib/funnel";
import type { CatalogOverview, FunnelStages, SourceOverview, SourceSync } from "../../types";

function badgeClass(source: SourceOverview): string {
  if (source.readiness === "connected") return "badge badgeOk";
  if (source.readiness === "failed" || source.readiness === "authorization_required") return "badge badgeWarn";
  return "badge badgeMuted";
}

function SourceCard(props: {
  source: SourceOverview;
  sync: SourceSync | null;
  syncing: boolean;
  onSync: (full: boolean) => void;
  onRequestFullSync: () => void;
}) {
  const { source, sync, syncing, onSync, onRequestFullSync } = props;
  const syncActive = sync !== null && ["queued", "running"].includes(sync.status);
  const numbersHidden = ["not_configured", "authorization_required", "inventory_pending"].includes(source.readiness);
  return (
    <div className="card actionCard">
      <strong>
        {source.display_name} <span className={badgeClass(source)}>{readinessLabel(source.readiness)}</span>
      </strong>
      {numbersHidden ? (
        <span className="muted">{source.readiness_detail ?? "No inventory reported yet."}</span>
      ) : (
        <div className="sourceFacts">
          <span>{source.stages.discovered.toLocaleString()} discovered · {source.stages.searchable.toLocaleString()} searchable</span>
          <span className="muted">{freshnessLabel(source)}</span>
          {source.readiness === "failed" && source.readiness_detail && <span className="status">{source.readiness_detail}</span>}
        </div>
      )}
      {source.actions.can_sync && (
        <div className="syncControls">
          <button className="button" onClick={() => onSync(false)} disabled={syncing || syncActive}>
            {sync?.status === "queued" ? "Waiting for bridge…" : sync?.status === "running" ? "Sync in progress…" : syncing ? "Requesting sync…" : "Sync latest 25"}
          </button>
          <button className="button secondary" onClick={onRequestFullSync} disabled={syncing || syncActive}>Full sync</button>
          {sync?.status === "done" && <span className="muted">Last {sync.full_sync ? "full" : "bounded"} sync imported {sync.imported_count.toLocaleString()} assets.</span>}
          {sync?.status === "partial" && <span className="status">Partial sync: {sync.imported_count.toLocaleString()} imported, {sync.failed_count.toLocaleString()} failed.</span>}
        </div>
      )}
      {!source.actions.can_sync && <span className="muted cardAction">Read-only in v1</span>}
    </div>
  );
}

export default function PhotosPage() {
  const [overview, setOverview] = useState<CatalogOverview | null>(null);
  const [sync, setSync] = useState<SourceSync | null>(null);
  const [expanded, setExpanded] = useState<keyof FunnelStages | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState("");
  const [confirmFullSync, setConfirmFullSync] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    catalogOverview().then(setOverview).catch((reason) => {
      setError(reason instanceof Error ? reason.message : "Catalog overview unavailable");
    });
    applePhotosSyncStatus().then(setSync).catch(() => setSync(null));
  }, []);

  useEffect(() => {
    if (!sync || !["queued", "running"].includes(sync.status)) return;
    const timer = window.setInterval(() => {
      applePhotosSyncStatus().then(setSync).catch(() => undefined);
      catalogOverview().then(setOverview).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [sync]);

  async function startSync(fullSync = false) {
    setSyncing(true);
    setSyncError("");
    try {
      setSync(await requestApplePhotosSync(25, fullSync));
    } catch (reason) {
      setSyncError(reason instanceof Error ? reason.message : "Could not request Apple Photos sync");
    } finally {
      setSyncing(false);
    }
  }

  if (!overview) {
    return <main><div className="eyebrow">Catalog overview</div><h1>Photos</h1><p className="muted">{error || "Reading the catalog…"}</p></main>;
  }

  const sourceNames = Object.fromEntries(overview.sources.map((s) => [s.kind, s.display_name]));
  const faces = overview.context.faces;
  const places = overview.context.places;
  const assignedPct = faces.total > 0 ? (faces.assigned / faces.total) * 100 : 0;
  const locatedTotal = places.located + places.unlocated;
  const locatedPct = locatedTotal > 0 ? (places.located / locatedTotal) * 100 : 0;

  return <>
    <main>
      <div className="eyebrow">Catalog overview</div>
      <h1>Photos</h1>
      <p className="lead">The state of your catalog and its connections — where every asset is, and what needs attention.</p>

      <h2>Asset funnel</h2>
      <div className="funnel">
        {STAGES.map((stage) => {
          const value = overview.funnel[stage.key];
          const classes = ["funnelStage"];
          if (stage.tone === "goal") classes.push("funnelStageGoal");
          if (stage.tone === "bad" && value > 0) classes.push("funnelStageBad");
          if (stage.approximate) classes.push("funnelStageApprox");
          return (
            <button key={stage.key} className={classes.join(" ")} aria-pressed={expanded === stage.key} onClick={() => setExpanded(expanded === stage.key ? null : stage.key)}>
              <span className="stageLabel">{stage.label}</span>
              <span className="stageValue">{value.toLocaleString()}</span>
              {stage.approximate && <span className="stageApprox">approx</span>}
            </button>
          );
        })}
      </div>
      <p className="funnelNote">Discovered counts are as of each source&apos;s last report. Select a stage for its per-source breakdown.</p>
      {expanded && (
        <div className="drilldown">
          <strong>{STAGES.find((s) => s.key === expanded)?.label} — by source</strong>
          {overview.sources.map((source) => {
            const value = source.stages[expanded];
            const max = Math.max(1, ...overview.sources.map((s) => s.stages[expanded]));
            return (
              <div className="barRow" key={source.kind}>
                <span>{source.display_name}</span>
                <span className="barTrack"><span className="barFill" style={{ width: `${(value / max) * 100}%` }} /></span>
                <strong>{value.toLocaleString()}</strong>
              </div>
            );
          })}
        </div>
      )}

      <h2>Source connections</h2>
      {syncError && <p className="status">{syncError}</p>}
      <div className="cards">
        {overview.sources.map((source) => (
          <SourceCard
            key={source.kind}
            source={source}
            sync={source.kind === "apple_photos" ? sync : null}
            syncing={syncing}
            onSync={(full) => void startSync(full)}
            onRequestFullSync={() => setConfirmFullSync(true)}
          />
        ))}
      </div>

      <h2>Recent imports</h2>
      {overview.context.recent_imports.length === 0 ? (
        <p className="muted">No assets imported yet.</p>
      ) : (
        <div className="thumbRow">
          {overview.context.recent_imports.map((asset) => (
            <figure key={asset.id} className="photo">
              <img src={thumbnailUrl(asset.id)} alt={asset.original_filename ?? "Imported asset"} loading="lazy" />
              <figcaption>{sourceNames[asset.source_kind ?? ""] ?? "Pics"}</figcaption>
            </figure>
          ))}
        </div>
      )}

      <h2>Catalog context</h2>
      <div className="cards">
        <div className="card">
          <strong>Faces &amp; people</strong>
          <span className="contextValue">{faces.total.toLocaleString()} faces</span>
          <span className="muted">{faces.assigned.toLocaleString()} assigned to people · {faces.unassigned.toLocaleString()} unassigned</span>
          <div className="proportionBar"><span style={{ width: `${assignedPct}%`, background: "#2e7d4f" }} /></div>
        </div>
        <div className="card">
          <strong>Places</strong>
          <span className="contextValue">{places.located.toLocaleString()} located</span>
          <span className="muted">{places.unlocated.toLocaleString()} assets without location data</span>
          <div className="proportionBar"><span style={{ width: `${locatedPct}%`, background: "#4f6b8a" }} /></div>
        </div>
      </div>
    </main>
    <ConfirmDialog open={confirmFullSync} title="Run a full Apple Photos sync?" description="Pics will scan the entire Photos library and import only assets it does not already know about. The local bridge must be running." confirmLabel="Start full sync" onCancel={() => setConfirmFullSync(false)} onConfirm={() => { setConfirmFullSync(false); void startSync(true); }} />
  </>;
}
```

- [x] **Step 2: Verify**

Run: `pnpm --filter web check` and `pnpm --filter web test` (workdir repo root)
Expected: PASS — tsc no errors; vitest suites still green.

- [x] **Step 3: Commit**

```bash
git add apps/web/app/photos/page.tsx
git commit -m "feat: rebuild photos page as catalog overview"
```

### Task 12: Final verification

- [x] **Step 1: Full test suite**

Run: `pnpm test` (workdir repo root)
Expected: PASS — web, pics-api, pics-cli, pics-core, pics-worker all green.

- [x] **Step 2: App starts clean**

Run: `pnpm dev:docker:build` (or your usual dev stack) and confirm the API and web containers start without errors.

- [x] **Step 3: End-to-end manual check**

Open `http://localhost:3000/photos` and verify against the wireframe (`catalog-overview-design-diagram.svg`):

- Funnel shows 7 stages; numbers match expectations for your library (Discovered ≈ 8,571; Searchable ≈ 5,434; Failed/Blocked shows the previously invisible stuck count).
- Selecting a stage expands the per-source breakdown with proportional bars.
- Apple Photos card shows readiness, freshness ("as of last sync …"), last error, and working Sync latest 25 / Full sync buttons.
- Mounted folder card shows discovered/searchable and "scanned … ago"; Uploads card shows "live".
- Recent imports show thumbnails with source labels; Faces & people and Places cards show proportion bars.
- Start a bounded sync and confirm the page polls and the funnel updates.

## Verification Summary

- [ ] All tests pass: `pnpm test`
- [ ] App starts clean: `pnpm dev:docker:build`
- [ ] Feature works end-to-end: Task 12 Step 3 checklist
