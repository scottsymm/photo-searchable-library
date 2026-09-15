# Apple Photos Connection Progression Implementation Plan

*Created: 2026-09-15*

**Goal:** Guide Apple Photos from detected library to bridge authorization, inventory, and first import with truthful server-backed states.

**Architecture:** Persist a bridge heartbeat on the Apple Photos source. The native macOS bridge reports authorization and inventory while it is alive; the API derives an offline/authorization-required/connected state using a short heartbeat lease. The catalog endpoint exposes bridge metadata, and the Photos page renders a progressive connection card that only emphasizes sync once the bridge is ready.

**Tech Stack:** Swift PhotoKit bridge, FastAPI + SQLite, pytest, Next.js 16 + React 19 + TypeScript, Vitest.

**Source:** Approved follow-up requirements from the catalog-overview review on 2026-09-15.

## File Map

| File | Action | Responsibility |
|---|---|---|
| `packages/core/core/schema.py` | Modify | Persist bridge status and heartbeat timestamp on sources |
| `packages/core/tests/test_schema.py` | Modify | Verify bridge columns migrate |
| `apps/api/api/sources.py` | Modify | Accept bridge heartbeats and derive bridge availability |
| `apps/api/tests/test_sources.py` | Modify | Verify heartbeat, authorization, and stale bridge states |
| `apps/api/api/catalog.py` | Modify | Include bridge state in Apple Photos overview data |
| `apps/api/tests/test_catalog.py` | Modify | Verify overview exposes bridge progression state |
| `apps/photos-bridge/Sources/PicsPhotosBridge/main.swift` | Modify | Send authorization and inventory heartbeats while running |
| `apps/photos-bridge/README.md` | Modify | Document progression and first connection command |
| `apps/web/types.ts` | Modify | Add bridge state fields |
| `apps/web/app/photos/page.tsx` | Modify | Render progressive Apple Photos connection and sync actions |
| `apps/web/app/globals.css` | Modify | Style progression panel and state treatment |
| `apps/web/lib/funnel.test.ts` | Modify | Verify bridge state labels |

## Tasks

### Task 1: Persist Apple Photos bridge presence

**Files:**
- Modify: `packages/core/core/schema.py`
- Test: `packages/core/tests/test_schema.py`

- [x] **Step 1: Add migration tests**

Append:

```python
def test_migrate_adds_bridge_presence_columns(tmp_path):
    conn = connect(str(tmp_path / "catalog.db"))
    migrate(conn)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(sources)")}
    conn.close()
    assert {"bridge_status", "bridge_last_seen_at"} <= columns
```

- [x] **Step 2: Implement**

Add to the `sources` table after `authorization_state`:

```sql
  bridge_status TEXT NOT NULL DEFAULT 'offline',
  bridge_last_seen_at TEXT,
```

Add a source-column migration tuple in `migrate` that adds both columns when absent, using definitions `TEXT NOT NULL DEFAULT 'offline'` and `TEXT` respectively.

- [x] **Step 3: Verify**

Run: `uv run --frozen --package pics-core --extra dev pytest tests/test_schema.py -x` (workdir `packages/core`)
Expected: PASS — 4 schema tests.

- [x] **Step 4: Commit**

```bash
git add packages/core/core/schema.py packages/core/tests/test_schema.py
git commit -m "feat: persist Apple Photos bridge presence"
```

### Task 2: Add bridge heartbeat endpoint and state derivation

**Files:**
- Modify: `apps/api/api/sources.py`
- Test: `apps/api/tests/test_sources.py`

- [x] **Step 1: Add tests**

Append tests that POST `/sources/apple-photos/bridge/heartbeat` with `{"authorization_state":"notDetermined","asset_count":0}` and assert `bridge_status == "authorization_required"`, POST with `{"authorization_state":"authorized","asset_count":8105}` and assert `bridge_status == "connected"`, and assert a status response whose `bridge_last_seen_at` is older than `PICS_BRIDGE_LEASE_SECONDS` reports `bridge_status == "offline"`.

- [x] **Step 2: Implement**

Add `BRIDGE_LEASE_SECONDS = int(os.environ.get("PICS_BRIDGE_LEASE_SECONDS", "15"))`, a Pydantic `BridgeHeartbeat` with `authorization_state: str` and `asset_count: int = Field(ge=0)`, and:

```python
def _bridge_status(authorization_state: str, asset_count: int) -> str:
    if authorization_state in ("denied", "restricted", "notDetermined"):
        return "authorization_required"
    return "inventory_pending" if asset_count == 0 else "connected"
```

Add `POST /apple-photos/bridge/heartbeat` to update `bridge_status`, `bridge_last_seen_at`, `authorization_state`, and `asset_count`, then return the source status. Add `_source_with_bridge_status` for the status endpoint: return `offline` when the heartbeat is missing or older than the lease, while preserving the persisted status for a live bridge.

- [x] **Step 3: Verify**

Run: `uv run --frozen --package pics-api --extra dev pytest tests/test_sources.py -x` (workdir `apps/api`)
Expected: PASS — 7 source tests.

- [x] **Step 4: Commit**

```bash
git add apps/api/api/sources.py apps/api/tests/test_sources.py
git commit -m "feat: expose Apple Photos bridge heartbeat state"
```

### Task 3: Send bridge heartbeat during startup and polling

**Files:**
- Modify: `apps/photos-bridge/Sources/PicsPhotosBridge/main.swift`
- Modify: `apps/photos-bridge/README.md`

- [x] **Step 1: Implement heartbeat request**

Add a Codable `BridgeHeartbeat` with `authorization_state` and `asset_count`, a `sendHeartbeat` function posting JSON to `/sources/apple-photos/bridge/heartbeat`, and call it after `requestAccess()` with the current authorization state and `PHAsset.fetchAssets(with: nil).count`. In watch mode, send the same heartbeat before each `claimSync` poll. If heartbeat fails, log `heartbeat_error=...` but continue so a temporary API failure does not terminate the bridge.

- [x] **Step 2: Document the progression**

Update the README to state that the first run reports authorization, the watch process refreshes bridge presence, and the Photos page moves from detected to connected before enabling normal sync guidance.

- [x] **Step 3: Verify**

Run: `swift build` (workdir `apps/photos-bridge`)
Expected: PASS — Swift package builds.

- [x] **Step 4: Commit**

```bash
git add apps/photos-bridge/Sources/PicsPhotosBridge/main.swift apps/photos-bridge/README.md
git commit -m "feat: report Apple Photos bridge presence"
```

### Task 4: Expose bridge metadata through catalog overview

**Files:**
- Modify: `apps/api/api/catalog.py`
- Test: `apps/api/tests/test_catalog.py`

- [x] **Step 1: Add test**

Add a catalog test that updates the Apple Photos source with `bridge_status = 'connected'`, `bridge_last_seen_at` set to the current UTC timestamp, `authorization_state = 'authorized'`, and `asset_count = 8105`, then asserts the Apple Photos entry includes `bridge_status == 'connected'`, `bridge_last_seen_at`, and `authorization_state == 'authorized'`.

- [x] **Step 2: Implement**

Add these fields to `_apple_entry`:

```python
"bridge_status": source["bridge_status"],
"bridge_last_seen_at": source["bridge_last_seen_at"],
"authorization_state": source["authorization_state"],
```

Use the same stale-heartbeat derivation as the source status endpoint before constructing the entry, so the overview never reports a live bridge after its lease expires.

- [x] **Step 3: Verify**

Run: `uv run --frozen --package pics-api --extra dev pytest tests/test_catalog.py -x` (workdir `apps/api`)
Expected: PASS — 14 catalog tests.

- [x] **Step 4: Commit**

```bash
git add apps/api/api/catalog.py apps/api/tests/test_catalog.py
git commit -m "feat: include bridge state in catalog overview"
```

### Task 5: Render progressive Apple Photos actions

**Files:**
- Modify: `apps/web/types.ts`
- Modify: `apps/web/app/photos/page.tsx`
- Modify: `apps/web/app/globals.css`
- Test: `apps/web/lib/funnel.test.ts`

- [x] **Step 1: Add types and labels**

Add `BridgeStatus = "offline" | "authorization_required" | "inventory_pending" | "connected" | "syncing"`, plus `bridge_status`, `bridge_last_seen_at`, and `authorization_state` to `SourceOverview`. Add a `bridgeLabel` helper with labels `Bridge offline`, `Photos access required`, `Reading Photos library`, `Connected`, and `Syncing` and tests for all states.

- [x] **Step 2: Replace Apple Photos card guidance**

Use `bridge_status` rather than `readiness` to render this progression:

```tsx
const bridgeReady = source.bridge_status === "connected";
const bridgeOffline = source.bridge_status === "offline";
const bridgeNeedsAccess = source.bridge_status === "authorization_required";
```

When offline, show `Library found · Bridge offline`, the detected library path from `context.photos_libraries`, and a collapsible setup panel with the bridge command. When authorization is required, show “Allow Photos access in macOS, then keep the bridge running.” When inventory is pending, show “Connected. Reading your Photos library…” and disable sync. Only show `Import latest 25` as the primary action when `bridgeReady`; keep full sync secondary behind the existing confirmation dialog. Rename the actions from `Sync` to `Import`.

- [x] **Step 3: Add styles**

Add styles for `.sourceProgress`, `.sourceProgressTitle`, `.setupDetails`, and `.setupDetails code` using the existing panel, accent, and muted variables. Ensure the setup panel is readable at mobile widths.

- [x] **Step 4: Verify**

Run: `pnpm --filter web check && pnpm --filter web test` (workdir repo root)
Expected: PASS — TypeScript and both Vitest files.

- [x] **Step 5: Commit**

```bash
git add apps/web/types.ts apps/web/app/photos/page.tsx apps/web/app/globals.css apps/web/lib/funnel.test.ts
git commit -m "feat: guide Apple Photos connection progression"
```

### Task 6: Final verification

- [x] **Step 1: Full tests**

Run: `pnpm test`
Expected: PASS — all five packages.

- [x] **Step 2: Live progression smoke check**

With `pnpm dev:docker` running, verify `GET /catalog/overview` reports the Apple Photos bridge state, `/photos` shows the detected library plus bridge-offline guidance, and a heartbeat changes the API state to `connected` or `inventory_pending`.

- [x] **Step 3: Commit plan state**

```bash
git add artifacts/pics/catalog-overview/apple-photos-progression/apple-photos-progression-inception.md artifacts/pics/catalog-overview/apple-photos-progression/apple-photos-progression-plan.md
git commit -m "docs: add Apple Photos progression plan"
```

## Verification Summary

- [x] All tests pass: `pnpm test`
- [x] Bridge builds: `swift build` in `apps/photos-bridge`
- [x] App starts clean: `pnpm dev:docker:build` or `pnpm dev:docker`
- [x] Feature works end-to-end: detected library → bridge offline → authorization/inventory → connected import action
