# Apple Photos Source Phase 1 Implementation Plan

*Created: 2026-09-15*

**Goal:** Add a native macOS Apple Photos bridge that imports authorized Photos assets into Pics with stable source identity and visible sync status.

**Architecture:** A Swift command-line bridge uses PhotoKit to authorize, enumerate, and extract primary asset resources. The FastAPI service exposes a dedicated Apple Photos ingest endpoint that stores source identity, deduplicates by `source + source_asset_id`, writes the media into the library, and queues the existing import pipeline. The web Photos tab shows bridge sync state. SwiftPM owns the native bridge build; Docker Compose and Turborepo do not build the macOS-only bridge in Phase 1.

**Tech Stack:** Swift 6 / PhotoKit, FastAPI, SQLite, Next.js, pytest, TypeScript.

**Source:** `artifacts/pics/apple-photos-source/apple-photos-source-spike.md`

## Scope

**In scope:**

- `apple_photos` source registration
- Stable `PHAsset.localIdentifier` source asset IDs
- PhotoKit authorization and enumeration
- Primary image/video resource extraction
- Dedicated bridge ingest endpoint
- Duplicate handling by source ID and content hash
- Sync status and error reporting
- Basic web visibility for Apple Photos source state

**Out of scope:**

- Albums
- Apple People import
- Edit/rendition selection
- Live Photo video-component import
- Deletion propagation
- Background daemon packaging
- Menu-bar UI
- Automatic continuous sync scheduling

## File Map

| File | Action | Responsibility |
|---|---|---|
| `packages/core/core/schema.py` | Modify | Add `sources` table and source identity columns/indexes for assets |
| `packages/core/core/sources.py` | Create | Register sources and resolve source asset records |
| `packages/core/tests/test_sources.py` | Create | Test source registration and source asset identity behavior |
| `apps/api/api/sources.py` | Create | Dedicated Apple Photos bridge ingest and status endpoints |
| `apps/api/api/main.py` | Modify | Mount source routes |
| `apps/api/tests/test_sources.py` | Create | Test bridge ingest, deduplication, and status responses |
| `apps/web/types.ts` | Modify | Add Apple Photos source status types |
| `apps/web/lib/api.ts` | Modify | Add source status API client |
| `apps/web/app/photos/page.tsx` | Modify | Show Apple Photos bridge authorization/sync state |
| `apps/photos-bridge/Package.swift` | Create | Define Swift command-line bridge package |
| `apps/photos-bridge/Sources/PicsPhotosBridge/main.swift` | Create | PhotoKit authorization, enumeration, extraction, and API upload |
| `apps/photos-bridge/README.md` | Create | Document local bridge build/run commands |
| `package.json` | Modify | Add root convenience scripts for bridge build, dry run, and bounded sync |
| `README.md` | Modify | Document Apple Photos bridge Phase 1 usage |

## Tasks

### Task 1: Add source schema support

**Files:**
- Modify: `packages/core/core/schema.py`
- Test: `packages/core/tests/test_sources.py`

- [ ] **Step 1: Add failing tests**

Create `packages/core/tests/test_sources.py`:

```python
from core.conn import connect
from core.schema import migrate


def db():
    conn = connect(":memory:")
    migrate(conn)
    return conn


def test_sources_table_seeds_apple_photos_source():
    conn = db()
    row = conn.execute(
        "SELECT kind, display_name, status FROM sources WHERE kind = 'apple_photos'"
    ).fetchone()
    assert row["kind"] == "apple_photos"
    assert row["display_name"] == "Apple Photos"
    assert row["status"] == "not_connected"


def test_assets_have_source_identity_columns():
    conn = db()
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(assets)")}
    assert {"source_id", "source_asset_id", "original_filename"} <= columns
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
cd packages/core
.venv/bin/pytest tests/test_sources.py -q
```

Expected: FAIL — `sources` table does not exist.

- [ ] **Step 3: Add schema tables and columns**

In `packages/core/core/schema.py`, add this table after `files`:

```sql
CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  display_name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'not_connected',
  authorization_state TEXT,
  last_sync_at TEXT,
  last_error TEXT,
  asset_count INTEGER NOT NULL DEFAULT 0,
  imported_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(kind)
);
```

Add these columns to the `assets` schema definition:

```sql
  source_id INTEGER REFERENCES sources(id),
  source_asset_id TEXT,
  original_filename TEXT,
```

Add this index after the existing asset indexes:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS assets_source_asset_idx
ON assets(source_id, source_asset_id)
WHERE source_id IS NOT NULL AND source_asset_id IS NOT NULL;
```

In `migrate`, after `seed(conn)`, add:

```python
    conn.execute(
        """INSERT OR IGNORE INTO sources(kind, display_name, status)
        VALUES ('apple_photos', 'Apple Photos', 'not_connected')"""
    )
```

- [ ] **Step 4: Verify tests pass**

Run:

```bash
cd packages/core
.venv/bin/pytest tests/test_sources.py -q
```

Expected: PASS — 2 tests passing.

- [ ] **Step 5: Commit**

```bash
git add packages/core/core/schema.py packages/core/tests/test_sources.py
git commit -m "feat: add source identity schema"
```

### Task 2: Add source persistence helpers

**Files:**
- Create: `packages/core/core/sources.py`
- Test: `packages/core/tests/test_sources.py`

- [ ] **Step 1: Add failing tests**

Append to `packages/core/tests/test_sources.py`:

```python
from core.sources import get_source, mark_source_status, upsert_source_asset


def test_source_status_tracks_authorization_and_counts():
    conn = db()
    source = get_source(conn, "apple_photos")
    mark_source_status(
        conn,
        source_id=source["id"],
        status="connected",
        authorization_state="authorized",
        asset_count=10,
        imported_count=2,
    )
    updated = get_source(conn, "apple_photos")
    assert updated["status"] == "connected"
    assert updated["authorization_state"] == "authorized"
    assert updated["asset_count"] == 10
    assert updated["imported_count"] == 2


def test_upsert_source_asset_is_idempotent():
    conn = db()
    source = get_source(conn, "apple_photos")
    first = upsert_source_asset(
        conn,
        source_id=source["id"],
        source_asset_id="asset-1",
        path="/library/imports/one.jpg",
        original_filename="one.jpg",
    )
    second = upsert_source_asset(
        conn,
        source_id=source["id"],
        source_asset_id="asset-1",
        path="/library/imports/two.jpg",
        original_filename="one.jpg",
    )
    assert first == second
    assert conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 1
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
cd packages/core
.venv/bin/pytest tests/test_sources.py -q
```

Expected: FAIL — `core.sources` does not exist.

- [ ] **Step 3: Implement source helpers**

Create `packages/core/core/sources.py`:

```python
"""Source registration and source-backed asset identity."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def get_source(conn: sqlite3.Connection, kind: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM sources WHERE kind = ?", (kind,)).fetchone()
    if row is None:
        raise ValueError(f"unknown source: {kind}")
    return row


def mark_source_status(
    conn: sqlite3.Connection,
    *,
    source_id: int,
    status: str,
    authorization_state: str | None = None,
    asset_count: int | None = None,
    imported_count: int | None = None,
    last_error: str | None = None,
) -> None:
    current = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    if current is None:
        raise ValueError(f"unknown source id: {source_id}")
    conn.execute(
        """UPDATE sources SET
        status = ?, authorization_state = ?, asset_count = ?, imported_count = ?,
        last_error = ?, last_sync_at = ?, updated_at = ?
        WHERE id = ?""",
        (
            status,
            authorization_state,
            current["asset_count"] if asset_count is None else asset_count,
            current["imported_count"] if imported_count is None else imported_count,
            last_error,
            datetime.now(timezone.utc).isoformat(),
            datetime.now(timezone.utc).isoformat(),
            source_id,
        ),
    )
    conn.commit()


def upsert_source_asset(
    conn: sqlite3.Connection,
    *,
    source_id: int,
    source_asset_id: str,
    path: str,
    original_filename: str | None,
) -> int:
    conn.execute(
        """INSERT INTO assets(source_id, source_asset_id, original_filename, path, sha256, size_bytes, mime)
        VALUES (?, ?, ?, ?, '', 0, 'application/octet-stream')
        ON CONFLICT(source_id, source_asset_id) DO UPDATE SET
          original_filename = excluded.original_filename,
          deleted = 0""",
        (source_id, source_asset_id, original_filename, path),
    )
    row = conn.execute(
        "SELECT id FROM assets WHERE source_id = ? AND source_asset_id = ?",
        (source_id, source_asset_id),
    ).fetchone()
    if row is None:
        raise RuntimeError("source asset row was not persisted")
    conn.commit()
    return int(row["id"])
```

- [ ] **Step 4: Verify tests pass**

Run:

```bash
cd packages/core
.venv/bin/pytest tests/test_sources.py -q
```

Expected: PASS — 4 tests passing.

- [ ] **Step 5: Commit**

```bash
git add packages/core/core/sources.py packages/core/tests/test_sources.py
git commit -m "feat: add source persistence helpers"
```

### Task 3: Add dedicated Apple Photos ingest endpoint

**Files:**
- Create: `apps/api/api/sources.py`
- Modify: `apps/api/api/main.py`
- Test: `apps/api/tests/test_sources.py`

- [ ] **Step 1: Add failing API tests**

Create `apps/api/tests/test_sources.py`:

```python
def test_apple_photos_status_defaults(client):
    response = client.get("/sources/apple-photos/status")
    assert response.status_code == 200
    assert response.json()["source"]["kind"] == "apple_photos"
    assert response.json()["source"]["status"] == "not_connected"


def test_apple_photos_ingest_queues_import(client, tmp_path, monkeypatch):
    monkeypatch.setattr("api.sources.LIBRARY", tmp_path)
    response = client.post(
        "/sources/apple-photos/assets",
        files={"file": ("IMG_0001.JPG", b"jpeg-bytes", "image/jpeg")},
        data={
            "source_asset_id": "ABC/L0/001",
            "original_filename": "IMG_0001.JPG",
            "media_type": "image",
            "authorization_state": "authorized",
            "asset_count": "1",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["duplicate"] is False
    assert body["source_asset_id"] == "ABC/L0/001"

    duplicate = client.post(
        "/sources/apple-photos/assets",
        files={"file": ("IMG_0001.JPG", b"jpeg-bytes", "image/jpeg")},
        data={"source_asset_id": "ABC/L0/001", "original_filename": "IMG_0001.JPG"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
```

- [ ] **Step 2: Verify tests fail**

Run:

```bash
cd apps/api
.venv/bin/pytest tests/test_sources.py -q
```

Expected: FAIL — `/sources/apple-photos/status` is not found.

- [ ] **Step 3: Implement source routes**

Create `apps/api/api/sources.py`:

```python
"""External source ingest and status endpoints."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile

from core import jobs
from core.assets import sha256_file
from core.sources import get_source, mark_source_status

from .deps import get_conn

router = APIRouter()
LIBRARY = Path(os.environ.get("PICS_LIBRARY", "library"))


@router.get("/apple-photos/status")
def apple_photos_status(conn=Depends(get_conn)):
    source = dict(get_source(conn, "apple_photos"))
    imported = conn.execute(
        """SELECT COUNT(*) FROM assets
        WHERE source_id = ? AND deleted = 0 AND sha256 != ''""",
        (source["id"],),
    ).fetchone()[0]
    source["imported_count"] = imported
    return {"source": source}


@router.post("/apple-photos/assets")
async def ingest_apple_photos_asset(
    file: UploadFile = File(...),
    source_asset_id: str = Form(...),
    original_filename: str | None = Form(default=None),
    media_type: str | None = Form(default=None),
    taken_at: str | None = Form(default=None),
    authorization_state: str | None = Form(default=None),
    asset_count: int | None = Form(default=None),
    conn=Depends(get_conn),
):
    source = get_source(conn, "apple_photos")
    existing = conn.execute(
        """SELECT id, path FROM assets
        WHERE source_id = ? AND source_asset_id = ? AND deleted = 0""",
        (source["id"], source_asset_id),
    ).fetchone()
    if existing is not None and existing["path"]:
        mark_source_status(
            conn,
            source_id=source["id"],
            status="connected",
            authorization_state=authorization_state,
            asset_count=asset_count,
        )
        return {
            "status": "duplicate",
            "duplicate": True,
            "asset_id": existing["id"],
            "source_asset_id": source_asset_id,
        }

    suffix = Path(original_filename or file.filename or "photo.jpg").suffix.lower() or ".jpg"
    destination = LIBRARY / "apple-photos" / f"{uuid.uuid4().hex}{suffix}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as output:
        shutil.copyfileobj(file.file, output)

    conn.execute(
        """INSERT INTO assets(
          source_id, source_asset_id, original_filename, path, sha256, size_bytes, mime, taken_at, extra
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        ),
    )
    asset_id = conn.execute(
        "SELECT id FROM assets WHERE source_id = ? AND source_asset_id = ?",
        (source["id"], source_asset_id),
    ).fetchone()["id"]
    job_id = jobs.push(conn, "import", {"paths": [str(destination)]})
    mark_source_status(
        conn,
        source_id=source["id"],
        status="connected",
        authorization_state=authorization_state,
        asset_count=asset_count,
    )
    return {
        "status": "queued",
        "duplicate": False,
        "asset_id": asset_id,
        "job_id": job_id,
        "source_asset_id": source_asset_id,
        "path": str(destination),
    }
```

In `apps/api/api/main.py`, change the import line to:

```python
from . import admin, jobs, persons, places, search, sources, uploads
```

Add after the places router:

```python
app.include_router(sources.router, prefix="/sources", tags=["sources"])
```

- [ ] **Step 4: Verify tests pass**

Run:

```bash
cd apps/api
.venv/bin/pytest tests/test_sources.py -q
```

Expected: PASS — 2 tests passing.

- [ ] **Step 5: Commit**

```bash
git add apps/api/api/sources.py apps/api/api/main.py apps/api/tests/test_sources.py
git commit -m "feat: add Apple Photos ingest endpoint"
```

### Task 4: Create Swift bridge package

**Files:**
- Create: `apps/photos-bridge/Package.swift`
- Create: `apps/photos-bridge/Sources/PicsPhotosBridge/main.swift`
- Create: `apps/photos-bridge/README.md`

- [ ] **Step 1: Create package manifest**

Create `apps/photos-bridge/Package.swift`:

```swift
// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "PicsPhotosBridge",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(name: "PicsPhotosBridge")
    ]
)
```

- [ ] **Step 2: Create bridge implementation**

Create `apps/photos-bridge/Sources/PicsPhotosBridge/main.swift`:

```swift
import Foundation
import Photos

struct BridgeOptions {
    var apiURL = URL(string: "http://localhost:8000")!
    var limit = 25
    var dryRun = false
}

func parseOptions() -> BridgeOptions {
    var options = BridgeOptions()
    var arguments = CommandLine.arguments.dropFirst()
    while let argument = arguments.popFirst() {
        switch argument {
        case "--api-url":
            if let value = arguments.popFirst(), let url = URL(string: value) {
                options.apiURL = url
            }
        case "--limit":
            if let value = arguments.popFirst(), let limit = Int(value) {
                options.limit = limit
            }
        case "--dry-run":
            options.dryRun = true
        default:
            break
        }
    }
    return options
}

func authorizationName(_ status: PHAuthorizationStatus) -> String {
    switch status {
    case .notDetermined: return "notDetermined"
    case .restricted: return "restricted"
    case .denied: return "denied"
    case .authorized: return "authorized"
    case .limited: return "limited"
    @unknown default: return "unknown"
    }
}

func requestAccess() async -> PHAuthorizationStatus {
    let current = PHPhotoLibrary.authorizationStatus(for: .readWrite)
    if current != .notDetermined { return current }
    return await PHPhotoLibrary.requestAuthorization(for: .readWrite)
}

func primaryResource(for asset: PHAsset) -> PHAssetResource? {
    let resources = PHAssetResource.assetResources(for: asset)
    if asset.mediaType == .video {
        return resources.first { $0.uniformTypeIdentifier.contains("movie") || $0.uniformTypeIdentifier.contains("video") } ?? resources.first
    }
    return resources.first { $0.uniformTypeIdentifier.contains("image") || $0.uniformTypeIdentifier.contains("jpeg") || $0.uniformTypeIdentifier.contains("heic") } ?? resources.first
}

func extract(resource: PHAssetResource, to output: URL) async throws {
    if FileManager.default.fileExists(atPath: output.path) {
        try FileManager.default.removeItem(at: output)
    }
    let options = PHAssetResourceRequestOptions()
    options.isNetworkAccessAllowed = true
    try await withCheckedThrowingContinuation { continuation in
        PHAssetResourceManager.default().writeData(for: resource, toFile: output, options: options) { error in
            if let error {
                continuation.resume(throwing: error)
            } else {
                continuation.resume()
            }
        }
    }
}

func upload(asset: PHAsset, resource: PHAssetResource, fileURL: URL, options: BridgeOptions) async throws {
    var request = URLRequest(url: options.apiURL.appendingPathComponent("/sources/apple-photos/assets"))
    request.httpMethod = "POST"
    let boundary = UUID().uuidString
    request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

    var body = Data()
    func field(_ name: String, _ value: String) {
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n".data(using: .utf8)!)
        body.append("\(value)\r\n".data(using: .utf8)!)
    }

    field("source_asset_id", asset.localIdentifier)
    field("original_filename", resource.originalFilename)
    field("media_type", asset.mediaType == .video ? "video" : "image")
    if let creationDate = asset.creationDate {
        field("taken_at", creationDate.ISO8601Format())
    }
    field("authorization_state", authorizationName(PHPhotoLibrary.authorizationStatus(for: .readWrite)))

    let filename = resource.originalFilename
    let mime = asset.mediaType == .video ? "video/quicktime" : "application/octet-stream"
    body.append("--\(boundary)\r\n".data(using: .utf8)!)
    body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n".data(using: .utf8)!)
    body.append("Content-Type: \(mime)\r\n\r\n".data(using: .utf8)!)
    body.append(try Data(contentsOf: fileURL))
    body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)

    let (data, response) = try await URLSession.shared.upload(for: request, from: body)
    guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
        throw NSError(domain: "PicsPhotosBridge", code: 1, userInfo: [NSLocalizedDescriptionKey: String(data: data, encoding: .utf8) ?? "upload failed"])
    }
}

@main
struct PicsPhotosBridge {
    static func main() async {
        let options = parseOptions()
        let status = await requestAccess()
        print("authorization=\(authorizationName(status))")
        guard status == .authorized || status == .limited else {
            exit(2)
        }

        let fetchOptions = PHFetchOptions()
        fetchOptions.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: false)]
        let assets = PHAsset.fetchAssets(with: fetchOptions)
        print("asset_count=\(assets.count)")

        let count = min(options.limit, assets.count)
        let temporaryDirectory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try? FileManager.default.createDirectory(at: temporaryDirectory, withIntermediateDirectories: true)

        for index in 0..<count {
            let asset = assets.object(at: index)
            guard let resource = primaryResource(for: asset) else {
                print("skip=\(asset.localIdentifier) reason=no-resource")
                continue
            }
            print("asset=\(asset.localIdentifier) file=\(resource.originalFilename)")
            if options.dryRun { continue }
            let output = temporaryDirectory.appendingPathComponent(resource.originalFilename)
            do {
                try await extract(resource: resource, to: output)
                try await upload(asset: asset, resource: resource, fileURL: output, options: options)
                print("uploaded=\(asset.localIdentifier)")
            } catch {
                print("error=\(asset.localIdentifier) \(error.localizedDescription)")
            }
        }
    }
}
```

- [ ] **Step 3: Create bridge README**

Create `apps/photos-bridge/README.md`:

```markdown
# Apple Photos Bridge

Native macOS command-line bridge for importing Apple Photos assets into Pics.

Build:

```bash
swift build
```

Preview the first 25 assets without uploading:

```bash
swift run PicsPhotosBridge --dry-run
```

Import the first 25 assets into the local API:

```bash
swift run PicsPhotosBridge --limit 25
```

Use a different API URL or limit:

```bash
swift run PicsPhotosBridge --api-url http://localhost:8000 --limit 100
```

The first run asks macOS for Photos access. The bridge uses PhotoKit and does
not read `Photos Library.photoslibrary` directly.
```

- [ ] **Step 4: Verify bridge builds**

Run:

```bash
cd apps/photos-bridge
swift build
```

Expected: PASS — `Build complete!`

- [ ] **Step 5: Verify dry run**

Run:

```bash
cd apps/photos-bridge
.build/debug/PicsPhotosBridge --dry-run --limit 3
```

Expected: PASS — output includes `authorization=authorized`, `asset_count=`, and three `asset=` lines.

- [ ] **Step 6: Add root convenience scripts**

Modify the root `package.json` scripts block to include:

```json
"bridge:build": "swift build --package-path apps/photos-bridge",
"bridge:dry-run": "swift run --package-path apps/photos-bridge PicsPhotosBridge --dry-run --limit 25",
"bridge:sync": "swift run --package-path apps/photos-bridge PicsPhotosBridge --limit 25"
```

These scripts are convenience wrappers only. SwiftPM remains the build system for the macOS bridge; Docker Compose and Turborepo do not build it in Phase 1.

- [ ] **Step 7: Verify root scripts**

Run:

```bash
pnpm bridge:build
pnpm bridge:dry-run
```

Expected: PASS — the Swift package builds and the dry run prints authorization state, asset count, and asset IDs.

- [ ] **Step 8: Commit**

```bash
git add apps/photos-bridge package.json
git commit -m "feat: add Apple Photos bridge prototype"
```

### Task 5: Surface Apple Photos source state in the web UI

**Files:**
- Modify: `apps/web/types.ts`
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/app/photos/page.tsx`

- [ ] **Step 1: Add source status type**

In `apps/web/types.ts`, append:

```typescript
export interface SourceStatus {
  id: number;
  kind: string;
  display_name: string;
  status: string;
  authorization_state: string | null;
  last_sync_at: string | null;
  last_error: string | null;
  asset_count: number;
  imported_count: number;
}
```

- [ ] **Step 2: Add API client**

In `apps/web/lib/api.ts`, add `SourceStatus` to the type import and append:

```typescript
export async function applePhotosStatus(): Promise<SourceStatus> {
  const response = await fetch(apiUrl("/sources/apple-photos/status"), { cache: "no-store" });
  if (!response.ok) throw new Error("Apple Photos status request failed");
  return (await response.json()).source;
}
```

- [ ] **Step 3: Show source state on Photos page**

In `apps/web/app/photos/page.tsx`, import:

```typescript
import { applePhotosStatus, libraryInventory } from "../../lib/api";
import type { LibraryInventory, SourceStatus } from "../../types";
```

Add state:

```typescript
const [source, setSource] = useState<SourceStatus | null>(null);
```

Change the effect to:

```typescript
useEffect(() => {
  libraryInventory().then(setInventory).catch((reason) => {
    setError(reason instanceof Error ? reason.message : "Library inventory unavailable");
  });
  applePhotosStatus().then(setSource).catch(() => setSource(null));
}, []);
```

After the first cards section, add:

```tsx
{source && <><h2>Apple Photos bridge</h2><div className="cards"><div className="card"><strong>{source.status}</strong><span className="muted">Authorization: {source.authorization_state ?? "not requested"}</span></div><div className="card"><strong>{source.imported_count.toLocaleString()} imported</strong><span className="muted">{source.asset_count.toLocaleString()} assets reported by the bridge.</span></div><div className="card"><strong>Last sync</strong><span className="muted">{source.last_sync_at ?? "Never"}</span></div></div></>}
```

- [ ] **Step 4: Verify web checks**

Run:

```bash
cd apps/web
pnpm check
pnpm build
```

Expected: PASS — TypeScript check and production build succeed.

- [ ] **Step 5: Commit**

```bash
git add apps/web/types.ts apps/web/lib/api.ts apps/web/app/photos/page.tsx
git commit -m "feat: show Apple Photos bridge status"
```

### Task 6: Document Phase 1 usage

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add Apple Photos section**

After the `## Index Photos` section in `README.md`, add:

```markdown
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

The first run asks macOS for Photos access. Phase 1 imports primary image and
video resources with stable Apple asset identifiers. Albums, Apple People,
edits, deletion propagation, and background scheduling are deferred.
```

- [ ] **Step 2: Verify documentation commands**

Run:

```bash
cd apps/photos-bridge
swift build
```

Expected: PASS — `Build complete!`

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document Apple Photos bridge"
```

### Task 7: Run full verification

**Files:**
- None

- [ ] **Step 1: Run Python tests**

Run:

```bash
cd packages/core && .venv/bin/pytest -q
cd ../../apps/api && .venv/bin/pytest -q
cd ../../services/worker && .venv/bin/pytest -q
```

Expected: PASS — all core, API, and worker tests pass.

- [ ] **Step 2: Run web checks**

Run:

```bash
cd apps/web
pnpm check
pnpm build
```

Expected: PASS — TypeScript and production build succeed.

- [ ] **Step 3: Run bridge dry run**

Run:

```bash
cd apps/photos-bridge
.build/debug/PicsPhotosBridge --dry-run --limit 3
```

Expected: PASS — authorization is `authorized` or `limited`, and asset IDs are printed.

- [ ] **Step 4: Run bounded live import**

Run:

```bash
cd apps/photos-bridge
.build/debug/PicsPhotosBridge --limit 3
curl -sS http://localhost:8000/sources/apple-photos/status
```

Expected: PASS — bridge uploads complete or report per-asset errors; status shows `connected` and an imported count.

- [ ] **Step 5: Commit any remaining fixes**

```bash
git status --short
git add <only files changed by verification fixes>
git commit -m "test: verify Apple Photos bridge phase 1"
```

## Verification Summary

Final verification steps after all tasks complete:

- [ ] Core tests pass: `cd packages/core && .venv/bin/pytest -q`
- [ ] API tests pass: `cd apps/api && .venv/bin/pytest -q`
- [ ] Worker tests pass: `cd services/worker && .venv/bin/pytest -q`
- [ ] Web check passes: `cd apps/web && pnpm check`
- [ ] Web build passes: `cd apps/web && pnpm build`
- [ ] Bridge builds: `pnpm bridge:build`
- [ ] Bridge dry run lists assets: `pnpm bridge:dry-run`
- [ ] Bounded live import updates status: `pnpm bridge:sync && curl -sS http://localhost:8000/sources/apple-photos/status`
