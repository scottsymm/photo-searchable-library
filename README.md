# Photo Searchable Library

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A private, self-hosted, searchable photo library. Import photos from a mounted
folder, direct uploads, or Apple Photos (macOS), then find them by **what
happened, who was there, where, or when** — without sending anything to a cloud
service.

Next.js 16 · FastAPI · SQLite + sqlite-vec · Python worker (CLIP + InsightFace) ·
Swift Apple Photos bridge · Turborepo + uv workspaces

---

## Table of Contents

- [What's implemented](#whats-implemented)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Getting photos in](#getting-photos-in)
- [Search, places, and people](#search-places-and-people)
- [Apple Photos bridge](#apple-photos-bridge)
- [Configuration](#configuration)
- [API routes](#api-routes)
- [Local development](#local-development)
- [Data, volumes & backups](#data-volumes--backups)
- [Project layout](#project-layout)
- [Quality gates](#quality-gates)
- [Roadmap & limitations](#roadmap--limitations)
- [License](#license)

---

## What's implemented

| Area | Delivered |
|---|---|
| Search | CLIP semantic search plus `who`, `place`, `before`, `after`, `tag` structured filters |
| Catalog | Asset funnel, per-source overview, recent imports, faces/places context |
| Ingest | Direct upload, mounted-folder scan/watch, Apple Photos bounded + full sync |
| Faces & people | InsightFace detection, DBSCAN clustering, confirm/reject/restore/merge/split |
| Places | Reverse-geocoded city/country aggregation |
| CLI | `scan`, `query`, `upload`, `strip-exif`, `cluster`, `people` |
| Apple Photos | `/sources/apple-photos/*` HTTP contract, sync state machine, heartbeat lease |

**Not yet built:** authentication, multi-user, and a production deployment
story. See [Roadmap & limitations](#roadmap--limitations).

---

## Architecture

```text
Browser / HTTP clients
        │
        ▼
Next.js web app (host :3001 / container :3000)
        │  /  /photos  /people  /places  /settings
        ▼
FastAPI API (:8000)
  catalog, search, uploads, jobs, admin, persons, places,
  apple-photos source endpoints
        │
        ▼
shared SQLite catalog + library volume
  (sqlite-vec content/face vectors)

Python worker (internal :9090)
  CLIP embeddings · EXIF/media processing · face detection ·
  job loop · mounted-folder watcher
        ▲
        │
Swift PhotoKit bridge (macOS host process)
  reads the macOS Photos library over HTTP
```

Three processes, three ownerships:

- **The API owns the catalog contract**: it serves the web UI, receives
  uploads, exposes search/jobs/admin/persons/places, and tracks sources.
- **The worker is the engine**: it loads CLIP + InsightFace weights, processes
  files, runs the job loop, and watches the mount. It is not a separate ML
  "sidecar" — the embed API (`:9090`) runs inside the same process.
- **The Swift bridge owns macOS Photos access**: it uses PhotoKit (never
  `Photos Library.photoslibrary`) and pushes assets into the API over HTTP. It
  has no database and no knowledge of the catalog internals.

<details>
<summary><strong>Why is the worker one combined process?</strong></summary>

The worker container runs the CLIP embed API, the SQLite job loop, InsightFace
face detection, and the mounted-folder watcher in a single Python process. This
keeps model weights loaded once and shared across all work — which is why the
`models` volume belongs to the worker alone.

</details>

<details>
<summary><strong>sqlite-vec & vector search</strong></summary>

CLIP embeddings are 512-dimensional float32 vectors stored in the shared SQLite
catalog. `packages/core` creates two sqlite-vec virtual tables:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS vec0_content USING vec0(content_embed float[512]);
CREATE VIRTUAL TABLE IF NOT EXISTS vec0_face    USING vec0(face_embed float[512]);
```

The extension is loaded on **every** SQLite connection (`sqlite_vec.load` in
`core/conn.py`). Rows use `rowid = asset_id` (content) or `rowid = face_id`
(faces), and search runs KNN `MATCH ... AND k = ?` queries.

</details>

<details>
<summary><strong>Data ownership boundaries</strong></summary>

| Process | Owns | Never touches |
|---|---|---|
| API | Catalog DB, library files, jobs, people, sources | Model weights, Photos internals |
| Worker | Model weights, inference, processing jobs | Photos internals; no separate database |
| Swift bridge | macOS Photos access | The catalog; it only speaks HTTP |

The worker and bridge are both replaceable without touching the catalog — the
contracts are HTTP (`/v1/*` and `/sources/apple-photos/*` respectively).

</details>

---

## Quick start

The default path is the containerized stack.

### Prerequisites

- Docker Desktop with Compose
- A directory of photos to scan (defaults to `~/Pictures`, mounted read-only)
- ~4 GB for the worker image and model cache
- Network access on the first worker start (CLIP and InsightFace weights)

### Run it

```bash
docker compose up --build
```

The API waits on the worker health gate (`/v1/status`). The first start can take
several minutes while the worker downloads models into the `models` volume;
later starts reuse them.

Open:

- Web UI: <http://localhost:3001>
- API health: <http://localhost:8000/>

### Useful commands

```bash
docker compose ps
docker compose logs -f worker
docker compose down            # stop, keep catalog/library/models
docker compose down -v         # also delete all local runtime data
```

To use a different host photo directory:

```bash
docker compose down
PICS_MOUNT_SOURCE=/Volumes/Backup/Photos docker compose up --build
```

The host directory is mounted **read-only** and can only be changed at container
startup, not from the UI.

<details>
<summary><strong>Why the web app is on :3001</strong></summary>

The web container listens on `:3000` internally, but Compose publishes host
port `3001` by default (`PICS_WEB_PORT`) so this project can run alongside the
Rails project that uses host port `3000`. The API's CORS configuration allows
the configured web origin.

</details>

---

## Getting photos in

| Path | Who it's for | How |
|---|---|---|
| **Mounted-folder scan/watch** | Any OS | A host directory is mounted read-only at `/media/photos`; the worker watches it |
| **Direct upload** | Any OS | Upload a file, or a whole directory, into the library |
| **Apple Photos bridge** | macOS users | Sync from your existing Photos library; see below |

Supported files: `.jpg`, `.jpeg`, `.png`, `.heic`, `.heif`, `.mov`, `.mp4`,
`.avif`, `.dng`. Originals are never modified.

### Upload one file

```bash
curl -F 'file=@/path/to/photo.heic' http://localhost:8000/assets/upload
```

### Upload a directory

```bash
uv run --package pics-cli pics upload "$HOME/Pictures"
```

### Queue a local scan (no HTTP API needed)

`pics scan` walks a directory and queues paths directly in the configured local
SQLite catalog:

```bash
PICS_DB=/path/to/catalog.db uv run --package pics-cli pics scan "$HOME/Pictures"
```

### Watch jobs

```bash
curl http://localhost:8000/jobs
curl http://localhost:8000/jobs/1
```

---

## Search, places, and people

Natural-language search is available once the worker has generated CLIP
embeddings. Structured filters: `who:`, `place:`, `before:`, `after:`, `tag:`.

Web pages: `/` (search), `/photos` (catalog + sources), `/places`, `/people`.

```bash
curl 'http://localhost:8000/search?q=birthday%20cake&limit=20'
curl 'http://localhost:8000/search?q=beach&who=Sam&before=2020'
uv run --package pics-cli pics query "birthday cake"
```

### Face clustering

After photos are indexed, queue conservative face clustering:

```bash
uv run --package pics-cli pics cluster --eps 0.30 --min-samples 3
```

Clusters are **suggestions**. Confirmed person links are kept separately from
ML assignments, so rerunning clustering never erases user decisions. Review and
confirm suggestions on the People page (`/people`).

---

## Apple Photos bridge

On macOS, the bridge is the easiest way to import an existing Photos library.
It is a native Swift CLI in `apps/photos-bridge` that uses PhotoKit and speaks
HTTP to the API.

```bash
pnpm bridge:build
pnpm bridge:dry-run       # preview what PhotoKit sees; import nothing
pnpm bridge:sync          # import the latest 25 assets
pnpm bridge:watch         # keep the bridge ready for UI-triggered imports
```

The first run asks macOS for Photos access. The Photos page (`/photos`) offers a
bounded recent sync and a **full sync** that checks stable Apple asset IDs and
uploads only missing assets. The bridge targets `http://localhost:8000` by
default; override with `--api-url`.

<details>
<summary><strong>Bridge protocol (for the curious)</strong></summary>

The API contract lives at `/sources/apple-photos/*`:

- `POST /sources/apple-photos/sync` — request a batch (`limit`, `full`)
- `POST /sources/apple-photos/sync/claim` — claim the next queued sync
- `POST /sources/apple-photos/sync/:id/complete` — report imported/failed/error
- `POST /sources/apple-photos/bridge/heartbeat` — authorization + asset count
- `POST /sources/apple-photos/assets/known` — which `source_asset_id`s exist
- `POST /sources/apple-photos/assets` — multipart upload
- `GET /sources/apple-photos/status` · `GET /sources/apple-photos/sync/status` — state

`source_asset_id` contains `/`, so it travels as a **form field**, never a route
segment. Full sync enumerates the PhotoKit library in chunks, asks the API which
stable `PHAsset.localIdentifier` values are already present, and uploads only
missing assets.

</details>

---

## Configuration

Environment variables read by the API, worker, CLI, and Compose:

| Variable | Default | Purpose |
|---|---|---|
| `PICS_DB` | `catalog.db` | SQLite catalog path |
| `PICS_LIBRARY` | `library` | Imported originals, uploads, crops |
| `PICS_WORKER_URL` | `http://localhost:9090` | Worker embed API (used by the API) |
| `PICS_EMBED_PORT` | `9090` | Port the worker embed API listens on |
| `PICS_MODEL` | `openai/clip-vit-base-patch32` | Hugging Face CLIP model |
| `PICS_MODEL_VERSION` | `clip-vit-base-patch32-v1` | Version recorded with embeddings |
| `PICS_FACE_MODEL` | `buffalo_l` | InsightFace model |
| `PICS_WATCH_ROOT` | `/media/photos` | Directory watched by the worker |
| `PICS_WATCHER_ENABLED` | `1` | Enable the mounted-folder watcher |
| `PICS_WATCH_POLL_SECONDS` | `30` | Watcher poll interval |
| `PICS_INVENTORY_CACHE_TTL` | `60` | Watch-root inventory cache TTL (seconds) |
| `PICS_API` | `http://localhost:8000` | API URL used by the CLI |
| `PICS_WEB_PORT` | `3001` | Host port for the web container |
| `PICS_MOUNT_SOURCE` | `~/Pictures` | Host directory mounted read-only (Compose) |
| `HF_HOME` | `/models/huggingface` | CLIP model cache (worker) |
| `INSIGHTFACE_ROOT` | `/models/insightface` | InsightFace model cache (worker) |

Docker Compose pins `PICS_DB=/data/catalog.db`, `PICS_LIBRARY=/library`, and the
model cache paths inside the `models` volume.

---

## API routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | API health |
| `GET` | `/search` | Semantic + structured search (`q`, `who`, `place`, `before`, `after`, `tag`, `limit`) |
| `GET` | `/catalog/overview` | Asset funnel, context, sources, sync state |
| `POST` | `/assets/upload` | Upload an asset |
| `GET` | `/assets/:id/thumbnail` | Thumbnail for an asset |
| `GET` | `/jobs` · `/jobs/:id` | List / show jobs |
| `GET` | `/admin/status` · `/admin/settings` | Settings and status |
| `PATCH` | `/admin/settings` | Update settings |
| `GET` | `/admin/library` | Inventory walk + catalog counts |
| `POST` | `/admin/scan` | Queue a scan of the watch root |
| `GET` | `/persons` · `/persons/search` | People index / picker search |
| `POST` | `/persons/cluster` | Run face clustering |
| `PATCH` | `/persons/:id` | Rename a person |
| `POST` | `/persons/:id/aliases` · `DELETE /persons/:id/aliases/:alias_id` | Manage aliases |
| `POST` | `/persons/:id/merge/:remove_id` | Merge two people |
| `POST` | `/persons/:id/split` | Split faces into a new person |
| `POST` | `/persons/:id/faces/:face_id` | Assign a face to a person |
| `POST` | `/persons/suggestions/:id/confirm` · `/reject` · `/restore` | Review cluster suggestions |
| `GET` | `/persons/faces/:face_id/crop` | Serve a face crop |
| `GET` | `/places` | Aggregated city/country index |
| `POST` | `/sources/apple-photos/sync` · `/sync/claim` · `/sync/:id/complete` | Sync state machine |
| `POST` | `/sources/apple-photos/bridge/heartbeat` | Bridge heartbeat |
| `POST` | `/sources/apple-photos/assets/known` · `/assets` | Dedupe + bridge upload |
| `GET` | `/sources/apple-photos/status` · `/sync/status` | Source and sync state |

Internal worker endpoints (`:9090`, not the public API): `GET /v1/status`,
`POST /v1/embed-text`.

---

## Local development

### Prerequisites

- Python 3.12 and `uv`
- Node.js and `pnpm`
- `exiftool` and `ffmpeg` for worker media processing

```bash
brew install exiftool ffmpeg
uv sync --all-packages
pnpm install
```

### Run the web app alone

```bash
pnpm dev
```

`pnpm dev` runs **only** the Next.js web app. Point it at a running API with
`NEXT_PUBLIC_PICS_API_URL`.

### Run the whole stack with live reload

```bash
pnpm dev:docker
```

Compose Watch syncs `apps/web`, `apps/api`, and `packages/core` into their
containers with hot reload, and rebuilds when dependency files or development
Dockerfiles change. The worker keeps the regular image because its model

### Run a task for one package

```bash
pnpm turbo run test --filter=web
uv run --package pics-api --extra dev pytest apps/api/tests
uv run --package pics-worker --extra dev pytest services/worker/tests
```

### CLI against a non-default catalog/API

```bash
PICS_DB=/path/to/catalog.db PICS_API=http://localhost:8000 \
  uv run --package pics-cli pics query "birthday cake"
```

---

## Data, volumes & backups

- `catalog` volume — the shared SQLite catalog
- `library` volume — imported originals, uploads, crops
- `models` volume — downloaded model weights

Back up the catalog and library volumes together; they are the source of truth.
`docker compose down` preserves all three; `docker compose down -v` deletes

---

## Project layout

```text
apps/web/             Next.js web UI (search, photos, people, places, settings)
apps/api/             FastAPI API (catalog, search, uploads, jobs, admin, persons, sources)
apps/photos-bridge/   Swift PhotoKit bridge (macOS)
services/worker/      Python worker (embed API, jobs, faces, watcher)
packages/core/        Shared Python catalog, schema, SQLite/sqlite-vec
tools/cli/            pics command-line tools
artifacts/            Discovery and implementation planning documents
```

Python package graph:

```text
pics-core
  ├── pics-api
  ├── pics-worker
  └── pics-cli
```

Generated virtual environments, `.next`, `.turbo`, model files, databases, and
runtime libraries are not source or build artifacts.

---

## Quality gates

```bash
uv lock --check
pnpm check           # uv lock --check + web typecheck
pnpm test            # all Python suites + web tests
pnpm build           # web + package builds
docker compose config
```

CI (`.github/workflows/ci.yml`) runs the core/worker/API Python suites,
`pics --help`, web tests, web production build, and `docker compose config`.
Root `pnpm test`/`build` use package filters so they target the actual workspace
packages rather than the synthetic root `uv` workspace package.

---

## Roadmap & limitations

Done: see [What's implemented](#whats-implemented).

Planned / not built:

- **Authentication & multi-user** — everything is designed for one user on
  their own machine.
- **Production deployment** — there is no deploy story; Docker Compose is the
  only run path.
- **Apple albums & People** — the bridge imports assets; album and Apple People
  import are deferred.

Tradeoffs worth knowing:

- SQLite is the database — great for a single-user local library; a
  multi-user server would want PostgreSQL.
- The worker downloads models on first real-mode boot (several minutes).
- The web app uses host port `3001` by default so it can coexist with the Rails
  project on `:3000`.

---

## License

This project is licensed under the [MIT License](LICENSE).
