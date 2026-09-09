# Photo Searchable Library

Self-hosted photo search for metadata, natural-language image search, places,
and people. The repository is a TypeScript and Python monorepo:

- `apps/web`: Next.js UI
- `apps/api`: FastAPI HTTP API
- `services/worker`: metadata and ML processing worker
- `tools/cli`: `pics` command-line tools
- `packages/core`: shared Python catalog and SQLite functionality

## Development

Python services require Python 3.12 and `uv`. The worker also requires the
`exiftool` and `ffmpeg` binaries.

```bash
pnpm install
uv sync --project packages/core
pnpm web
```

Runtime data belongs outside version control: `catalog.db`, `library/`, and
`models/` are ignored by Git.
