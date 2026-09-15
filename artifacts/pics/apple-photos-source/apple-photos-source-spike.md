---
title: Apple Photos Source — Spike Findings
tags:
  - discovery
  - apple-photos-source
  - apple-photos
  - photokit
  - macos
keywords:
  - Apple Photos
  - PhotoKit
  - PHAsset
  - PHAssetResourceManager
  - macOS bridge
  - iCloud Photos
  - source adapter
created: 2026-09-15
updated: 2026-09-15

# Apple Photos Source — Spike Findings

## Summary

A native macOS command-line helper can access the user's Apple Photos library
through PhotoKit without traversing `Photos Library.photoslibrary` through
Docker. The spike successfully authorized, enumerated 8,105 assets, extracted
representative image and video bytes, and uploaded one extracted image through
the existing Pics API.

This validates the recommended architecture: keep the Docker services as the
indexing and search system, and add a native macOS bridge as the Apple Photos
source adapter.

## Prototype

Temporary prototype location:

```text
/var/folders/84/6zphkb3x4_v2zbq0jjk7k9hr0000gn/T/opencode/apple-photos-spike
```

The prototype used:

- Swift 6.4 command-line executables
- `PHPhotoLibrary.requestAuthorization(for: .readWrite)`
- `PHAsset.fetchAssets`
- `PHAssetResource.assetResources`
- `PHAssetResourceManager.writeData`
- Existing `POST /assets/upload`

No repository production code was changed for the spike.

## Results

### Authorization

Result:

```text
authorization=authorized
```

A command-line Swift process can request and receive Photos access. This means
the first bridge does not need to be a full GUI application to prove the core
integration.

### Enumeration

Result:

```text
asset_count=8105
```

The helper can enumerate the real Apple Photos library even though Docker cannot
traverse the `.photoslibrary` package.

Observed asset metadata includes:

- Stable-looking `PHAsset.localIdentifier` values such as
  `D4C76C89-1D86-47B1-99A5-8D986A78C7D7/L0/001`
- Media type
- Creation date
- Location presence
- Favorite flag
- Hidden flag
- Resource uniform type identifiers and original filenames

Observed resource examples:

- `public.jpeg`
- `public.heic`
- `com.apple.quicktime-movie`

Live Photos appear as an image asset with both HEIC and QuickTime resources.

### Extraction

Representative image extraction succeeded:

```text
resource[0] uti=public.jpeg file=IMG_1321.JPG bytes=2526207
```

Representative video extraction succeeded:

```text
resource[0] uti=com.apple.quicktime-movie file=IMG_1267.MOV bytes=645536
```

`PHAssetResourceManager` can write real media bytes to disk with network access
enabled. This is the right extraction boundary for a bridge because it avoids
reading Apple's private package/database layout directly.

### Pics API handoff

One extracted image was uploaded through the existing API:

```json
{"job_id":4,"status":"queued","path":"/library/imports/9b1336a88ba04e84830d76ce435129b0.jpg"}
```

The worker completed the import:

```json
{"id":4,"kind":"import","status":"done","progress":1.0,"error":null}
```

The existing upload/import pipeline can accept media produced by the bridge.

## Key Decisions Supported

1. **Use PhotoKit, not direct package traversal.** Docker filesystem access to
   `.photoslibrary` is unreliable and does not expose the Apple Photos data
   model.
2. **Use a native macOS bridge.** The bridge owns Photos authorization and
   media extraction; Docker remains responsible for indexing, embeddings, and
   search.
3. **Use `PHAsset.localIdentifier` as the source asset identity.** The catalog
   should store it separately from filesystem paths.
4. **Extract through `PHAssetResourceManager`.** This supports original media
   resources and can request network access for iCloud-backed assets.
5. **Start with asset import, not full metadata parity.** Albums, edits, Apple
   People, and deletion propagation should be later phases.

## Remaining Unknowns

- Whether `localIdentifier` remains stable across all library migrations and
  iCloud account changes. It is stable enough for the Phase 1 design, but the
  schema should keep it scoped to an `apple_photos` source.
- How large iCloud-only libraries behave during bulk extraction. The bridge
  needs throttling, progress, cancellation, and retry behavior.
- Whether a long-running background helper should be a CLI, LaunchAgent, or
  menu-bar app. A CLI is sufficient for Phase 1; a user-facing app may be better
  for permissions and lifecycle later.
- How much Apple Photos metadata should be imported in Phase 1. Creation date,
  location, favorite, hidden, media type, and original filename are readily
  available.
- How edits and Live Photo video components should be represented. Phase 1
  should import the primary image/video resource and preserve resource metadata.

## Recommendation

Proceed to a formal Phase 1 implementation plan for a native Apple Photos
bridge.

Phase 1 should include:

- Source model for `apple_photos`
- Stable source asset IDs
- PhotoKit authorization and enumeration
- Original resource extraction
- Upload/import handoff to the existing API
- Sync status and error reporting
- Basic duplicate handling by source ID and content hash

Phase 1 should explicitly defer:

- Albums
- Apple People import
- Edit/rendition selection
- Deletion propagation
- Background daemon packaging
- Menu-bar UI
