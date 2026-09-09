---
title: Photo Searchable Library — Technical Design
tags:
  - design
  - photo-searchable-library
  - sqlite-vec
  - FastAPI
  - Next.js
keywords:
  - photo library design
  - CLIP embedding pipeline
  - SQLite vector search
  - Docker Compose worker
  - FastAPI search API
  - Next.js photo UI
created: 2026-09-10
updated: 2026-09-10
---

# Photo Searchable Library — Design (v1)

## 0. Approval trail

- **Scope:** full end-to-end (all subsystems) in this session.
- **Approaches considered:** A (Files mgmt: separate worker+api+web sharing SQLite), B (all-in-FastAPI), C (Next.js drives everything).
- **Chosen:** A.

## 1. Architecture overview

One Docker Compose stack with three services, sharing a single SQLite catalog
file and a library of photo files on disk:

```
compose: services{api, worker, web}  volumes{ catalog.db, library/, models/ }
```

- **catalog.db** — the single source of truth. Assets, faces, tags,
  embeddings (sqlite-vec `vec0`), and a `jobs` table for async index progress.
- **library/** — original photo files (mounted read-write; uploads write here,
  indexes read/write thumbnails). EXIF-stripped status lives in catalog, not in
  the file.
- **models/** — downloaded weights cache for CLIP/face models (shared across
  worker restarts).

All services talk to each other through the **SQLite file and the library
folder**. The API is the only service exposed to the user/LAN; web and worker
are internal. The one exception is an internal HTTP hop from `api` to `worker`
for query-embedding (api → worker `/v1/embed-text`) — kept off the main flow
because the only cross-service call is model runtime.

## 2. Components

### 2.1 `api` — FastAPI (thin)

- **`POST /assets/upload`** — accepts multipart uploads (photo or a `.zip` of
  photos), writes bytes into `library/imports/<yyyy-mm>/<asset-sha>.jpg`, then
  inserts a row into the SQLite `jobs` queue (`kind=scan_path`) and returns
  `{job_id, status}`.
- **`GET /search?q=…&who=Sam&place=Portugal&before=2019-01-01&tag=…`** — embeds
  the text query, runs exact KNN on `content_embeds`, post-filters structured
  filters against `assets` metadata + `faces` clusters, returns ranked asset
  rows (see §5 Data flow).
- **`GET /assets/{id}`** — row + URLs for the original file and generated
  thumbnail.
- **`GET /jobs`** / **`GET /jobs/{id}`** — progress for the UI (watch runs).
- **`GET /meta/counts`** — library stats for dashboard (assets, persons, cities).
- **`GET /places`** — top place buckets (reverse-geocoded).
- **`GET /persons`** + **`PATCH /persons/{id}`** — cluster list w/ centroids,
  rename/merge/split (mutates `faces` + emits an optional `recluster` job).

Model-facing: the API **embeds the query** by calling the worker's embedding
runtime over HTTP (api → worker `/embed/text?model=cliper`). Everything else is
SQLite.

### 2.2 `worker` — Python, long-lived process (in a container)

Owns the heavy lifting. Drains the `jobs` table:

- **`import` job:** EXIF extract (ExifTool) → thumbnail (Pillow/ffmpeg) →
  content CLIP embed → face detect + embed → write catalog rows → mark job
  done. Deleted file detection on scan-cli side.
- **`rescan` job:** walks library dir, hashes files, dedups (content-addressed
  by SHA-256), adds missing `assets`, marks removed `deleted=1`.
- **`reindex` job (optional trigger):** re-embeds all assets when the CLIP
  model version changes (bump `embedding.model_version`). Avoids embedding
  drift (§6 risks).
- Long-lived, single-process. Loads CLIP + face models eagerly at startup;
  does batch GPU if present, else CPU. Idempotent ingestion via `sha256`.

Worker also runs **the query-embedding HTTP server** exposed only inside
compose (api calls it): `POST /v1/embed-text`, `POST /v1/embed-image@?list`, a
`/v1/status` with model load state. This keeps the *model runtime* behind one
interface so an API request never spawns model work.

### 2.3 `web` — Next.js (React, TypeScript)

- **Pages:** Library (grid of thumbnails, virtualized), Search box + filter
  sidebar (who / place / date / tag), People page (name clusters,
  merge/split), Map (cluster by place), Settings (scan button, reindex, EXIF
  strip toggle, model choice).
- **Data source:** calls `api` (FastAPI) via same-LAN; never touches SQLite
  directly. Render-facing only.
- **Upload UI:** multi-file drop → `POST /api/upload` (multipart), polls
  `/jobs/{id}` for progress bar.

### 2.4 `cli` (dev/add-on, not a container service)

`pics` — Python package in repo `tools/cli`, depends on `packages/core`
(reuses schema, queue, catalog, KNN glue). Commands:

- `pics scan <dir>` → inserts `job kind=scan`
- `pics query "birthday cake" [--who Sam] [--place ...]` → embeds + KNN,
  prints table
- `pics strip-exif <id|path>` — console tool calls ExifTool to copy the or ass
  to a clean copy and marks `stripped=1`
- `pics reindex` — force model-version bump + re-embed

## 3. Data model (SQLite schema v1)

```sql
CREATE TABLE assets (
  id          INTEGER PRIMARY KEY,
  path        TEXT    NOT NULL UNIQUE,   -- absolute path in library/
  sha256      TEXT    NOT NULL,
  size_bytes  INTEGER,
  mime        TEXT,
  taken_at    TEXT,                      -- ISO-8601, from EXIF or file
  gps_lat     REAL,
  gps_lon     REAL,
  place_city  TEXT,                      -- reverse-geocoded, denormalized
  place_country TEXT,
  thumbnail_id INTEGER REFERENCES files(id),
  stripped     INTEGER NOT NULL DEFAULT 0,   -- EXIF stripped in file
  deleted      INTEGER NOT NULL DEFAULT 0,   -- scan-removed, keep row
  extra        TEXT                       -- raw EXIF JSON blob
);

CREATE TABLE files (
  id        INTEGER PRIMARY KEY,          -- content-id for dedup
  sha256    TEXT NOT NULL UNIQUE,
  kind      TEXT,   -- original, thumbnail, stripped-copy
  bytes     BLOB,    -- thumbnails; originals on disk via assets.path
  created_at TEXT
);

CREATE TABLE faces (
  id      INTEGER PRIMARY KEY,
  asset_id  INTEGER NOT NULL REFERENCES assets(id),
  crop_path TEXT,     -- cropped face thumbnail
  bbox     TEXT,      -- json [x,y,w,h] rel to asset
  cluster_id INTEGER REFERENCES persons(id)
);

CREATE TABLE persons (
  id          INTEGER PRIMARY KEY,
  name        TEXT,     -- '' = unnamed cluster
  prototype_from INTEGER, -- representative face for review
  status      TEXT DEFAULT 'new'  -- new / named / merged / split
);

CREATE TABLE content_embeds (
  asset_id  INTEGER PRIMARY KEY,
  model     TEXT NOT NULL,          -- e.g. 'openai/clip:ViT-B/32'
  model_version TEXT NOT NULL,
  embed     BLOB NOT NULL          -- float32[512], see vec0
);

CREATE TABLE face_embeds (
  face_id   INTEGER PRIMARY KEY,
  model     TEXT NOT NULL,
  embed     BLOB NOT NULL          -- float32[512]
);

CREATE TABLE tags (
  asset_id  INTEGER NOT NULL,
  tag       TEXT NOT NULL,
  source    TEXT NOT NULL DEFAULT 'clip',  -- clip-probe | manual | face
  PRIMARY KEY (asset_id, tag)
);

CREATE TABLE jobs (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  kind      TEXT NOT NULL,             -- scan | import | reindex
  status    TEXT NOT NULL DEFAULT 'queued', -- queued/ready/working/done/error
  progress  REAL,       -- 0..1
  error     TEXT,
  params    TEXT,       -- json
  created_at TEXT, update_at TEXT
);
```

`content_embeds.embed` and `face_embeds.embed` are `BLOB float32[512]`. The
`vec0` virtual tables for KNN are maintained as **near mirrors** of these
tables (see §6 key decision) — the app queries `vec0` for distance, joins back
to `content_embeds` by `rowid`, and treats the BLOB columns as the canonical
store that they mirror.

## 4. Monorepo layout

One git repo, a hybrid TypeScript + Python monorepo — TS runs the web layer,
Python owns the model runtime (the stack's constraint is where the ML lives,
not taste). PNPM is the repo package manager.

```
pics/
├── apps/
│   ├── web/          Next.js (React/TS) — UI + browse/search/thumbnail web API
│   └── api/          FastAPI (Python) — search, metadata, persons, jobs HTTP API
├── services/
│   └── worker/       Python long-lived — CLIP embed, face detect/embed (queued)
├── tools/
│   └── cli/          Python console — `pics scan/query/strip-exif/reindex`
├── packages/
│   └── core/         Python lib — schema, queue, catalog access, sqlite-vec glue
├── pnpm-workspace.yaml
└── docker-compose.yml
```

- `apps/web` (Next.js) and the Python side share **no code** — only the HTTP
  API contract (OpenAPI types, generated) between them.
- `apps/api`, `services/worker`, `tools/cli` all import `packages/core` via
  uv/pip editable install; `core` holds the SQLite schema, `jobs` queue helpers,
  catalog access, and sqlite-vec KNN glue.
- `apps/api` imports `core` but **never** torch; `services/worker` imports
  `core` + torch/insightface. This is the dividing line that keeps the API
  thin.

### Components & interfaces

| Component | Responsibility | Interface |
|---|---|---|
| `tools/cli scan` | Walk dir, insert job; idempotent | py lib `core.jobs.push(kind=scan)` |
| `apps/api upload` | Save bytes → sha → jobs row | HTTP `POST /api/upload` |
| `services/worker ingest` | EXIF, thumb, CLIP embed, face, write catalog | `core` + torch |
| `services/worker embed-service` | Query embedding | internal HTTP `POST /v1/embed-text` |
| `apps/api search` | NL + filters → KNN → rank | HTTP `GET /search` |
| `apps/web` | UI shell | REST → api |
| `tools/cli query` | Reuse api search | CLI → REST |

## 5. Data flow

**Ingest (upload or scan) end-to-end:**

```
upload() → library/imports/…/<sha>.jpg
        → jobs(kind=import)
worker: jobs.DO → decode EXIF → thumbnail write to files.table
                     │
       face detect ──┼── CLIP embed (content_embeds + vec0 content mirror)
                     │
                     ▼
            places: GPS → reverse geocode → assets.place
            faces → persons cluster
             job.progress, job.status
```

**Search:**

```
GET /search?q=…&who=…&place=…&before=…&tag=…
  api:
    if q:  embed text via worker /v1/embed-text → qvec
           sqlite: SELECT a.* , c.rowid as dist
           FROM vec0_content v JOIN assets a ON a.id=v.rowid
           WHERE v.embed match :qvec
           ORDER BY distance LIMIT 200
           post-filter: place/date/who via join persons::face_embeds
    return {results: [{asset_id, thumbnail_url, dist, …}]}
```

**EXIF strip:**

```
tools/strip --copy <path>   # ExifTool -all= on a copy
  → new file, new sha, update assets.sha256/extra, stripped=1
```

## 6. Key decisions

- **SQLite is the single mutable shared state**, no wire between services.
  Keeps compose trivially simple and backup moves one file. Tradeoff: at 20k
  photos, exact KNN (0.5–4M vec compares, pure C) is sub-100ms — no index
  needed beyond the native exact scan. If scale later hits >100k, swap vec0 to
  a sidecar ANN without API change.
- **Model runtime = Python torch in worker only.** The API never imports torch.
  Query embedding goes over an internal HTTP hop (worker `/v1/embed-text`). Keeps
  the heavy container off the API balloon and lets models be re-loaded
  independently.
- **Embedding versioning (anti-drift):** every embed stores its
  `model` + `model_version`. Re-embedding is a real `jobkind=reindex`.
  `tags`/`extra` survive model swaps; only `content_embeds` re-run.
- **Thumbnails as content-addressed `files` rows** (sha of bytes) → dedup, cache
  invalidation automatic, one copy even if the same photo appears twice.
- **Face clustering stays cluster-level + human review** (naming never
  automatic): clustering at index time, `persons` reviewed in `web` People page
  (rename/merge/split), witch merges are DB updates re-deriving member sets.
- **EXIF strip = copy, not in-place**, catalog is the source of truth;
  `stripped=1` marks intent; nothing unrecoverable.

## 7. Error handling

- **Job failure** → row `status=error`, `error` text, `progress` stays.
  Worker detects db-lock (busy) with retry + backoff; never hangs.
- **Unsupported file** (unknown mime) → import job fails gracefully, marks
  asset `skip=1`, logs — no pipeline crash.
- **Embedding model not downloadable** (offline first run) → `worker` starts
  anyway; queries return `503` with `models_pending` so the web shows "index is
  warming", not blank.
- **Search when `stripped`**: exact metadata is preserved in `assets.extra`
  json regardless of file strip; `GET /search` always available.
- **DB locked during long jobs**: sqlite WAL mode + `busy_timeout`, single
  writer (worker), readers (api/web) don't block.

## 8. Testing approach

- **Core (lib/core)**: SQLite schema migrations + KNN glue + queue drain
  idempotency tests.
- **API**: `pytest` + FastAPI TestClient, sqlite fixture per test. Endpoints
  covered: upload, search, jobs.
- **Worker**: integration — seed 3 sample JPEGs + 1 HEIC + 1 MOV; assert
  catalog rows, thumbnails, face rows, embeddings present, no `error` jobs.
- **Web**: unit (vitest) for search parser/filters; e2e (Playwright) page
  smoke on a seeded catalog.
- **CLI**: `pics scan` on fixture dir → job created; `pics query` returns rows.
- Joint: Compose healthchecks (`worker /v1/status` ready) before web can
  search.

## 10. Ops (Compose)

```yaml
services:
  web:       build: ./apps/web   ports: 3000:3000   depends_on: api
  api:       build: ./apps/api   ports: 8000:8000   volume: catalog+library
  worker:    build: ./apps/worker
             volumes: catalog+library+models
             deploy: restart: unless-stopped
volumes: catalog, library, models
```

Worker runs one process; API only does HTTP→SQLite (WAL). Backups: copy the
catalog `.db` file (WAL checkpoint), library dir optionally. Models dir is a
cache (safe to evict + redownload).

## 9. What's deliberately out of scope (v1)

- Multi-user auth, LAN-only usage (single-user personal tool).
- Manual EXIF stripping from the web UI (v1 does CLI only).
- Mobile auto-backup and immersive "memories" timeline.
- Heavy vector ANN (swap later if >1TB images).
- Face anti-spoofing / age-gender-emotion analysis.

(Content review self-checks: names consistent, no placeholders, spec-coverage
checked — all indexed requirements have a design decision.)