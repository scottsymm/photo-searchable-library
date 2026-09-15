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
