# Photo Searchable Library

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

- Web UI: <http://localhost:3000>
- API health: <http://localhost:8000/>

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
pnpm dev:all
```

Run the workspace checks, tests, and builds through Turborepo:

```bash
pnpm check:all
pnpm test:all
pnpm build:all
```

Python workspace discovery and task integration use Turborepo's experimental
`uv` workspace support. Direct `uv` commands remain available for package-level
work and troubleshooting.

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
