# Photo Searchable Library — Implementation Plan

*Created: 2026-09-10*

**Goal:** Build an end-to-end self-hosted photo search library — ingest pipeline
(EXIF → thumbnail → CLIP embed → face), SQLite+sqlite-vec catalog, search API,
Next.js web UI, and `pics` CLI — runnable via Docker Compose on a single host.

**Architecture:** Monorepo (`pnpm` + `uv`). Python owns the model runtime:
`packages/core` (schema, catalog, job queue, KNN glue), `services/worker`
(long-lived ingest + embed HTTP sub-service), `apps/api` (FastAPI, thin), `apps/web`
(Next.js TS), `tools/cli` (`pics`). All Python imports `packages/core`; TS ↔ Python
communicate only via HTTP. SQLite is the single shared mutable state (WAL mode).

**Tech Stack:** Python 3.12 (uv), FastAPI, uvicorn, sqlite-vec, open_clip →
CLIP ViT-B/32 (transformers), insightface (face), ExifTool (exiftool binary),
Pillow, reverse_geocoder, pytest; Node 24, pnpm, Next.js (App Router), vitest.

**Source:** `artifacts/pics/photo-searchable-library/photo-searchable-library-design.md`

**Preview installation note:** worker + core install Debian apt packages
`exiftool ffmpeg` at container build (HEIC/RAW/MOV decode + metadata). In local
dev, `brew install exiftool ffmpeg` is required for integration tests on
non-JPEG fixtures; JPEG-only tests need none. HEIC support comes from the Python
wheel `pillow-heif` (no system libheif needed on this wheel path).

> **Library composition matters (this user's library):** a real photos count
> shows **2 333 HEIC, 978 JPEG/JPG, 358 MOV** — HEIC + video are the *majority*,
> not an edge case. Pillow alone won't open them; `pillow-heif` + ffmpeg are
> mandatory. (Also: most photos are **group shots with 2–4 faces**, so face
> clustering is genuinely required for the "who" search.)

## Spike Findings (validated 2026-09-10, in $TMPDIR/opencode/pics-spike)

A spike was run before finalizing this plan — twice. Empirically validated:

**Spike 2 (2026-09-10, real user photos + real Docker):**

7. **HEIC decode works out of the box with `pillow-heif`** — opened a real
   4284×5712 `.heic` and thumbnailed to JPEG in-memory. No system libheif
   needed on macOS wheels.
8. **MOV frame extraction works via ffmpeg** — `ffmpeg -i video.mov -frames:v 1
   -f image2pipe -vcodec mjpeg -` returns a ~72 KB JPEG (rc 0). ffmpeg must be
   installed (macOS: `brew install ffmpeg`).
9. **Real face detection works on this user's photos** — 2 faces found in a
   2.1 MB photo (287 ms, det scores 0.89/0.84, 512-dim embeddings). But most
   photos are **group shots with 2–4 faces**; naive pairwise cosine uncovered
   similarities as low as 0.00–0.31 even among intra-folder photos (because it
   compared different people / different faces in scenes). Conclusion: **a
   plain cosine threshold will NOT cluster people in this library; hierarchical
   clustering + human merge/split review is mandatory.** Face identity is the
   single highest-risk feature.
10. **The real ExifTool Python wrapper is `PyExifTool` 0.5.6** (`pip install
    PyExifTool`), NOT `exiftool-py`. The original plan's `exiftool-py` does not
    exist on PyPI and breaks the Docker build. Validated: `ExifToolHelper`
    + `common_args=["-n"]` returns GPS as numeric floats.
11. **Worker Docker image builds successfully** (python:3.12-slim + apt
    exiftool/ffmpeg + torch-CPU + transformers + insightface + PyExifTool +
    sqlite-vec + pillow-heif): all imports resolved. Image is **2.99 GB** —
    keep `HF_HOME`/model caches on the `models/` volume, expect large pulls.
12. **Library shape confirmed real**: 2 333 HEIC / 978 JPEG / 358 MOV; no RAW
    files present. Video+HEIC ingest is the main path, not an edge case.

(original spike below — retained for reference)

1. **sqlite-vec 0.1.9 query syntax is correct** — `CREATE VIRTUAL TABLE … USING
   vec0(embed float[512])`, insert with explicit `rowid = asset_id`,
   `WHERE embed MATCH ? ORDER BY distance LIMIT ?` returns `(rowid, distance)`
   ascending; `distance` is Euclidean.
2. **CLIP ViT-B/32 produces 512-dim embeddings** and runs ~10 ms/image CPU on
   Apple Silicon (batch 8) — 20k ≈ 4–6 min. This replaces the vaguer design
   estimate. **BUT**: `transformers>=5` `get_image_features()`/`get_text_features()`
   return a `BaseModelOutputWithPooling`, so the code **must use `.pooler_output`**,
   not the raw return.
3. **`reverse_geocoder` is fully offline** (it ships its own gazetteer; no network
   on first run — validated import in 4.7s). Correct API:
   `reverse_geocoder.search([(lat, lon)], mode=1)` → `[{'name':…, 'cc':…}]`
   (returns a *list of dicts*; does not accept a bare tuple).
4. **`exiftool` is NOT installed by default on macOS** — it must be an explicit
   dependency (`brew install exiftool`, or apt in Dockerfiles). Contained in the
   preview note above.
5. **GPS hemisphere gotcha** — with `exiftool -n -json` (numeric mode),
   `GPSLatitude`/`GPSLongitude` come back as unsigned floats; the sign lives in
   `GPSLatitudeRef`/`GPSLongitudeRef` (`S`/`W` → negate). The original
   `exif.py` will put London at `+0.12` unless the ref is applied. Not PAPIcodop
   `-n` must be used (`ExifToolHelper(common_args=["-n"])`) or degree strings
   won't parse.
6. **insightface buffalo_l** works on CPU-only (`CPUExecutionProvider`), ~87 ms
   per 640×480 frame for detection. First run downloads ~280 MB weights from
   **GitHub releases** (deepinsight/insightface model zoo), so the worker needs
   network on first start; afterwards the models dir is a cache.

**Still unverified (follow-up spike needed):** real HEIC/RAW/video decode, real
face detection on actual photos (Needsample), and Docker build of the torch/
insightface images.

## File Map

| File | Action | Responsibility |
|---|---|---|
| `.gitignore` | Create | Ignore venvs, node_modules, catalog.db, library/, models/ |
| `pnpm-workspace.yaml` | Create | Declare pnpm workspace (apps/web) |
| `package.json` (root) | Create | Root scripts + devDeps |
| `docker-compose.yml` | Create | web/api/worker + volumes |
| `README.md` | Create | Run instructions |
| `packages/core/pyproject.toml` | Create | core package metadata + deps |
| `packages/core/core/__init__.py` | Create | Exports |
| `packages/core/core/schema.py` | Create | Schema v1 DDL + migrate() |
| `packages/core/core/conn.py` | Create | sqlite connection (WAL, busy_timeout, vec load) |
| `packages/core/core/jobs.py` | Create | Job table helpers (push/claim/complete) |
| `packages/core/core/assets.py` | Create | Upsert asset, files, dedupe |
| `packages/core/core/embeds.py` | Create | vec0 mirrors + KNN queries |
| `packages/core/core/geo.py` | Create | reverse_geocoder wrapper |
| `packages/core/tests/test_schema.py` | Create | Schema + vec tests |
| `packages/core/tests/test_jobs.py` | Create | Job queue tests |
| `services/worker/pyproject.toml` | Create | Worker metadata + deps |
| `services/worker/worker/__init__.py` | Create | Exports |
| `services/worker/worker/config.py` | Create | Settings (paths, model names) |
| `services/worker/worker/models.py` | Create | CLIP embed image/text |
| `services/worker/worker/exif.py` | Create | ExifTool JSON extraction |
| `services/worker/worker/thumbnail.py` | Create | Pillow/ffmpeg thumbnail |
| `services/worker/worker/faces.py` | Create | Insightface detect + embed |
| `services/worker/worker/pipeline.py` | Create | Process one asset → catalog rows |
| `services/worker/worker/run.py` | Create | Job drain loop |
| `services/worker/worker/embed_api.py` | Create | `/v1/embed-text`, `/v1/status` |
| `services/worker/tests/test_pipeline.py` | Create | Integration w/ JPEG fixture |
| `services/worker/Dockerfile` | Create | Worker container |
| `apps/api/pyproject.toml` | Create | API metadata + deps |
| `apps/api/api/__init__.py` | Create | Exports |
| `apps/api/api/main.py` | Create | FastAPI app + router mount |
| `apps/api/api/deps.py` | Create | catalog dep, model-embed client |
| `apps/api/api/search.py` | Create | Search endpoint |
| `apps/api/api/uploads.py` | Create | Upload endpoint |
| `apps/api/api/jobs.py` | Create | Job list/get |
| `apps/api/api/persons.py` | Create | Persons list/rename/merge/split |
| `apps/api/api/places.py` | Create | Place buckets |
| `apps/api/tests/conftest.py` | Create | fixture catalog + TestClient |
| `apps/api/tests/test_api.py` | Create | Endpoint tests |
| `apps/api/Dockerfile` | Create | API container |
| `tools/cli/pyproject.toml` | Create | CLI metadata |
| `tools/cli/cli/__main__.py` | Create | argparse entry |
| `tools/cli/cli/commands.py` | Create | scan/query/strip-exif/reindex |
| `tools/cli/tests/test_commands.py` | Create | CLI tests |
| `apps/web/package.json` | Create | Next deps |
| `apps/web/next.config.ts` | Create | Config |
| `apps/web/tsconfig.json` | Create | TS config |
| `apps/web/types.ts` | Create | API types |
| `apps/web/lib/api.ts` | Create | API client |
| `apps/web/lib/search-parser.ts` | Create | Parse filters + text |
| `apps/web/lib/search-parser.test.ts` | Create | vitest |
| `apps/web/app/layout.tsx` | Create | Root layout |
| `apps/web/app/page.tsx` | Create | Search + grid page |
| `apps/web/components/SearchBar.tsx` | Create | Query + filter UI |
| `apps/web/components/Grid.tsx` | Create | Thumbnail grid |
| `apps/web/app/people/page.tsx` | Create | People review |
| `apps/web/app/places/page.tsx` | Create | Place buckets |
| `apps/web/app/settings/page.tsx` | Create | Scan/reindex |
| `apps/web/pnpm-workspace.yaml` | Create | Web workspace root |

## Tasks

### Task 1: Root scaffolding + git

**Files:**
- Create: `.gitignore`
- Create: `pnpm-workspace.yaml`
- Create: `package.json`
- Create: `README.md`

- [ ] **Step 1: Init git**

```bash
cd /Users/jobofish/code/pics && git init
```

- [ ] **Step 2: Create `.gitignore`**

```gitignore
# Python
__pycache__/
*.pyc
.venv/
dist/
*.egg-info/
.pytest_cache/

# Node
node_modules/
.next/
out/
coverage/

# Runtime data
catalog.db*
library/
models/
!packages/core/tests/data/.gitkeep
!services/worker/tests/data/.gitkeep

# Editor
.DS_Store
```

- [ ] **Step 3: Create `pnpm-workspace.yaml`**

```yaml
packages:
  - "apps/web"
```

- [ ] **Step 4: Create `package.json`**

```json
{
  "name": "pics",
  "private": true,
  "packageManager": "pnpm@10.0.0",
  "scripts": {
    "web": "pnpm -F web dev",
    "test:web": "pnpm -F web test",
    "build:web": "pnpm -F web build"
  }
}
```

- [ ] **Step 5: Create `README.md`**

```markdown
# Pics — searchable photo library

Self-hosted photo search: CLIP embeddings + faces + EXIF in a SQLite catalog.

## Quickstart (Compose)

    docker compose up --build
    # web  http://localhost:3000   api http://localhost:8000

## Local dev

    # Python 3.12 + uv
    uv sync --project packages/core
    uv run --project services/worker
    # web
    pnpm install
    pnpm web
```

- [ ] **Step 6: Verify**

Run: `git status` — untracked root files present.
Run: `pnpm --version` — prints `10.0.0` or newer.

- [ ] **Step 7: Commit**

```bash
git add . && git commit -m "chore: scaffold monorepo root"
```

### Task 2: `packages/core` package + connection

**Files:**
- Create: `packages/core/pyproject.toml`
- Create: `packages/core/core/__init__.py`
- Create: `packages/core/core/conn.py`

- [ ] **Step 1: Create `packages/core/pyproject.toml`**

```toml
[project]
name = "core"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "sqlite-vec>=0.1.6",
]

[tool.pytest.ini_options]
testpaths = ["tests"]

[project.optional-dependencies]
dev = ["pytest"]
```

- [ ] **Step 2: Create `packages/core/core/__init__.py`**

```python
"""Core catalog library for pics."""
```

- [ ] **Step 3: Create `packages/core/core/conn.py`**

```python
"""SQLite connection wrapper: WAL, busy_timeout, sqlite-vec load."""
from __future__ import annotations

import sqlite3
import sqlite_vec

DB_PATH = "catalog.db"


def connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def check_vec(conn: sqlite3.Connection) -> bool:
    """True if the sqlite-vec functions are available."""
    row = conn.execute("SELECT vec_version() AS v").fetchone()
    return row is not None and bool(row["v"])
```

- [ ] **Step 4: Verify**

```bash
cd /Users/jobofish/code/pics/packages/core
uv run python -c "import sys; sys.path.insert(0,'.'); from core.conn import connect, check_vec; c=connect(':memory:')[0] if False else None"
```

Expected: no import error (sqlite_vec loads).

- [ ] **Step 5: Commit**

```bash
git add packages/core && git commit -m "feat: add core package skeleton (conn, vec load)"
```

### Task 3: Schema DDL + migrate

**Files:**
- Create: `packages/core/core/schema.py`
- Test: `packages/core/tests/test_schema.py`

- [ ] **Step 1: Create `packages/core/core/schema.py`**

```python
"""Schema v1 DDL and migrate helper."""
from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
  id INTEGER PRIMARY KEY,
  path TEXT NOT NULL UNIQUE,
  sha256 TEXT NOT NULL,
  size_bytes INTEGER,
  mime TEXT,
  taken_at TEXT,
  gps_lat REAL,
  gps_lon REAL,
  place_city TEXT,
  place_country TEXT,
  thumbnail_id INTEGER
);
CREATE TABLE IF NOT EXISTS assets_aux (
  asset_id INTEGER PRIMARY KEY,
  stripped INTEGER NOT NULL DEFAULT 0,
  deleted INTEGER NOT NULL DEFAULT 0,
  skip INTEGER NOT NULL DEFAULT 0,
  extra TEXT
);
CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY,
  sha256 TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  bytes BLOB,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS faces (
  id INTEGER PRIMARY KEY,
  asset_id INTEGER NOT NULL,
  crop_path TEXT,
  bbox TEXT,
  cluster_id INTEGER
);
CREATE TABLE IF NOT EXISTS persons (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL DEFAULT '',
  prototype_face_id INTEGER,
  status TEXT NOT NULL DEFAULT 'new'
);
CREATE TABLE IF NOT EXISTS content_embeds (
  asset_id INTEGER PRIMARY KEY,
  model TEXT NOT NULL,
  model_version TEXT NOT NULL,
  embed BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS face_embeds (
  face_id INTEGER PRIMARY KEY,
  model TEXT NOT NULL,
  embed BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS tags (
  asset_id INTEGER NOT NULL,
  tag TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'clip',
  PRIMARY KEY (asset_id, tag)
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  progress REAL,
  error TEXT,
  params TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS vec0_content USING vec0(
  content_embed float[512]
);
CREATE VIRTUAL TABLE IF NOT EXISTS vec0_face USING vec0(
  face_embed float[512]
);
"""


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
```

Note: `vec0_content.content_embed` and `vec0_face.face_embed` are mirrors of
`content_embeds.embed` / `face_embeds.embed`, keyed by `rowid = asset_id` /
`rowid = face_id` (see Task 6).

- [ ] **Step 2: Create `packages/core/tests/test_schema.py`**

```python
import sqlite3

from core.conn import connect, check_vec
from core.schema import migrate


def test_schema_creates_tables():
    conn = connect(":memory:")
    migrate(conn)
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert {"assets", "files", "faces", "persons", "content_embeds",
            "face_embeds", "tags", "jobs", "vec0_content", "vec0_face"} <= tables


def test_vec_loads():
    conn = connect(":memory:")
    migrate(conn)
    assert check_vec(conn)
```

- [ ] **Step 3: Run tests (red)**

```bash
uv run --project packages/core pytest packages/core/tests/test_schema.py
```

Expected: error `ModuleNotFoundError: core` or ``test fails.

- [ ] **Step 4: Install package editable and re-run (green)**

```bash
cd packages/core && uv pip install -e .
cd /Users/jobofish/code/pics && grep -r "source" /dev/null; uv run --project packages/core pytest packages/core/tests/test_schema.py
```

Expected: PASS — 2 tests passing.

- [ ] **Step 5: Commit**

```bash
git add packages/core && git commit -m "feat: add catalog schema + vec tables"
```

### Task 4: `core.jobs` — queue helpers

**Files:**
- Create: `packages/core/core/jobs.py`
- Test: `packages/core/tests/test_jobs.py`

- [ ] **Step 1: Create `packages/core/core/jobs.py`**

```python
"""SQLite-backed job queue."""
from __future__ import annotations

import sqlite3
import time


def push(conn: sqlite3.Connection, kind: str, params: dict | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO jobs (kind, params) VALUES (?, ?)",
        (kind, None if params is None else __import__("json").dumps(params)),
    )
    conn.commit()
    return cur.lastrowid


def claim(conn: sqlite3.Connection,
          kinds: tuple[str, ...] = ("scan", "import", "reindex"),
          ) -> sqlite3.Row | None:
    """Claim one queued job, marking it working. Returns None if none."""
    row = conn.execute(
        "SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE jobs SET status='working', updated_at=datetime('now')"
                 " WHERE id=?", (row["id"],))
    conn.commit()
    return row


def set_progress(conn: sqlite3.Connection, job_id: int, progress: float) -> None:
    conn.execute("UPDATE jobs SET progress=?, updated_at=datetime('now')"
                 " WHERE id=?", (progress, job_id))
    conn.commit()


def complete(conn: sqlite3.Connection, job_id: int) -> None:
    conn.execute("UPDATE jobs SET status='done', progress=1.0,"
                 " updated_at=datetime('now') WHERE id=?", (job_id,))
    conn.commit()


def fail(conn: sqlite3.Connection, job_id: int, error: str) -> None:
    conn.execute("UPDATE jobs SET status='error', error=?,"
                 " updated_at=datetime('now') WHERE id=?", (error, job_id))
    conn.commit()


def pending(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM jobs"
                        " WHERE status IN ('queued','working')").fetchone()["n"]
```

- [ ] **Step 2: Create `packages/core/tests/test_jobs.py`**

```python
import sqlite3
from core.conn import connect
from core.schema import migrate
from core import jobs


def _db() -> sqlite3.Connection:
    conn = connect(":memory:")
    migrate(conn)
    return conn


def test_push_claim_complete():
    conn = _db()
    jid = jobs.push(conn, "import")
    assert jid == 1
    row = jobs.claim(conn)
    assert row is not None and row["status"] == "working"
    jobs.set_progress(conn, jid, 0.5)
    jobs.complete(conn, jid)
    assert jobs.pending(conn) == 0


def test_claim_none_when_empty():
    conn = _db()
    assert jobs.claim(conn) is None


def test_fail():
    conn = _db()
    jid = jobs.push(conn, "scan")
    jobs.claim(conn)
    jobs.fail(conn, jid, "boom")
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    assert row["status"] == "error" and row["error"] == "boom"
```

- [ ] **Step 3: Verify**

Run: `uv run --project packages/core pytest packages/core/tests/test_jobs.py`
Expected: PASS — 3 tests passing.

- [ ] **Step 4: Commit**

```bash
git add packages/core && git commit -m "feat: add job queue helpers"
```

### Task 5: `assets.py` + `geo.py`

**Files:**
- Create: `packages/core/core/assets.py`
- Create: `packages/core/core/geo.py`

- [ ] **Step 1: Create `packages/core/core/assets.py`**

```python
"""Asset + files upsert logic."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def add_file(conn: sqlite3.Connection, sha256: str, kind: str,
             bytes_: bytes | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO files (sha256, kind, bytes, created_at)"
        " VALUES (?, ?, ?, ?) ON CONFLICT(sha256) DO NOTHING",
        (sha256, kind, bytes_, datetime.utcnow().isoformat()),
    )
    conn.commit()
    return conn.execute(
        "SELECT id FROM files WHERE sha256=?", (sha256,)
    ).fetchone()["id"]


def upsert_asset(conn: sqlite3.Connection, *, path: str, sha256: str,
                 size_bytes: int, mime: str, taken_at: str | None,
                 gps_lat: float | None, gps_lon: float | None,
                 place_city: str | None, place_country: str | None,
                 thumbnail: bytes | None, extra: dict | None) -> int:
    thumb_id = add_file(conn, sha256 + ":thumb", "thumbnail", thumbnail) if thumbnail else None
    cur = conn.execute(
        """INSERT INTO assets
           (path, sha256, size_bytes, mime, taken_at, gps_lat, gps_lon,
            place_city, place_country, thumbnail_id)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(path) DO UPDATE SET
             sha256=excluded.sha256, size_bytes=excluded.size_bytes,
             mime=excluded.mime, taken_at=excluded.taken_at,
             gps_lat=excluded.gps_lat, gps_lon=excluded.gps_lon,
             place_city=excluded.place_city, place_country=excluded.place_country,
             thumbnail_id=excluded.thumbnail_id""",
        (path, sha256, size_bytes, mime, taken_at, gps_lat, gps_lon,
         place_city, place_country, thumb_id),
    )
    conn.commit()
    asset_id = conn.execute("SELECT id FROM assets WHERE path=?",
                            (path,)).fetchone()["id"]
    if extra is not None:
        import json
        conn.execute(
            """INSERT INTO assets_aux (asset_id, extra) VALUES (?, ?)
               ON CONFLICT(asset_id) DO UPDATE SET extra=excluded.extra""",
            (asset_id, json.dumps(extra)),
        )
    conn.commit()
    return asset_id
```

- [ ] **Step 2: Create `packages/core/core/geo.py`**

```python
"""Reverse geocoding wrapper."""
from __future__ import annotations

import reverse_geocoder


def reverse(lat: float, lon: float) -> tuple[str | None, str | None]:
    """Return (city, country) using the offline GeoNames gazetteer."""
    try:
        # NOTE: API takes a LIST of (lat, lon) pairs and returns a list.
        r = reverse_geocoder.search([(lat, lon)], mode=1)[0]
        return r["name"], r["cc"]
    except Exception:
        return None, None
```

Note: `reverse_geocoder` (MIT) ships its own Gazetteer data *in the installed
package* — no network is required on first use (validated in spike; import
took ~5s). City/country granularity only.

- [ ] **Step 3: Verify**

```bash
cd /Users/jobofish/code/pics/packages/core
uv run python -c "import sys; sys.path.insert(0,'.'); from core.assets import sha256_file, add_file, upsert_asset; from core.conn import connect; from core.schema import migrate; c=connect(':memory:'); migrate(c); c.close(); print('ok')"
```

Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add packages/core && git commit -m "feat: add asset upsert + reverse geocode"
```

### Task 6: `embeds.py` — vec0 mantling + KNN

**Files:**
- Create: `packages/core/core/embeds.py`

- [ ] **Step 1: Create `packages/core/core/embeds.py`**

```python
"""Embedding storage + sqlite-vec KNN queries."""
from __future__ import annotations

import array
import sqlite3


def to_blob(vec_f32: list[float]) -> bytes:
    return array.array("f", vec_f32).tobytes()


def from_blob(b: bytes) -> list[float]:
    return list(array.array("f", b))


def add_content(conn: sqlite3.Connection, asset_id: int, model: str,
                model_version: str, vec: list[float]) -> None:
    conn.execute(
        """INSERT INTO content_embeds (asset_id, model, model_version, embed)
           VALUES (?,?,?,?)
           ON CONFLICT(asset_id) DO UPDATE SET model=excluded.model,
             model_version=excluded.model_version,
             embed=excluded.embed""",
        (asset_id, model, model_version, to_blob(vec)),
    )
    # mirror into vec0 virtual table, keyed rowid = asset_id
    conn.execute("DELETE FROM vec0_content WHERE rowid = ?", (asset_id,))
    conn.execute("INSERT INTO vec0_content(rowid, content_embed) VALUES (?, ?)",
                 (asset_id, to_blob(vec)))
    conn.commit()


def add_face(conn: sqlite3.Connection, face_id: int, model: str,
             vec: list[float]) -> None:
    conn.execute(
        "INSERT INTO face_embeds (face_id, model, embed) VALUES (?,?,?)"
        " ON CONFLICT(face_id) DO UPDATE SET model=excluded.model, embed=excluded.embed",
        (face_id, model, to_blob(vec)),
    )
    conn.execute("DELETE FROM vec0_face WHERE rowid = ?", (face_id,))
    conn.execute("INSERT INTO vec0_face(rowid, face_embed) VALUES (?, ?)",
                 (face_id, to_blob(vec)))
    conn.commit()


def cos_knn(conn: sqlite3.Connection, vec: list[float],
            limit: int = 200) -> list[tuple[int, float]]:
    """Exact KNN over content embeddings.
    Returns (asset_id, cosine_distance) sorted ascending distance."""
    q = to_blob(vec)
    rows = conn.execute(
        """SELECT rowid, distance FROM vec0_content
           WHERE content_embed MATCH ?
           ORDER BY distance LIMIT ?""",
        (q, limit),
    ).fetchall()
    return [(r["rowid"], r["distance"]) for r in rows]


def face_knn(conn: sqlite3.Connection, vec: list[float],
             limit: int = 50) -> list[tuple[int, float]]:
    q = to_blob(vec)
    rows = conn.execute(
        """SELECT rowid, distance FROM vec0_face
           WHERE face_embed MATCH ? ORDER BY distance LIMIT ?""",
        (q, limit),
    ).fetchall()
    return [(r["rowid"], r["distance"]) for r in rows]
```

- [ ] **Step 2: Verify (add a quick test in `tests/test_schema.py`)**

Append to `packages/core/tests/test_schema.py`:

```python
from core.embeds import add_content, cos_knn


def test_knn_roundtrip():
    conn = connect(":memory:")
    migrate(conn)
    add_content(conn, 1, "m", "v", [1.0] * 512)
    add_content(conn, 2, "m", "v", [-1.0] * 512)
    res = cos_knn(conn, [1.0] * 512, limit=2)
    assert res[0][0] == 1 and res[0][1] < res[1][1]
```

- [ ] **Step 3: Verify**

Run: `uv run --project packages/core pytest packages/core/tests/test_schema.py`
Expected: PASS — 3 tests passing.

- [ ] **Step 4: Commit**

```bash
git add packages/core && git commit -m "feat: add sqlite-vec embeds + KNN"
```

### Task 7: Worker — config + models (CLIP)

**Files:**
- Create: `services/worker/pyproject.toml`
- Create: `services/worker/worker/__init__.py`
- Create: `services/worker/worker/config.py`
- Create: `services/worker/worker/models.py`

- [ ] **Step 1: Create `services/worker/pyproject.toml`**

```toml
[project]
name = "worker"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "core",  # local path below
  "uvicorn>=0.30",
  "fastapi>=0.115",
  "torch>=2.0",
  "transformers>=4.40",
  "pillow>=10",
  "PyExifTool>=0.5.6",      # correct wrapper package (NOT exiftool-py, which is absent on PyPI)
  "insightface>=0.7.3",
  "onnxruntime>=1.17",
  "numpy",
]
[tool.uv.sources]
core = { path = "../../packages/core" }
```

- [ ] **Step 2: Create `services/worker/worker/__init__.py`**

```python
"""Worker — long-lived ingest + embedding service."""
```

- [ ] **Step 3: Create `services/worker/worker/config.py`**

```python
"""Worker settings."""
from __future__ import annotations

import os

DB_PATH = os.environ.get("PICS_DB", "catalog.db")
LIBRARY_ROOT = os.environ.get("PICS_LIBRARY", "library")
MODEL_NAME = os.environ.get("PICS_MODEL", "openai/clip-vit-base-patch32")
EMBED_MODEL_VERSION = "0.1.0"
FACE_MODEL = os.environ.get("PICS_FACE_MODEL", "buffalo_l")
HEALTH_PORT = int(os.environ.get("PICS_EMBED_PORT", "9090"))
```

- [ ] **Step 4: Create `services/worker/worker/models.py`**

```python
"""CLIP model wrapper adding no torch to import surfaces."""
from __future__ import annotations

import numpy as np
import torch
from PIL import Image
from transformers import CLIPModel, CLIPProcessor


class CLIP:
    def __init__(self, name: str):
        self.name = name
        self.model = CLIPModel.from_pretrained(name)
        self.processor = CLIPProcessor.from_pretrained(name)
        self.model.eval()

    @torch.no_grad()
    def embed_image(self, images: list[Image.Image]) -> list[list[float]]:
        inputs = self.processor(images=images, return_tensors="pt")
        out = self.model.get_image_features(**inputs)
        # transformers>=5 returns BaseModelOutputWithPooling, not a tensor
        feats = out.pooler_output
        feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.cpu().numpy().tolist()

    @torch.no_grad()
    def embed_text(self, texts: list[str]) -> list[list[float]]:
        inputs = self.processor(text=texts, return_tensors="pt",
                                padding=True, truncation=True)
        out = self.model.get_text_features(**inputs)
        feats = out.pooler_output
        feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.cpu().numpy().tolist()
```

- [ ] **Step 4: Verify**

Run: `uv sync --project services/worker` — deps install.
Expected: no error (may take time to resolve/wheel).

- [ ] **Step 5: Commit**

```bash
git add services/worker && git commit -m "feat: worker config + clip model wrapper"
```

### Task 8: Worker EXIF + thumbnail

**Files:**
- Create: `services/worker/worker/exif.py`
- Create: `services/worker/worker/thumbnail.py`

- [ ] **Step 1: Create `services/worker/worker/exif.py`**

```python
"""ExifTool-based EXIF extraction (JSON)."""
from __future__ import annotations

from exiftool import ExifToolHelper


def _signed_deg(value, ref) -> float | None:
    """Apply hemisphere ref: S/W coords are stored unsigned + ref flag."""
    if value is None:
        return None
    return -abs(value) if ref in ("S", "W", "South", "West") else abs(value)


def extract(path: str) -> dict:
    """Return dict with standard fields; keys present only if available.
    NOTE: `-n` (numeric mode) is required so GPS comes back as floats, not
    DMS strings. Signs come from GPSLatitudeRef / GPSLongitudeRef."""
    with ExifToolHelper(common_args=["-n"]) as et:
        for d in et.get_metadata(path):
            lat = _signed_deg(d.get("GPSLatitude"), d.get("GPSLatitudeRef"))
            lon = _signed_deg(d.get("GPSLongitude"), d.get("GPSLongitudeRef"))
            taken = d.get("DateTimeOriginal") or d.get("CreateDate")
            mime = d.get("MIMEType", "")
            size = d.get("FileSize", 0)
            model = d.get("Model")
            return {"taken_at": taken, "gps_lat": lat, "gps_lon": lon,
                    "mime": mime, "size_bytes": size, "model": model}
    return {}
```

- [ ] **Step 2: Create `services/worker/worker/thumbnail.py`**

```python
"""Generate thumbnails (byte arrays) for content and face crops."""
from __future__ import annotations

import io

from PIL import Image


def thumbnail_bytes(path) 
```

```python
"""Generate a 512px-wide JPEG thumbnail of an image/video frame."""
from __future__ import annotations

import io
import subprocess

from PIL import Image


def image_thumbnail(path: str, max_dim: int = 512) -> bytes | None:
    try:
        img = Image.open(path)
        img.thumbnail((max_dim, max_dim))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=82)
        return buf.getvalue()
    except Exception:
        return None


def video_frame(path: str) -> bytes | None:
    """Extract a frame from video via ffmpeg → JPEG bytes."""
    try:
        out = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-i", path, "-frames:v", "1",
             "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
            capture_output=True, check=True,
        )
        return out.stdout or None
    except Exception:
        return None
```

- [ ] **Step 2: Verify (syntax)**

Run: `uv run --project services/worker python -m py_compile services/worker/worker/exif.py services/worker/worker/thumbnail.py`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add services/worker && git commit -m "feat: worker exif + thumbnail modules"
```

### Task 9: Worker faces

**Files:**
- Create: `services/worker/worker/faces.py`

- [ ] **Step 1: Create `services/worker/worker/faces.py`**

```python
"""Face detection + embedding via insightface (buffalo_l)."""
from __future__ import annotations

import numpy as np

from .config import FACE_MODEL


class FaceEngine:
    def __init__(self, name: str = FACE_MODEL):
        import insightface
        import insightface.app

        self.app = insightface.app.FaceAnalysis(name=name, providers=[
            "CPUExecutionProvider",
        ])
        self.app.prepare(ctx_id=0, det_size=(640, 640))

    def detect_and_embed(self, image: np.ndarray
    ) -> list[dict]:
        """Return [{'bbox': [x,y,w,h], 'embed': [512 floats], 'align': np-array}]."""
        faces = self.app.get(image)
        out = []
        for f in faces:
            ba = f.bbox.astype(int)
            out.append({
                "bbox": [int(v) for v in [ba[0], ba[1], ba[2]-ba[0], ba[3]-ba[1]]],
                "embed": f.normed_embedding.tolist(),
                "emb_norm": float(np.linalg.norm(f.normed_embedding)),
            })
        return out
```

- [ ] **Step 2: Verify (syntax)**

Run: `uv run --project services/worker python -m py_compile services/worker/worker/faces.py`
Expected: compile 0.

- [ ] **Step 3: Commit**

```bash
git add services/worker && git commit -m "feat: worker face engine"
```

### Task 10: Worker pipeline (one asset → catalog)

**Files:**
- Create: `services/worker/worker/pipeline.py`

- [ ] **Step 1: Create `services/worker/worker/pipeline.py`**

```python
"""Process a single file into catalog rows."""
from __future__ import annotations

import io
import json
import os
import uuid

import numpy as np
from PIL import Image

from core.assets import sha256_file, upsert_asset
from core.embeds import add_content, add_face
from core.geo import reverse as reverse_geocode
from core.conn import connect

from .config import DB_PATH, LIBRARY_ROOT, EMBED_MODEL_VERSION
from .exif import extract
from .thumbnail import image_thumbnail, video_frame
from .models import CLIP


def _import_one(clip: CLIP, face_engine, src_path: str) -> None:
    exif = extract(src_path)
    mime = exif.get("mime", "")
    thumb = image_thumbnail(src_path) if not mime.startswith("video") else video_frame(src_path)
    if thumb is None:
        raise ValueError(f"no thumbnail for {src_path}")

    sha = sha256_file(src_path)
    gps_lat, gps_lon = exif.get("gps_lat"), exif.get("gps_lon")
    if gps_lat is not None and gps_lon is not None:
        city, country = reverse_geocode(gps_lat, gps_lon)
    else:
        city = country = None
    crop_dir = os.path.join(LIBRARY_ROOT, ".crops")

    with connect(DB_PATH) as conn:
        img = Image.open(io.BytesIO(thumb))
        vec = clip.embed_image([img.convert("RGB")])[0]
        asset_id = upsert_asset(
            conn, path=src_path, sha256=sha, size_bytes=os.path.getsize(src_path),
            mime=mime, taken_at=exif.get("taken_at"),
            gps_lat=gps_lat, gps_lon=gps_lon,
            place_city=city, place_country=country,
            thumbnail=thumb, extra=exif,
        )
        add_content(conn, asset_id, clip.name, EMBED_MODEL_VERSION, vec)

        if face_engine is not None:
            os.makedirs(crop_dir, exist_ok=True)
            arr = np.array(img.convert("RGB"))
            for f in face_engine.detect_and_embed(arr):
                crop_bytes = None
                bbox = f["bbox"]  # [x, y, w, h]
                x, y, w, h = bbox
                crop = arr[max(0, y):max(0, y) + h, max(0, x):max(0, x) + w]
                if crop.size:
                    buf = io.BytesIO()
                    Image.fromarray(crop).save(buf, "JPEG", quality=90)
                    crop_bytes = buf.getvalue()
                cur = conn.execute(
                    "INSERT INTO faces (asset_id, bbox, crop_path) VALUES (?,?,?)",
                    (asset_id, json.dumps(bbox),
                     os.path.join(crop_dir, f"{uuid.uuid4().hex}.jpg") if crop_bytes else None),
                )
                face_id = cur.lastrowid
                add_face(conn, face_id, "buffalo_l", f["embedding"])
        conn.commit()
```

Note: `face_engine.detect_and_embed(arr)` must return a list of dicts shaped
`{"bbox": [x, y, w, h], "embedding": [512 floats]}` (see the faces interface
contract). This matches `_import_one(clip, face_engine, path)` in Task 12's
test, where the stub returns `[]` for empty scenes and real detections
otherwise.

- [ ] **Step 3: Verify (syntax)**

Run: `uv run --project services/worker python -m py_compile services/worker/worker/pipeline.py`
Expected: compile 0.

- [ ] **Step 4: Commit**

```bash
git add services/worker && git commit -m "feat: worker asset pipeline"
```

### Task 11: Worker embed HTTP service + drain loop

**Files:**
- Create: `services/worker/worker/embed_api.py`
- Create: `services/worker/worker/run.py`

- [ ] **Step 1: Create `services/worker/worker/embed_api.py`**

```python
"""Internal embed service for query embedding (api → worker)."""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from .config import EMBED_MODEL_VERSION, MODEL_NAME
from .models import CLIP


class EmbedTextReq(BaseModel):
    texts: list[str]


class ModelState:
    clip: CLIP | None = None
    loaded: bool = False


state = ModelState()
app = FastAPI()


@app.on_event("startup")
def _load():
    state.clip = CLIP(MODEL_NAME)
    state.loaded = True


@app.get("/v1/status")
def status():
    return {"ok": state.loaded,
            "model": MODEL_NAME, "version": EMBED_MODEL_VERSION}


@app.post("/v1/embed-text")
def embed_text(req: EmbedTextReq):
    if not state.loaded or state.clip is None:
        return {"error": "models_pending", "results": []}
    return {"model": MODEL_NAME,
            "results": state.clip.embed_text(req.texts)}
```

- [ ] **Step 2: Create `services/worker/worker/run.py`**

```python
"""Drain the jobs table and run the pipeline."""
from __future__ import annotations

import json
import time

from core import jobs
from core.conn import connect
from core.schema import migrate
from .config import DB_PATH, MODEL_NAME
from .faces import FaceEngine
from .models import CLIP
from .pipeline import _import_one


def drain_once(models) -> bool:
    """models is an object exposing `clip` and `faces` (or the stub)."""
    conn = connect(DB_PATH)
    migrate(conn)
    job = jobs.claim(conn)
    if job is None:
        conn.close()
        return False
    try:
        if job["kind"] == "import":
            params = json.loads(job["params"] or "{}")
            for path in params.get("paths", []):
                _import_one(models.clip, models.faces, path)
                jobs.set_progress(conn, job["id"], 0.5)
        # scan/reindex jobs are no-ops for now; complete them so the queue
        # drains rather than blocking
        jobs.complete(conn, job["id"])
    except Exception as e:  # the pipeline should be resilient
        jobs.fail(conn, job["id"], str(e))
    finally:
        conn.close()
    return True


class _Runtime:
    def __init__(self):
        self.clip = CLIP(MODEL_NAME)
        self.faces = FaceEngine()


def main():
    models = _Runtime()
    while True:
        did = drain_once(models)
        if not did:
            time.sleep(5)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Verify (syntax)**

Run: `uv run --project services/worker python -m py_compile services/worker/worker/run.py services/worker/worker/embed_api.py`
Expected: compile 0.

- [ ] **Step 4: Commit**

```bash
git add services/worker && git commit -m "feat: worker job drain + embed api"
```

### Task 12: Worker Dockerfile + integration test

**Files:**
- Create: `services/worker/Dockerfile`
- Create: `services/worker/tests/test_pipeline.py`

- [ ] **Step 1: Create `services/worker/tests/test_pipeline.py`**

```python
"""Integration: pipe a tiny JPEG through ingest and assert catalog rows.

Requires the `exiftool` binary on PATH (it reports JPEG mime/type).
Faces and CLIP are stubbed out — this test is for the DB plumbing, not
for ML correctness (validated separately in the spike).
"""
from __future__ import annotations

import os

from PIL import Image
from core.conn import connect
from core.schema import migrate
from core import jobs


class FakeClip:
    name = "fake-clip"

    @staticmethod
    def embed_image(imgs):
        return [[0.1] * 512 for _ in imgs]


class NoFaces:
    @staticmethod
    def detect_and_embed(arr):
        return []


def _make_jpeg(path: str) -> None:
    Image.new("RGB", (64, 64), color=(200, 0, 0)).save(path, "JPEG")


def test_ingest_pipeline(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    img_path = lib / "a.jpg"
    _make_jpeg(str(img_path))

    db = tmp_path / "catalog.db"
    os.environ["PICS_DB"] = str(db)
    os.environ["PICS_LIBRARY"] = str(lib)

    # import happens relative to DB path in config; point config at the tmp db
    import worker.config as cfg
    cfg.DB_PATH = str(db)
    cfg.LIBRARY_ROOT = str(lib)

    conn = connect(str(db))
    migrate(conn)

    from worker.pipeline import _import_one
    jid = jobs.push(conn, "import", {"paths": [str(img_path)]})

    _import_one(FakeClip(), NoFaces(), str(img_path))
    jobs.complete(conn, jid)

    rows = conn.execute("SELECT * FROM assets").fetchall()
    emb = conn.execute("SELECT * FROM content_embeds").fetchall()
    assert len(rows) == 1
    assert rows[0]["mime"] == "image/jpeg"
    assert len(emb) == 1  # vector persisted
    conn.close()
```

- [ ] **Step 3: Create `services/worker/Dockerfile`**

```dockerfile
# build context = repo root (docker compose build ./)
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    exiftool ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY packages/core /app/packages/core
COPY services/worker /app/services/worker
COPY packages/worker-requirements.txt /app/  # optional: pin to lockfile
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu torch
RUN pip install --no-cache-dir -e /app/packages/core && \
    pip install --no-cache-dir -e /app/services/worker
EXPOSE 9090
CMD ["python", "-m", "uvicorn", "worker.embed_api:app", "--host", "0.0.0.0", "--port", "9090"]
```

(Expected image ~3 GB after install — validated in spike 2. Model weights +
`HF_HOME`/insightface cache live on the `models/` volume so re-builds don't
re-download.)

- [ ] **Step 4: Verify (offline-path only, skip slow model)**

Run: `uv run --project services/worker pytest services/worker/tests/test_pipeline.py -x -k "not _slow"`
Expected: PASS — uses fake CLIP, no internet.

- [ ] **Step 5: Commit**

```bash
git add services/worker && git commit -m "test+deploy: worker Dockerfile + pipeline integration"
```

### Task 13: `apps/api` — skeleton + deps

**Files:**
- Create: `apps/api/pyproject.toml`
- Create: `apps/api/api/__init__.py`
- Create: `apps/api/api/deps.py`

- [ ] **Step 1: Create `apps/api/pyproject.toml`**

```toml
[project]
name = "api"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "core",
  "fastapi>=0.115",
  "uvicorn>=0.30",
  "python-multipart>=0.0.9",
  "httpx>=0.27",
  "pydantic>=2.7",
]
[tool.uv.sources]
core = { path = "../../packages/core" }
```

- [ ] **Step 2: Create `apps/api/api/__init__.py`**

```python
"""FastAPI application package."""
```

- [ ] **Step 3: Create `apps/api/api/deps.py`**

```python
"""Shared dependencies: catalog connection, worker embed client."""
from __future__ import annotations

import os

from fastapi import Request

from core.conn import connect

WORKER_URL = os.environ.get("PICS_WORKER_URL", "http://worker:9090")


def get_conn() -> None:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


async def embed_text(texts: list[str]) -> list[list[float]]:
    import httpx
    async with httpx.AsyncClient() as cl:
        r = await cl.post(
            f"{WORKER_URL}/v1/embed-text", json={"texts": texts})
        if r.status_code != 200:
            return []
        return r.json().get("results", [])
```

- [ ] **Step 4: Commit**

```bash
git add apps/api && git commit -m "chore: api skeleton + deps"
```

### Task 14: API search endpoint

**Files:**
- Create: `apps/api/api/search.py`

- [ ] **Step 1: Create `apps/api/api/search.py`**

```python
"""Hybrid NL + structured filter search."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import core.embeds as embeds

from .deps import get_conn, embed_text

router = APIRouter()


class SearchReq(BaseModel):
    q: str | None = None
    who: str | None = None
    place: str | None = None
    before: str | None = None
    after: str | None = None
    tag: str | None = None
    limit: int = 50


def _filtered_ids(conn, who, place, before, after, tag) -> set[int]:
    """Return a set of asset ids matching the structured filters (or ALL ids
    when no structured filter is present — the KNN list is the only filter)."""
    base = "SELECT id FROM assets WHERE 1=1"
    params = []
    if place:
        base += " AND (place_city LIKE ? OR place_country LIKE ?)"
        params += [f"%{place}%", f"%{place}%"]
    if before:
        base += " AND taken_at IS NOT NULL AND taken_at <= ?"
        params.append(before)
    if after:
        base += " AND taken_at IS NOT NULL AND taken_at >= ?"
        params.append(after)
    if tag:
        base += " AND id IN (SELECT asset_id FROM tags WHERE tag=?)"
        params.append(tag)
    if who:
        base += (" AND id IN (SELECT asset_id FROM faces JOIN persons"
                 " ON faces.cluster_id = persons.id WHERE persons.name=?)")
        params.append(who)
    return {r["id"] for r in conn.execute(base, params).fetchall()}


@router.get("/search")
def search(q: str | None = None, who: str | None = None,
           place: str | None = None, before: str | None = None,
           after: str | None = None, tag: str | None = None,
           limit: int = 50, conn=Depends(get_conn)):
    has_any = any([who, place, before, after, tag, q])
    if not has_any:
        # no query at all → just return the most recent assets
        rows = conn.execute(
            "SELECT id FROM assets ORDER BY taken_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return {"results": [{"asset_id": r["id"]} for r in rows]}

    results = []
    if q:
        vec = embed_text([q])
        if not vec:
            raise HTTPException(503, "models_pending")
        ranked = embeds.cos_knn(conn, vec[0], limit=limit * 4)
        results = [{"asset_id": i, "distance": d} for i, d in ranked]
    else:
        results = [{"asset_id": r["id"]} for r in conn.execute(
            "SELECT id FROM assets ORDER BY id DESC LIMIT ?", (limit * 4,)
        )]

    if who or place or before or after or tag:
        allowed = _filtered_ids(conn, who, place, before, after, tag)
        results = [r for r in results if r["asset_id"] in allowed]

    return {"results": results[:limit]}
```

- [ ] **Step 3: Verify (syntax)**

Run: `uv run --project apps/api python -m py_compile apps/api/api/search.py`
Expected: compile 0.

- [ ] **Step 4: Commit**

```bash
git add apps/api && git commit -m "feat: api search endpoint"
```

### Task 15: API upload + jobs + assets

**Files:**
- Create: `apps/api/api/uploads.py`
- Create: `apps/api/api/jobs.py`

- [ ] **Step 1: Create `apps/api/api/uploads.py`**

```python
"""Upload photos → library + jobs."""
from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Response, UploadFile

from core import jobs

from .deps import get_conn

router = APIRouter()

LIBRARY = Path(os.environ.get("PICS_LIBRARY", "library"))


@router.post("/assets/upload")
async def upload(file: UploadFile = File(...), conn=Depends(get_conn)):
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() or "jpg"
    rel = LIBRARY / f"imports/{uuid.uuid4().hex}.{ext}"
    rel.parent.mkdir(parents=True, exist_ok=True)
    with open(rel, "wb") as w:
        shutil.copyfileobj(file.file, w)
    jid = jobs.push(conn, "import", {"paths": [str(rel)]})
    return {"job_id": jid, "status": "queued", "path": str(rel)}


@router.get("/assets/{asset_id}/thumbnail")
def thumbnail(asset_id: int, conn=Depends(get_conn)):
    """Serve the stored thumbnail bytes for an asset."""
    from fastapi import HTTPException

    name = "thumbnail"
    row = conn.execute(
        """SELECT f.bytes FROM files f
           JOIN assets a ON a.thumbnail_id = f.id
           WHERE a.id = ?""",
        (asset_id,),
    ).fetchone()
    if row is None or row["bytes"] is None:
        raise HTTPException(404, "thumbnail not found")
    return Response(content=row["bytes"], media_type="image/jpeg")
```

- [ ] **Step 2: Create `apps/api/api/jobs.py`**

```python
"""Job listing/progress."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from core.conn import connect
from .deps import get_conn

router = APIRouter()


@router.get("/jobs")
def list_jobs(conn=Depends(get_conn)):
    rows = conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 100").fetchall()
    return {"jobs": [dict(r) for r in rows]}


@router.get("/jobs/{job_id}")
def get_job(job_id: int, conn=Depends(get_conn)):
    r = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return dict(r) if r else {"error": "not_found"}
```

- [ ] **Step 3: Verify (syntax)**

Run: `uv run python -m py_compile apps/api/api/uploads.py apps/api/api/jobs.py`
Expected: compile 0.

- [ ] **Step 4: Commit**

```bash
git add apps/api && git commit -m "feat: api upload + jobs endpoints"
```

### Task 16: API persons + places

**Files:**
- Create: `apps/api/api/persons.py`
- Create: `apps/api/api/places.py`

- [ ] **Step 1: Create `apps/api/api/persons.py`**

```python
"""Person clusters review (list/rename/merge/split)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.conn import connect
from .deps import get_conn

router = APIRouter()


@router.get("/persons")
def list_persons(conn=Depends(get_conn)):
    rows = conn.execute(
        """SELECT p.id, p.name, p.status, COUNT(f.id) AS face_count
           FROM persons p LEFT JOIN faces f ON f.cluster_id = p.id
           GROUP BY p.id HAVING COUNT(f.id) > 0""").fetchall()
    return {"persons": [dict(r) for r in rows]}


class RenameReq(BaseModel):
    name: str


@router.patch("/persons/{pid}")
def rename(pid: int, body: RenameReq, conn=Depends(get_conn)):
    conn.execute("UPDATE persons SET name=?, status='named' WHERE id=?",
                 (body.name, pid))
    conn.commit()
    return {"ok": True}


@router.post("/persons/{a}/merge/{b}")
def merge(a: int, b: int, conn=Depends(get_conn)):
    conn.execute("UPDATE faces SET cluster_id=? WHERE cluster_id=?", (a, b))
    conn.execute("DELETE FROM persons WHERE id=?", (b,))
    conn.commit()
    return {"ok": True}
```

- [ ] **Step 2: Create `apps/api/api/places.py`**

```python
"""Top place buckets for the map page."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from core.conn import connect
from .deps import get_conn

router = APIRouter()


@router.get("/places")
def places(limit: int = 25, conn=Depends(get_conn)):
    rows = conn.execute(
        """SELECT place_city, place_country, COUNT(*) AS n
           FROM assets WHERE place_city IS NOT NULL
           GROUP BY place_city, place_country ORDER BY n DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return {"places": [dict(r) for r in rows]}
```

- [ ] **Step 3: Verify (syntax)**

Run: `uv run python -m py_compile apps/api/api/persons.py apps/api/api/places.py`
Expected: compile 0.

- [ ] **Step 4: Commit**

```bash
git add apps/api && git commit -m "feat: api persons + places endpoints"
```

### Task 17: API main + router mount + tests

**Files:**
- Create: `apps/api/api/main.py`
- Create: `apps/api/tests/conftest.py`
- Create: `apps/api/tests/test_api.py`
- Create: `apps/api/Dockerfile`

- [ ] **Step 1: Create `apps/api/api/main.py`**

```python
from __future__ import annotations

from fastapi import FastAPI

from . import jobs as jobs_r
from . import persons as persons_r
from . import places as places_r
from . import search as search_r
from . import uploads as uploads_r

app = FastAPI(title="pics")

app.include_router(search_r.router, prefix="/search", tags=["search"])
app.include_router(uploads_r.router, prefix="/assets", tags=["assets"])
app.include_router(jobs_r.router, prefix="/jobs", tags=["jobs"])
app.include_router(persons_r.router, prefix="/persons", tags=["persons"])
app.include_router(places_r.router, prefix="/places", tags=["places"])


@app.get("/")
def root():
    return {"ok": True}
```

- [ ] **Step 3: Create `apps/api/tests/conftest.py`**

```python
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("PICS_WORKER_URL", "http://worker:9090")

from api.deps import get_conn
from api.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "catalog.db")
    # point the catalog dependency at a per-test db
    from core.conn import connect as raw_connect
    from core.schema import migrate

    conn = raw_connect(db)
    migrate(conn)
    conn.close()

    def _dep():
        c = raw_connect(db)
        try:
            yield c
        finally:
            c.close()

    app.dependency_overrides[get_conn] = _dep
    yield TestClient(app)
    app.dependency_overrides.clear()
```

Note: each test gets its own db at `tmp_path/catalog.db`; the `get_conn`
dependency is overridden to that path. The `client` fixture yields a
`TestClient(app)` and clears overrides afterward.

- [ ] **Step 4: Create `apps/api/tests/test_api.py`**

```python
"""API endpoint tests (per-test catalog db via client fixture)."""


def test_health(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_jobs_endpoint(client):
    from core import jobs as j
    from api.deps import get_conn

    with client.app.dependency_overrides[get_conn]() as conn:
        jid = j.push(conn, "scan")
    assert jid >= 1

    r = client.get("/jobs")
    assert r.status_code == 200
    assert len(r.json()["jobs"]) == 1


def test_search_no_query_returns_recent(client):
    r = client.get("/search", params={"limit": 10})
    assert r.status_code == 200
    assert isinstance(r.json()["results"], list)
```

- [ ] **Step 5: Create `apps/api/Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY packages/core /app/packages/core
COPY apps/api /app/apps/api
RUN pip install -e /app/packages/core && pip install -e /app/apps/api
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 6: Verify**

Run: `uv sync --project apps/api && uv run --project apps/api pytest apps/api/tests/`
Expected: PASS — tests green with fake DB.

- [ ] **Step 7: Commit**

```bash
git add apps/api && git commit -m "feat: api app main + tests"
```

### Task 18: CLI — `pics scan/query`

**Files:**
- Create: `tools/cli/pyproject.toml`
- Create: `tools/cli/cli/__main__.py`
- Create: `tools/cli/cli/commands.py`

- [ ] **Step 1: Create `tools/cli/pyproject.toml`**

```toml
[project]
name = "pics-cli"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["core", "httpx>=0.27", "rich>=13"]
[project.scripts]
pics = "cli.__main__:main"
[tool.uv.sources]
core = { path = "../../packages/core" }
```

- [ ] **Step 2: Create `tools/cli/cli/__main__.py`**

```python
import sys

from .commands import main

sys.exit(main())
```

- [ ] **Step 3: Create `tools/cli/cli/commands.py`**

```python
"""pics CLI commands."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from core import jobs
from core.conn import connect


def cmd_scan(args):
    conn = connect()
    paths = [str(p) for p in Path(args.dir).rglob("*") if p.is_file()
             and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".heic", ".mov",
                                      ".mp4", ".heif", ".avif", ".cr2", ".nef", ".arw"}]
    jid = jobs.push(conn, "import", {"paths": paths})
    print(f"queued {len(paths)} paths as job {jid}")
    conn.close()


def cmd_query(args):
    import httpx
    r = httpx.get("http://localhost:8000", timeout=5)
    # use the api endpoint
    params = {"q": args.q, "limit": args.limit}
    if args.who: params["who"] = args.who
    if args.place: params["place"] = args.place
    r = httpx.get("http://localhost:8000/search", params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    for row in data["results"]:
        print(row)


def cmd_strip_exif(args):
    import subprocess
    tmp = Path(args.path)
    out = tmp.with_name(tmp.stem + "_clean" + tmp.suffix)
    subprocess.run(["exiftool", "-all=", "-o", str(out), str(tmp)], check=True)
    conn = connect()
    conn.execute("UPDATE assets_aux SET stripped=1 WHERE path=?",
                 (str(tmp),))
    conn.commit()
    conn.close()
    print(f"stripped copy → {out}")


def cmd_reindex(args):
    conn = connect()
    n = conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    print(f"reindex {n} assets (run worker with model-version bump)")


def build_parser():
    p = argparse.ArgumentParser(prog="pics")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan"); s.add_argument("dir"); s.set_defaults(func=cmd_scan)
    q = sub.add_parser("query"); q.add_argument("q"); q.add_argument("--who");
    q.add_argument("--place"); q.add_argument("--limit", type=int, default=15)
    q.set_defaults(func=cmd_query)
    st = sub.add_parser("strip-exif"); st.add_argument("path"); st.set_defaults(func=cmd_strip_exif)
    r = sub.add_parser("reindex"); r.set_defaults(func=cmd_reindex)
    return p


def main():
    args = build_parser().parse_args()
    return args.func(args) or 0
```

- [ ] **Step 4: Add `cmd_query`**

```python
def cmd_query(args):
    import httpx
    base = os.environ.get("PICS_API", "http://localhost:8000")
    params = {"q": args.q, "limit": args.limit}
    if args.who: params["who"] = args.who
    if args.place: params["place"] = args.place
    r = httpx.get(f"{base}/search", params=params, timeout=60)
    r.raise_for_status()
    for row in r.json()["results"]:
        print(f"{row[0]}\t{row[1]:.3f}\t{row['path'] if 'path' in row else ''}")
```

- [ ] **Step 5: Verify (syntax)**

Run: `uv run --project tools/cli python -m py_compile tools/cli/cli/commands.py`
Expected: compile 0.

- [ ] **Step 6: Commit**

```bash
git add tools/cli && git commit -m "feat: pics cli (scan/query/strip/reindex)"
```

### Task 19: Web — scaffold Next.js

**Files:**
- Create: `apps/web/package.json`
- Create: `apps/web/next.config.ts`
- Create: `apps/web/tsconfig.json`
- Create: `apps/web/app/layout.tsx`

- [ ] **Step 1: Create `apps/web/package.json`**

```json
{
  "name": "web",
  "private": true,
  "packageManager": "pnpm@10.0.0",
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "test": "vitest run"
  },
  "dependencies": {
    "next": "^15.0.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "typescript": "^5.6",
    "vitest": "^3.0",
    "@types/react": "^19",
    "@types/node": "^22"
  }
}
```

- [ ] **Step 2: Create `apps/web/next.config.ts`**

```typescript
import type { NextConfig } from "next";
const nextConfig: NextConfig = {
  output: "standalone",
};
export default nextConfig;
```

- [ ] **Step 3: Create `apps/web/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "preserve",
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "incremental": true
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 4: Create `apps/web/app/layout.tsx`**

```tsx
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "Pics" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
```

- [ ] **Step 5: Create `apps/web/app/globals.css`**

```css
* { box-sizing: border-box; }
body { margin: 0; font-family: ui-sans-serif, system-ui, sans-serif; }
```

- [ ] **Step 6: Verify**

Run: `cd apps/web && pnpm install && pnpm build`
Expected: Next.js builds (pages exist).

- [ ] **Step 7: Commit**

```bash
git add apps/web && git commit -m "chore: scaffold next.js app"
```

### Task 20: Web types + API client

**Files:**
- Create: `apps/web/types.ts`
- Create: `apps/web/lib/api.ts`
- Create: `apps/web/lib/search-parser.ts`
- Create: `apps/web/lib/search-parser.test.ts`

- [ ] **Step 1: Create `apps/web/types.ts`**

```typescript
export interface Asset {
  id: number;
  path: string;
  mime: string;
  taken_at: string | null;
  place_city: string | null;
  place_country: string | null;
  thumbnail_id: number | null;
}

export interface SearchResult {
  asset_id: number;
  distance: number;
}

export interface SearchResponse {
  results: SearchResult[];
}

export interface Person { id: number; name: string; face_count: number; status: string; }

export interface Place { place_city: string | null; place_country: string | null; n: number; }

export interface JobRow { id: number; kind: string; status: string; progress: number | null; error: string | null; }
```

- [ ] **Step 2: Create `apps/web/lib/api.ts`**

```typescript
const API = process.env.PICS_API_URL ?? "http://localhost:8000";

export async function search(opts: {
  q?: string | null;
  who?: string | null;
  place?: string | null;
  before?: string | null;
  after?: string | null;
  tag?: string | null;
  limit?: number;
}): Promise<SearchResponse> {
  const p = new URLSearchParams();
  if (opts.q) p.set("q", opts.q);
  if (opts.who) p.set("who", opts.who);
  if (opts.place) p.set("place", opts.place);
  if (opts.before) p.set("before", opts.before);
  if (opts.after) p.set("after", opts.after);
  if (opts.tag) p.set("tag", opts.tag);
  if (opts.limit) p.set("limit", String(opts.limit));
  const r = await fetch(`${API}/search?${p}`);
  if (!r.ok) throw new Error(`search failed: ${r.status}`);
  return r.json();
}

export async function fetchPersons(): Promise<Person[]> {
  const r = await fetch(`${API}/persons`);
  if (!r.ok) throw new Error("persons failed");
  return (await r.json()).persons;
}
```

- [ ] **Step 3: Create `apps/web/lib/search-parser.ts`**

```typescript
export interface ParsedQuery {
  text: string;
  who: string | null;
  place: string | null;
  before: string | null;
  after: string | null;
  tag: string | null;
}

/** Parse a query like "birthday at beach who:Sam before:2020" into filters + free text. */
export function parseQuery(raw: string): ParsedQuery {
  const out: ParsedQuery = { text: "", who: null, place: null, before: null, after: null, tag: null };
  const tokens = raw.split(/\s+/).filter(Boolean);
  const keep: string[] = [];
  const setter: Record<string, (v: string) => void> = {
    who: (v) => (out.who = v),
    place: (v) => (out.place = v),
    before: (v) => (out.before = v),
    after: (v) => (out.after = v),
    tag: (v) => (out.tag = v),
  };
  for (const t of tokens) {
    const m = t.match(/^(\w+):(.*)$/);
    if (m && m[1] in setter) { setter[m[1]](m[2]); }
    else keep.push(t);
  }
  out.text = keep.join(" ");
  return out;
}
```

- [ ] **Step 4: Create `apps/web/lib/search-parser.test.ts`**

```typescript
import { describe, expect, it } from "vitest";
import { parseQuery } from "./search-parser";

describe("parseQuery", () => {
  it("keeps free text", () => {
    expect(parseQuery("birthday cake").text).toBe("birthday cake");
  });
  it("extracts who", () => {
    expect(parseQuery("beach who:sam").who).toBe("sam");
  });
  it("extracts date + place", () => {
    const r = parseQuery("beach place:portugal before:2019-01-01");
    expect(r.place).toBe("portugal");
    expect(r.before).toBe("2019-01-01");
  });
});
```

- [ ] **Step 5: Verify**

Run: `cd apps/web && pnpm test`
Expected: PASS — 3 tests passing.

- [ ] **Step 6: Commit**

```bash
git add apps/web && git commit -m "feat: web api client + query parser"
```

### Task 21: Web — search page + grid components

**Files:**
- Create: `apps/web/app/page.tsx`
- Create: `apps/web/components/SearchBar.tsx`
- Create: `apps/web/components/Grid.tsx`

- [ ] **Step 1: Create `apps/web/app/page.tsx`**

```tsx
"use client";
import { useState } from "react";
import { SearchBar } from "../components/SearchBar";
import { Grid } from "../components/Grid";
import { search } from "../lib/api";
import type { Asset } from "../types";

export default function Home() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [error, setError] = useState<string | null>(null);

  const run = async (q: string, query: ParsedFilters) => {
    try {
      const data = await search({ q, ...query, limit: 50 });
      setAssets(data.results.map((d) => assets[0] ? d as unknown as Asset : d));
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <main>
      <SearchBar onSearch={run} />
      {error && <p style={{ color: "red" }}>{error}</p>}
      <Grid assets={assets} />
    </main>
  );
}
```

For a clean page component, move the mapping: `SearchBar` calls
`onSearch(text: string, filters: {who?, place?})` (defined below), and the page
does `search({ q: text, who, place, limit: 50 })`.

- [ ] **Step 2: Create `apps/web/components/SearchBar.tsx`**

```tsx
"use client";
import { useState } from "react";
import { parseQuery } from "../lib/search-parser";

export function SearchBar({ onSearch }: { onSearch: (q: string, f: Record<string, string | null>) => void }) {
  const [val, setVal] = useState("");
  return (
    <form onSubmit={(e) => {
      e.preventDefault();
      const p = parseQuery(val);
      onSearch(p.text, { who: p.who, place: p.place, before: p.before, after: p.after, tag: p.tag });
    }}>
      <input value={val} onChange={(e) => setVal(e.target.value)} placeholder="search photos…" />
      <button type="submit">Search</button>
    </form>
  );
}
```

- [ ] **Step 3: Create `apps/web/components/Grid.tsx`**

```tsx
import type { Asset } from "../types";

export function Grid({ assets }: { assets: Asset[] }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 8 }}>
      {assets.map((a) => (
        <figure key={a.id}>
          <img src={`http://localhost:8000/assets/${a.id}/thumbnail`} alt={a.path} loading="lazy" style={{ width: "100%", aspectRatio: "1", objectFit: "cover" }} />
          <figcaption>{a.taken_at ?? ""}</figcaption>
        </figure>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Verify (build)**

Run: `cd apps/web && pnpm build`
Expected: builds without type errors.

- [ ] **Step 5: Commit**

```bash
git add apps/web && git commit -m "feat: web search + grid"
```

### Task 22: Web people / places / settings pages

**Files:**
- Create: `apps/web/app/people/page.tsx`
- Create: `apps/web/app/places/page.tsx`
- Create: `apps/web/app/settings/page.tsx`

- [ ] **Step 1: Create `apps/web/app/people/page.tsx`**

```tsx
"use client";
import { useEffect, useState } from "react";
import { fetchPersons } from "../../lib/api";
import type { Person } from "../../types";

export default function People() {
  const [persons, setPersons] = useState<Person[]>([]);
  useEffect(() => { fetchPersons().then(setPersons); }, []);
  return (
    <main>
      <h1>People</h1>
      {persons.map((p) => (
        <div key={p.id} style={{ marginBottom: 8 }}>
          <input value={p.name} placeholder="unnamed" onChange={(e) => { p.name = e.target.value; }} />
          <span>{p.face_count} faces</span>
        </div>
      ))}
    </main>
  );
}
```

- [ ] **Step 2: Create `apps/web/app/places/page.tsx`**

```tsx
"use client";
import { useEffect, useState } from "react";
import type { Place } from "../../types";

export default function Places() {
  const [places, setPlaces] = useState<Place[]>([]);
  useEffect(() => {
    fetch("http://localhost:8000/places")
      .then((r) => r.json())
      .then((d) => setPlaces(d.places));
  }, []);
  return (
    <main>
      <h1>Places</h1>
      {places.map((p, i) => (
        <p key={i}>{p.place_city} · {p.place_country} · {p.n}</p>
      ))}
    </main>
  );
}
```

- [ ] **Step 3: Create `apps/web/app/settings/page.tsx`**

```tsx
"use client";
export default function Settings() {
  return (
    <main>
      <h1>Settings</h1>
      <p>Ingest:</p>
      <pre>docker compose exec worker python -m worker.run</pre>
    </main>
  );
}
```

- [ ] **Step 4: Verify (build)**

Run: `cd apps/web && pnpm build`
Expected: builds clean.

- [ ] **Step 5: Commit**

```bash
git add apps/web && git commit -m "feat: people/places/settings pages"
```

### Task 23: Web Dockerfile + compose

**Files:**
- Create: `apps/web/Dockerfile`
- Create: `docker-compose.yml`

- [ ] **Step 1: Create `apps/web/Dockerfile`**

```dockerfile
FROM node:24-alpine AS build
WORKDIR /app
COPY apps/web/package.json pnpm-lock.yaml ./
RUN pnpm config set --global node-linker; pnpm install --frozen-lockfile || true
COPY apps/web .
RUN pnpm build
FROM node:20-slim
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next/standalone ./
RUN echo "import { fileURLToPath } from 'url'; ..." >/dev/null
CMD ["node", "server.js"]
```

- [ ] **Step 2: Create `docker-compose.yml`**

```yaml
version: "3.9"
services:
  web:
    build: ./apps/web
    ports: ["3000:3000"]
    environment:
      - PICS_API_URL=http://api:8000
  api:
    build: ./apps/api
    ports: ["8000:8000"]
    environment:
      - PICS_DB=/data/catalog.db
      - PICS_WORKER_URL=http://worker:9090
    volumes: ["catalog:/data", "library:/library"]
  worker:
    build:
      context: .
      dockerfile: services/worker/Dockerfile
    environment:
      - PICS_DB=/data/catalog.db
      - PICS_LIBRARY=/library
      - PICS_MODEL=openai/clip-vit-base-patch32
      - HF_HOME=/models
    volumes: ["catalog:/data", "library:/library", "models:/models"]
    command: ["python", "-m", "uvicorn", "worker.embed_api:app", "--host", "0.0.0.0", "--port", "9090"]
volumes:
  catalog:
  library:
  models:
```

- [ ] **Step 3: Verify**

Run: `docker compose config`
Expected: parses clean (no errors).

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml apps/web/Dockerfile && git commit -m "feat: compose stack"
```

### Task 24: Final verification + docs

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document compose + CLI usage**

Append to `README.md`:

```markdown
## Docker quickstart

    docker compose up --build
    # web:3000, api:8000

## CLI

    uv sync --project tools/cli
    pics scan ~/Photos
    pics query "birthday cake"
    pics strip-exif path/to/img.jpg
```

- [ ] **Step 2: Run all unit tests**

```bash
uv run --project packages/core pytest packages/core/tests
uv run --project apps/api pytest apps/api/tests
cd apps/web && pnpm test
```

Expected: all pass.

- [ ] **Step 3: Compose up smoke**

```bash
docker compose up --build -d
curl -s http://localhost:8000/ | grep ok
curl -s "http://localhost:8000/search?q=cake" | head
```

Expected: api returns `{"ok": true}`; search returns `(503 if model not downloaded yet)`.

- [ ] **Step 4: Commit**

```bash
git add README.md && git commit -m "docs: run instructions"
```

## Verification Summary

- [ ] `uv run --project packages/core pytest packages/core/tests` — all pass
- [ ] `uv run --project apps/api pytest apps/api/tests` — all pass
- [ ] `cd apps/web && pnpm test` — parser tests pass
- [ ] `docker compose up --build -d` starts web/api/worker
- [ ] `curl localhost:8000/` returns `{"ok": true}`
- [ ] `curl "localhost:8000/search?q=birthday"` returns results or 503 (models_pending)
- [ ] `pics scan <dir>` queues paths; `pics query "cake"` prints rows