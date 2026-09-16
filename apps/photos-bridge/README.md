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

Keep the bridge available for UI-triggered sync requests:

```bash
pnpm bridge:watch
```

This root-level command runs `swift run` with the correct package path and poll
interval for the developer workflow.

With the bridge watching, use the **Sync Apple Photos** button in Pics. The
bridge claims the request, imports the bounded batch, and reports completion;
the existing Pics worker processes each uploaded asset.

The Photos page also provides a full sync. It scans the complete PhotoKit
library in batches, checks already-imported `PHAsset.localIdentifier` values,
and uploads only assets that are missing from Pics.

Use a different API URL or limit:

```bash
swift run PicsPhotosBridge --api-url http://localhost:8000 --limit 100
```

The first run asks macOS for Photos access. The bridge uses PhotoKit and does
not read `Photos Library.photoslibrary` directly. While running in watch mode it
reports its authorization and inventory heartbeat to Pics, so the Photos page
can guide the progression from a detected library to an available import.
