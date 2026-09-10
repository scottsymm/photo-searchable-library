---
title: Admin and Ingest Automation — Technical Design
tags:
  - design
  - admin-and-ingest-automation
  - admin
  - ingest
  - watch
  - self-hosted
keywords:
  - admin settings
  - watch folder
  - backfill
  - polling watcher
  - docker mount
  - no silent processing
  - job status
created: 2026-09-10
updated: 2026-09-10
---

# Admin and Ingest Automation — Design (v1)

## 0. Approval trail

- **Approach chosen:** Settings table + in-worker watcher thread (Approach A).
- Decisions from tech-incept interrogation:
  - **Watch mechanism:** polling thread in the worker (`watchdog` not used).
  - **Reindex:** deferred; "Embed/Index" = rescan + job history + status only.
  - **Settings storage:** Pictures path in **env**; runtime toggles in a SQLite
    `settings` table.
  - **Parked gating:** global ingest flag; manual scan always available; search
    and upload unaffected; notice banner.

## 1. Architecture overview

The existing single-worker + SQLite queue model is preserved. A new settings
table holds **runtime toggles** the admin controls live; the **mount path stays
in environment** because Docker must know it at container start.

```
worker ── main loop (queue drain)         api ── REST endpoints     web ── pages
  │            ▲                                     │                    │
  └── watcher thread (only when                     settings ─────────────┘
      watch_enabled)                                (catalog.db)
              │
              └── polls PICS_WATCH_ROOT → new files (by sha) → scan job
```

- **Settings source of truth split:**
  - `PICS_WATCH_ROOT` (container path, default `/media/photos`) is an env var
    baked into Compose, displayed by the admin page, and documented for restart.
  - `settings.watch_enabled` and `settings.watch_backfill` live in the catalog
    so the admin can flip them at runtime with no container change.

- **No silent processing:** the worker's watcher thread does not start until
  `watch_enabled` is observed. A fresh install defaults to `watch_enabled=0`
  and `watch_backfill='prompt'`, so nothing reads the library until the admin
  chooses.

## 2. Components

### 2.1 `packages/core/core/settings.py` (new)

Typed access to the `settings` table.

- `get(conn, key, default=None) -> str`
- `set(conn, key, value) -> None`
- `get_all(conn) -> dict[str, str]`
- Seeds default rows on schema migration: `watch_enabled=0`,
  `watch_backfill=prompt`, `seed_version=1`.

### 2.2 `packages/core/core/schema.py` (modify)

Add:

```sql
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Bump `schema_meta.version` to `3`.

### 2.3 `services/worker/worker/watcher.py` (new)

A polling thread.

- Reads `PICS_WATCH_ROOT` (env) once.
- Loop:
  - Read `settings.watch_enabled`.
  - If `0`, sleep and continue (no filesystem access).
  - If `1`, `os.walk` the root; compute `sha256` of candidate media files
    (reuse `core.assets.sha256_file`), and compare with an in-memory set of
    already-queued keys plus the catalog `files.sha256`.
  - New files → `jobs.push(conn, "scan", {"paths": [abs_path]})` with a modest
    batch size.
  - Track a bounded LRU of recently queued hashes to avoid re-enqueue.
  - Sleep `PICS_WATCH_POLL_SECONDS` (default 30) between passes.
- Backfill: when `watch_backfill=backfill`, first pass treats all existing files
  under root as new (set `watch_backfill=done` after enqueue). When
  `watch_backfill=prompt`, the admin page decides; the watcher only sees an
  explicit `scan` job.
- Terminates on a stop event (for tests).

### 2.4 `services/worker/worker/service.py` (modify)

- Start `Watcher()` thread when `PICS_WATCHER_ENABLED=1` (default `1` in
  Docker; the watcher itself gates on the DB flag). Keep the embed API thread
  and drain loop unchanged.

### 2.5 `apps/api/api/admin.py` (new)

REST surface for the admin page.

- `GET /admin/status` — settings + worker state + catalog counts:
  - `watch_root` (from env), `watch_enabled`, `watch_backfill`,
  - `models_ready` (poll worker `/v1/status`),
  - `counts`: `{assets, faces, persons, jobs}`,
  - `disk`: shutil.disk_usage on the library/catalog volume.
- `GET /admin/settings` — current runtime settings.
- `PATCH /admin/settings` — accepts `watch_enabled` and/or `watch_backfill`
  (`prompt` | `backfill` | `done`). All writes go through `settings.set`.
- `POST /admin/scan` — body `{root?}`; always allowed, even when watch is off;
  enqueues a `scan` job over `root` (default env root). This is the *manual
  backfill / one-shot scan* path.

### 2.6 `apps/api/api/main.py` (modify)

Mount `admin` router at `/admin`. Keep `/jobs` and others as-is.

### 2.7 `apps/web/lib/api.ts`, `types.ts` (modify)

- `getAdminStatus()`, `getSettings()`, `updateSettings(...)`,
  `queueAdminScan(...)`.
- Types: `AdminStatus`, `AdminSettings`.

### 2.8 `apps/web/app/settings` — rename to `admin` (modify)

Reuse the existing `/settings` page as the admin page (nav already links
`Settings`); retitle to **Admin**:

- Watch/Ingest section: toggle `watch_enabled`, show `watch_root`, `PATCH`
  backfill mode (`prompt | backfill | done`) with the "backfill now" scan
  button wired to `POST /admin/scan`.
- Manual scan: `POST /admin/scan` (root from env).
- Embed/Index jobs: reuse existing `/jobs` list (start via scan; cancel/pause
  deferred).
- Clustering: reuse existing `queueClustering()` + `/persons` review.
- Status: counts, models-ready dot, disk usage, mount docs.

### 2.9 Banner (`apps/web/app/layout.tsx` / component)

- Fetch `/admin/status`.
- If `watch_enabled == '0'`, show a prominent fixed banner:
  "Photos are not being imported yet — configure ingest" with a link to
  `/settings`.
- Never block search or upload.

### 2.10 Compose (modify) + README

- Add bind mount `~/Pictures:/media/photos:ro` to `worker` (and `api` if it
  needs to serve originals later; for now worker only — API serves byte thumbs
  from `files`).
- Set `PICS_WATCH_ROOT=/media/photos`, `PICS_WATCHER_ENABLED=1`,
  `PICS_WATCH_POLL_SECONDS=30` on the worker.
- README: mirror the admin page's mount docs (how to change `PICS_WATCH_ROOT`
  in compose and restart; note that the mount is fixed at start).

## 3. Data model

`settings` table:

```sql
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Default rows (seeded at migrate):

| key | value |
|---|---|
| `watch_enabled` | `0` |
| `watch_backfill` | `prompt` |

`files.sha256` already exists and is the dedupe key for the watcher.

## 4. Data flow

**Manual scan (always allowed):**

```
admin POST /admin/scan {root} → jobs.push("scan", {paths}) → worker import → content
```

**Watch on (runtime):**

```
admin PATCH /admin/settings watch_enabled=1 → settings row
worker watcher thread (polls each 30s) →
  os.walk PICS_WATCH_ROOT → new sha → jobs.push("scan", batch)
```

**Backfill prompt flow:**

```
watcher sees watch_enabled=1 and watch_backfill=prompt →
  does NOT auto-enqueue; admin page shows "some photos exist, run backfill?"
  → POST /admin/scan (backfills) → worker imports → done
```

## 5. Key decisions

- **Settings in SQLite, path in env:** the path must exist before Docker
  starts; the toggles are live runtime state. This is the load-bearing decision
  and it matches the interview.
- **Polling, not `watchdog`:** no new dependency; content-addressed dedupe makes
  it idempotent; simpler and testable.
- **One `scan` job kind for both** manual + watch: the pipeline already handles
  `scan`/`import`; no new job kind needed.
- **Parked default is DB-seeded:** fresh install → `watch_enabled=0` →
  banner shows; nothing reads the library.
- **Dedupe via `files.sha256` + LRU:** prevents re-enqueue across passes and
  across restarts.

## 6. Error handling

- Watcher DB error → log and continue; never crash the worker.
- Root missing/unreadable (mount not present) → status reports
  `root_available: false`; admin page shows the warning; watching is idle.
- Poll iteration budget: if one pass exceeds the poll interval, skip sleeps
  until caught up rather than stacking threads.
- `PATCH /admin/settings` validates enum values; 422 otherwise.

## 7. Testing approach

- **Core:** `settings` get/set/seed tests; schema v3 migration idempotency.
- **Watcher:** unit tests with a temp dir and monkeypatched DB:
  - disabled → no filesystem walk,
  - enabled → enqueues new files once, not re-enqueued on next pass,
  - `watch_backfill=prompt` → nothing auto-enqueued; explicit scan path works.
- **API:** `pytest` + TestClient for `/admin/status`, `/admin/settings`,
  `/admin/scan` (root default, enum validation).
- **Web:** vitest for admin API client; `pnpm build` type-checks pages.
- **Compose:** `docker compose config` valid; README doc-only for mount path.

---

(Content review: settings path split matches interview; polling + deferred
reindex recorded; components named consistently; no placeholders.)