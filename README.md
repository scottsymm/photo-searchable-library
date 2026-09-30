# Photo Searchable Library

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Self-hosted photo search for metadata, natural-language image search, places,
and people. The repository is a TypeScript and Python monorepo:

- `apps/web`: Next.js UI
- `apps/api`: FastAPI HTTP API
- `services/worker`: metadata and ML processing worker
- `tools/cli`: `pics` command-line tools
- `packages/core`: shared Python catalog and SQLite functionality

## Docker Quickstart

Requirements:

- Docker Desktop with Compose
- Approximately 4 GB available for the worker image and model cache
- Network access on the first worker start so CLIP and InsightFace weights can
  be downloaded

Start the stack from the repository root:

```bash
docker compose up --build
```

Open:

- Web UI: <http://localhost:3001>
- API health: <http://localhost:8000/>

The web container listens on port 3000 internally, but this project uses host
port 3001 so it can run alongside the Rails project using host port 3000:

```bash
docker compose up --build
```

The web UI is available at <http://localhost:3001>. To override this host port
for another setup, set `PICS_WEB_PORT` before starting Compose.

The worker is intentionally gated by a health check. The first start can take
several minutes while it downloads the CLIP and InsightFace models. The model
files are stored in the Compose `models` volume and are reused on later starts.

Check service state:

```bash
docker compose ps
docker compose logs -f worker
```

Stop the services without deleting the catalog, photos, or model cache:

```bash
docker compose down
```

To delete all local runtime data as well, including indexed photos and model
weights:

```bash
docker compose down -v
```

## Index Photos

The Docker stack stores imported files in the Compose `library` volume. Upload
one file through the API:

```bash
curl -F 'file=@/path/to/photo.heic' http://localhost:8000/assets/upload
```

For a directory, install the CLI dependencies locally and use `pics upload`:

```bash
uv run --package pics-cli pics upload "$HOME/Pictures"
```

The command uploads supported `.jpg`, `.jpeg`, `.png`, `.heic`, `.heif`, `.mov`,
`.mp4`, `.avif`, and `.dng` files through the API. It does not modify the
original files.

The Admin page at <http://localhost:3000/settings> starts parked. It shows the
current mounted Pictures path and controls whether watching is enabled. The
default mount is `$HOME/Pictures`; watching is off until you enable it in the
Admin page. You can choose whether an enable action backfills existing files or
only watches new files.

To use a different host directory, set `PICS_MOUNT_SOURCE` before starting
Compose:

```bash
docker compose down
PICS_MOUNT_SOURCE=/Volumes/Backup/Photos docker compose up --build
```

The mount point cannot be changed from the UI because Docker establishes it at
container startup. The UI controls the runtime watch state and all processing
jobs. Manual upload remains available while watch is paused.

Monitor jobs:

```bash
curl http://localhost:8000/jobs
curl http://localhost:8000/jobs/1
```

## Apple Photos Bridge

Apple Photos libraries are application-managed packages. Do not rely on Docker
traversing `Photos Library.photoslibrary`; use the native macOS bridge instead.

Build the bridge:

```bash
cd apps/photos-bridge
swift build
```

Preview what PhotoKit can see without importing:

```bash
swift run PicsPhotosBridge --dry-run --limit 25
```

Import a bounded batch into the local API:

```bash
swift run PicsPhotosBridge --limit 25
```

For UI-triggered imports, keep the local bridge watching for requests:

```bash
pnpm bridge:watch
```

The Photos page offers both a bounded recent sync and a **Full sync**. Full
sync enumerates the entire PhotoKit library but asks the API which stable Apple
asset IDs are already present, so it uploads only missing assets.

The first run asks macOS for Photos access. Phase 1 imports primary image and
video resources with stable Apple asset identifiers. Albums, Apple People,
edits, deletion propagation, and background scheduling are deferred.

## Search

Use the web UI or the API:

```bash
curl 'http://localhost:8000/search?q=birthday%20cake&limit=20'
curl 'http://localhost:8000/search?q=beach&who=Sam&before=2020'
```

Natural-language search is available after the worker has generated CLIP
embeddings. Search can also use `who`, `place`, `before`, `after`, and `tag`
filters.

## Face Clustering

After photos have been indexed, queue conservative face clustering:

```bash
uv run --package pics-cli pics cluster --eps 0.30 --min-samples 3
```

The CLI command targets the local `catalog.db` by default. For the Docker
catalog, queue the same operation from the People page or API once the cluster
endpoint is exposed to the UI. Review suggestions at <http://localhost:3000/people>.

Clusters are suggestions. Confirmed person links are kept separately from ML
assignments so rerunning clustering cannot erase user decisions.

## Local Python Development

Python services require Python 3.12 and `uv`. The worker also requires the
`exiftool` and `ffmpeg` binaries.

```bash
brew install exiftool ffmpeg
uv sync --all-packages
```

Run the web app locally:

```bash
pnpm install
pnpm dev
```

For Docker-based development with automatic source syncing and reloads, use the
development Compose override:

```bash
pnpm dev:docker
```

The web app runs with `next dev`, and the API runs with Uvicorn reload enabled.
Changes under `apps/web`, `apps/api`, and `packages/core` are synced into their
containers. Changes to dependency files or development Dockerfiles trigger a
container rebuild. The worker continues to use the regular image because its
model environment is expensive to rebuild.

Run the workspace checks, tests, and builds through Turborepo:

```bash
pnpm check
pnpm test
pnpm build
```

## Repository Tooling

Turborepo orchestrates the TypeScript and Python workspace tasks. Python
workspace discovery uses Turborepo's experimental `uv` workspace support.
The Python package graph is:

```text
pics-core
  ├── pics-api
  ├── pics-worker
  └── pics-cli
```

The root commands use package filters so `test` and `build` target the actual
workspace packages rather than the synthetic root `uv` workspace package:

```bash
pnpm dev
pnpm check
pnpm test
pnpm build
```

Run a task for one package with Turbo or use the underlying tool directly:

```bash
pnpm turbo run test --filter=web
uv run --package pics-api --extra dev pytest apps/api/tests
pnpm --dir apps/web test
```

Turborepo handles local task orchestration and caching. Docker Compose remains
responsible for building and running the API, worker, and web services together.
Virtual environments, `.turbo/`, model files, and runtime data are not source
or build artifacts and are excluded from version control.

Runtime data belongs outside version control: `catalog.db`, `library/`, and
`models/` are ignored by Git. Local CLI commands use `PICS_DB` and `PICS_API`:

```bash
PICS_DB=/path/to/catalog.db PICS_API=http://localhost:8000 \
  uv run --package pics-cli pics query "birthday cake"
```

## Verification

```bash
uv lock --check
uv run --frozen --package pics-core --extra dev pytest packages/core/tests
uv run --frozen --package pics-worker --extra dev pytest services/worker/tests
uv run --frozen --package pics-api --extra dev pytest apps/api/tests
pnpm turbo run test --filter=web
pnpm turbo run build --filter=web
docker compose config
```

## License

This project is licensed under the [MIT License](LICENSE).
