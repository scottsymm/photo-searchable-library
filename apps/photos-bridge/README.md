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
swift run PicsPhotosBridge --watch --poll-interval 5
```

With the bridge watching, use the **Sync Apple Photos** button in Pics. The
bridge claims the request, imports the bounded batch, and reports completion;
the existing Pics worker processes each uploaded asset.

Use a different API URL or limit:

```bash
swift run PicsPhotosBridge --api-url http://localhost:8000 --limit 100
```

The first run asks macOS for Photos access. The bridge uses PhotoKit and does
not read `Photos Library.photoslibrary` directly.
