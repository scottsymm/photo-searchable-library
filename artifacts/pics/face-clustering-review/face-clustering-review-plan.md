# Face Clustering and Human Review — Implementation Plan

*Created: 2026-09-09*

**Goal:** Turn detected face embeddings into conservative anonymous clusters,
then let the user name, merge, split, confirm, reject, and manually assign
faces without losing decisions when clustering runs again.

**Architecture:** Add a versioned clustering job to the existing SQLite worker.
Each run writes algorithm suggestions to immutable run/assignment tables. Stable
`persons` and explicit `person_faces` links are user-owned state and are never
overwritten by a later clustering run. The People API exposes clusters and
review actions; the Next.js People page shows representative crops and source
photos.

**Spike source:** `artifacts/pics/face-clustering-review/face-clustering-review-spike.md`

**Starting algorithm:** DBSCAN with cosine distance, `eps=0.30`,
`min_samples=3` for high-confidence suggestions. A second candidate pass with
`min_samples=2` may be shown as review-only suggestions. Agglomerative
clustering is not the default because it produced mostly singleton clusters in
the real-photo sample.

## File Map

| File | Action | Responsibility |
|---|---|---|
| `packages/core/core/schema.py` | Modify | Schema v2: clustering runs, suggestions, assignments, durable person links |
| `packages/core/core/clustering.py` | Create | Load embeddings, run DBSCAN, persist suggestions and assignments |
| `packages/core/tests/test_clustering.py` | Create | Deterministic clustering and persistence tests |
| `services/worker/pyproject.toml` | Modify | Add scikit-learn dependency |
| `services/worker/worker/run.py` | Modify | Drain `cluster_faces` jobs |
| `services/worker/worker/pipeline.py` | Modify | Enqueue cluster job after imports when configured |
| `services/worker/tests/test_clustering.py` | Create | Worker job integration test with fake embeddings |
| `apps/api/api/persons.py` | Modify | Cluster listing, representative crops, confirm/merge/split/reject/manual assignment |
| `apps/api/api/jobs.py` | Modify | Expose clustering job creation/status |
| `apps/api/tests/test_persons.py` | Create | People review API tests |
| `apps/web/types.ts` | Modify | Cluster, face, and review action types |
| `apps/web/lib/api.ts` | Modify | People review API calls |
| `apps/web/app/people/page.tsx` | Replace | Cluster review UI with representative crops and actions |
| `apps/web/app/globals.css` | Modify | Face crop and review controls |
| `tools/cli/pics_cli/__main__.py` | Modify | Add `pics cluster` and `pics people` commands |
| `tools/cli/tests/test_clustering.py` | Create | CLI command tests |

## Tasks

### Task 1: Add schema v2 tables without overwriting user state

**Files:**
- Modify: `packages/core/core/schema.py`

- [ ] Add the following tables to `SCHEMA` using `CREATE TABLE IF NOT EXISTS`:

```sql
CREATE TABLE IF NOT EXISTS clustering_runs (
  id INTEGER PRIMARY KEY,
  model TEXT NOT NULL,
  model_version TEXT NOT NULL,
  algorithm TEXT NOT NULL,
  metric TEXT NOT NULL,
  eps REAL NOT NULL,
  min_samples INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'running',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at TEXT,
  error TEXT
);

CREATE TABLE IF NOT EXISTS cluster_suggestions (
  id INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL REFERENCES clustering_runs(id) ON DELETE CASCADE,
  cluster_key INTEGER NOT NULL,
  representative_face_id INTEGER REFERENCES faces(id),
  face_count INTEGER NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'candidate',
  status TEXT NOT NULL DEFAULT 'unreviewed',
  person_id INTEGER REFERENCES persons(id),
  UNIQUE(run_id, cluster_key)
);

CREATE TABLE IF NOT EXISTS face_assignments (
  id INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL REFERENCES clustering_runs(id) ON DELETE CASCADE,
  face_id INTEGER NOT NULL REFERENCES faces(id) ON DELETE CASCADE,
  suggestion_id INTEGER REFERENCES cluster_suggestions(id) ON DELETE CASCADE,
  distance REAL,
  status TEXT NOT NULL DEFAULT 'suggested',
  UNIQUE(run_id, face_id)
);

CREATE TABLE IF NOT EXISTS person_faces (
  person_id INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  face_id INTEGER NOT NULL REFERENCES faces(id) ON DELETE CASCADE,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(person_id, face_id)
);

CREATE INDEX IF NOT EXISTS face_assignments_face_idx ON face_assignments(face_id);
CREATE INDEX IF NOT EXISTS person_faces_face_idx ON person_faces(face_id);
```

- [ ] Bump the stored schema version from `1` to `2` only after the DDL has
  executed. The migration must be repeatable against an existing catalog.
- [ ] Keep `faces.cluster_id` temporarily for compatibility, but treat
  `person_faces` as the source of truth for confirmed identity links.

- [ ] **Verify**

Run: `uv run --project packages/core pytest packages/core/tests`
Expected: existing tests pass and a fresh database contains all v2 tables.

### Task 2: Add the clustering engine

**Files:**
- Create: `packages/core/core/clustering.py`
- Modify: `services/worker/pyproject.toml`

- [ ] Add `scikit-learn>=1.5` to worker dependencies.
- [ ] Implement `run_clustering(conn, model, model_version, eps=0.30,
  min_samples=3) -> int`:
  - Load `face_embeds.embed` joined to face IDs in stable ascending ID order.
  - Decode each float32 blob with the same helper used by `core.embeds`.
  - Create a `clustering_runs` row with `status='running'`.
  - Run `DBSCAN(eps=eps, min_samples=min_samples, metric='cosine')`.
  - Exclude label `-1` from `cluster_suggestions`; persist those faces as
    `face_assignments.status='noise'`.
  - For every non-noise label, choose the representative face as the member
    nearest the cluster centroid using cosine distance.
  - Store `confidence='high'` when `min_samples >= 3`; otherwise
    `confidence='candidate'`.
  - Persist one `face_assignments` row per face with `status='suggested'` and
    its distance to the cluster centroid.
  - Never update or delete `person_faces` or named `persons` rows.
  - Mark the run `completed` in one transaction, or `error` with the exception
    text if persistence fails.
- [ ] Add `list_suggestion_faces(conn, suggestion_id)` and
  `representative_face(conn, face_id)` helpers for the API.

- [ ] **Verify**

Run a deterministic fixture with three synthetic 2D vectors expanded to 512
dimensions: two points in one cluster, two in a second, and one noise point.
Expected: two suggestions, one noise assignment, correct representative IDs.

### Task 3: Test clustering persistence and reruns

**Files:**
- Create: `packages/core/tests/test_clustering.py`

- [ ] Test that a second completed run creates a new `clustering_runs` row and
  does not change existing `person_faces` rows.
- [ ] Test high-confidence versus candidate settings.
- [ ] Test a failed run records `status='error'` and an error message.
- [ ] Test representative face selection is deterministic for identical vectors
  and input order.

- [ ] **Verify**

Run: `uv run --project packages/core pytest packages/core/tests/test_clustering.py`
Expected: all persistence and rerun tests pass.

### Task 4: Add a clustering worker job

**Files:**
- Modify: `services/worker/worker/run.py`
- Modify: `services/worker/worker/pipeline.py`
- Create: `services/worker/tests/test_clustering.py`

- [ ] Add `cluster_faces` handling to `drain_once`:
  - Read model, version, `eps`, and `min_samples` from job params.
  - Call `run_clustering` using the existing catalog connection.
  - Mark the job complete only after the run is complete.
  - Leave prior user confirmations untouched.
- [ ] Add a `cluster` helper that queues a `cluster_faces` job.
- [ ] Do not automatically enqueue a full-library clustering run for every
  single imported photo. Import jobs may enqueue a debounced clustering job
  only when `PICS_CLUSTER_ON_IMPORT=1`; default it off.
- [ ] Add an integration test with fake face embeddings and a fake model name.

- [ ] **Verify**

Run: `uv run --project services/worker --extra dev pytest services/worker/tests`
Expected: import tests and clustering job tests pass without model downloads.

### Task 5: Add API cluster and review endpoints

**Files:**
- Modify: `apps/api/api/persons.py`
- Modify: `apps/api/api/jobs.py`

- [ ] Extend `GET /persons` to return both stable people and unreviewed
  suggestions with:
  - suggestion/run ID
  - confidence/status
  - face count
  - representative crop URL
  - sample face crop URLs
  - optional linked `person_id`
- [ ] Add `POST /persons/cluster` to queue a `cluster_faces` job with optional
  `eps`, `min_samples`, and `model_version`, defaulting to `.30`, `3`, and the
  current face model version.
- [ ] Add `POST /persons/suggestions/{suggestion_id}/confirm`:
  - Create a new stable `persons` row if no `person_id` is supplied.
  - Add every suggestion face to `person_faces` with source
    `cluster-confirmed`.
  - Mark the suggestion `confirmed` and link it to the person.
- [ ] Add `POST /persons/suggestions/{suggestion_id}/reject`:
  - Mark the suggestion `rejected`.
  - Do not delete face embeddings or source photos.
- [ ] Add `POST /persons/{person_id}/faces/{face_id}` for manual assignment.
- [ ] Change merge to move `person_faces` links as well as provisional
  assignments, preserving the target person and deleting only the source
  person after the transaction.
- [ ] Add split support by removing selected face links from a person and
  creating a new unnamed person with source `manual-split`.

- [ ] **Verify**

Add API tests using a temporary SQLite catalog:

- Confirming a suggestion creates a person and durable face links.
- Rejecting a suggestion leaves no person link.
- Merging preserves all links under the target person.
- Splitting removes only the requested faces.
- A second clustering run does not remove confirmed links.

Run: `uv run --project apps/api --extra dev pytest apps/api/tests`

### Task 6: Serve representative and source face media

**Files:**
- Modify: `apps/api/api/persons.py`

- [ ] Add `GET /persons/faces/{face_id}/crop` to serve the crop file with
  `image/jpeg` and return 404 for missing/rejected crops.
- [ ] Add `GET /persons/faces/{face_id}/asset` to return the parent asset ID,
  source path, and bounding box for review context.
- [ ] Ensure paths are resolved under the configured library/crops directory;
  reject paths that escape the library root.

- [ ] **Verify**

Create a crop fixture and assert both endpoints return the expected bytes and
metadata. Assert a missing crop returns 404.

### Task 7: Replace the People page with review workflow

**Files:**
- Modify: `apps/web/types.ts`
- Modify: `apps/web/lib/api.ts`
- Replace: `apps/web/app/people/page.tsx`
- Modify: `apps/web/app/globals.css`

- [ ] Add TypeScript types for `ClusterSuggestion`, `FaceAssignment`, and
  `PersonReview`.
- [ ] Add API client methods for queueing clustering, confirming, rejecting,
  renaming, merging, splitting, and manual face assignment.
- [ ] Divide the page into:
  - High-confidence anonymous clusters.
  - Candidate clusters.
  - Named people.
  - Unassigned/noise faces.
- [ ] Render 3–5 representative crops per cluster and show a source-photo
  link/context for each crop.
- [ ] Implement one-click confirm/name, reject, merge, and split controls.
- [ ] Keep optimistic state changes limited to the affected cluster and reload
  the server state after a mutation completes.
- [ ] Display a warning that clusters are suggestions and that face data remains
  local.

- [ ] **Verify**

Run: `pnpm --dir apps/web test && pnpm --dir apps/web build`
Expected: parser tests and production build pass. Manually verify the page with
mocked API responses for high-confidence, candidate, and empty states.

### Task 8: Add CLI clustering and review commands

**Files:**
- Modify: `tools/cli/pics_cli/__main__.py`
- Create: `tools/cli/tests/test_clustering.py`

- [ ] Add `pics cluster [--eps 0.30] [--min-samples 3]` to enqueue a
  `cluster_faces` job against `PICS_DB`.
- [ ] Add `pics people` to print stable people, candidate clusters, face counts,
  and review status.
- [ ] Keep CLI output useful for scripts by supporting `--json`.
- [ ] Add parser tests for both commands.

- [ ] **Verify**

Run: `uv run --project tools/cli pics cluster --help` and
`uv run --project tools/cli pytest tools/cli/tests`.

### Task 9: Validate against a labeled fixture

**Files:**
- Create: `services/worker/tests/data/face-clustering-fixture.json`
- Create: `services/worker/tests/test_face_clustering_quality.py`

- [ ] Record a small manually reviewed fixture containing at least:
  - One repeat person across three photos.
  - One group photo with two known people.
  - One false/partial detection.
  - One visually similar unrelated person.
- [ ] Assert high-confidence defaults do not merge the unrelated faces.
- [ ] Assert the repeat person forms a candidate/high-confidence cluster.
- [ ] Document expected false-split behavior rather than requiring every
  difficult face to cluster automatically.

- [ ] **Verify**

Run: `uv run --project services/worker --extra dev pytest services/worker/tests`
Expected: quality fixture passes with the starting threshold, or the test
records an explicit threshold adjustment in the plan.

## Verification Summary

- [ ] Schema v2 migrates an existing catalog without losing `person_faces`.
- [ ] `DBSCAN(eps=.30, min_samples=3)` creates conservative suggestions.
- [ ] Candidate clusters remain separate from stable identities.
- [ ] Confirmed person links survive future clustering runs.
- [ ] Merge, split, reject, and manual assignment are transactional.
- [ ] People review page shows representative crops and review actions.
- [ ] CLI can queue and inspect clustering jobs.
- [ ] Core, worker, API, CLI, and web tests pass.
- [ ] Docker Compose smoke test can queue a cluster job and expose its status.
