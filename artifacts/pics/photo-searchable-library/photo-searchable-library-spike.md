---
title: Photo Searchable Library — Spike findings
tags:
  - spike
  - photo-searchable-library
  - computer-vision
  - sqlite-vec
  - exiftool
keywords:
  - photo metadata extraction
  - CLIP embedding pipeline
  - face recognition clustering
  - sqlite-vec
  - HEIC decode
  - PyExifTool
  - vector search
created: 2026-09-10
updated: 2026-09-10
---

# Photo Searchable Library — Spike

Validates the riskiest assumptions behind the implementation plan before
execution. Two spikes run against a scratch venv
(`$TMPDIR/opencode/pics-spike`) and, for the second, the user's real photo
library. Findings are folded back into `<slug>-plan.md`.

## Spike 1 — library primitives (no real photos)

Environment: `uv venv` on Python 3.12, macOS arm64.

### 1.1 sqlite-vec 0.1.9 — KNN query syntax ✓

```sql
CREATE VIRTUAL TABLE vec0_content USING vec0(content_embed float[512]);
INSERT INTO vec0_content(rowid, content_embed) VALUES (1, ?); -- rowid = asset_id
SELECT rowid, distance FROM vec0_content WHERE content_embed MATCH ? ORDER BY distance LIMIT 2;
```

- Returns `(rowid, distance)` ascending. `distance` is **Euclidean**.
- Delete-then-insert on a rowid re-indexes correctly (no duplicate rows).

**Implication:** the plan's `embeds.py` query shape is correct; no ANN index
needed at 20k.

### 1.2 CLIP ViT-B/32 embeddings ✓ (with a breaking API gotcha)

- `transformers>=5`, `CLIPModel.from_pretrained("openai/clip-vit-base-patch32")`
- Image + text features are **512-dim**.
- Throughput on Apple Silicon CPU: batch-8 ≈ **10 ms/image** → ~4–6 min for 20k.

**Gotcha (would have crashed the plan):** in transformers 5.x,
`get_image_features()` / `get_text_features()` return a
`BaseModelOutputWithPooling`, **not** a tensor. `.pooler_output` is required.

### 1.3 reverse_geocoder — offline ✓ (signature corrected)

- `import reverse_geocoder` ≈ 5 s; **no network** on first use (ships its own
  GeoNames gazetteer).
- Correct API: `reverse_geocoder.search([(lat, lon)], mode=1)` →
  `[{'name': 'London', 'cc': 'GB'}]` (list of dicts; a bare tuple fails).

### 1.4 ExifTool — not installed by default ✓ (gotcha)

- macOS: `brew install exiftool` is required (apt in Docker).
- Numeric GPS needs `-n`. With `-n`, `GPSLatitude`/`GPSLongitude` return as
  **unsigned floats**; the sign lives in `GPSLatitudeRef`/`GPSLongitudeRef`
  (`S`/`W` → negate). Without the ref, west/south coords come back positive.

### 1.5 insightface buffalo_l — CPU ✓ (first-run download)

- `FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])` works
  on CPU-only; ~87 ms per empty 640×480 frame; 512-dim `normed_embedding`.
- **First run downloads ~280 MB from GitHub releases** (deepinsight/insightface
  model zoo), not HuggingFace. Worker needs network on first start; cache
  thereafter (`models/` volume).

## Spike 2 — Real library + real Docker

### 2.1 Library composition — shapes the design

Counted across `~/Pictures` (incl. `Photos Library.photoslibrary`):

```
2333 heic   978 jpeg/jpg   358 mov   (no RAW)
```

**HEIC + video are the majority**, not an edge case. Pillow alone cannot open
either: `pillow-heif` (regular-opens HEIC) + ffmpeg (video frames) are
mandatory.

### 2.2 HEIC decoding ✓

- `pillow_heif.register_heif_opener()` then `Image.open()` opened a real
  4284×5712 HEIC; thumbnailed to a 54 KB JPEG in-memory. No system libheif on
  the macOS wheel path.

### 2.3 MOV frame extraction ✓

- `ffmpeg -loglevel error -i video.mov -frames:v 1 -f image2pipe -vcodec mjpeg -`
  returned a ~72 KB JPEG with rc 0. Requires `brew install ffmpeg`.

### 2.4 Real face detection ✓, and a hard truth about identity ✗

- A real 2.1 MB photo: **2 faces** detected in 287 ms (det scores 0.89/0.84),
  512-dim embeddings.
- But this library is overwhelmingly **group shots (2–4 faces per photo)**.
  Cross-photo cosine similarity among "same folder" faces ranged **0.00–0.31**
  because they're different people in group scenes.

**Implication:** a naive cosine threshold will NOT cluster people here.
Hierarchical clustering + human merge/split review is **required**, not a
nice-to-have. Face identity is the single highest-risk feature; the People page
is a first-class deliverable.

### 2.5 The ExifTool Python wrapper — plan bug caught

- The plan's `exiftool-py` **does not exist on PyPI** → the Docker build failed.
- Real package: **`PyExifTool` 0.5.6** (`from exiftool import ExifToolHelper`).
- Validated: `ExifToolHelper(common_args=["-n"])` returns GPS as numeric floats.

### 2.6 Docker build of the worker image ✓

- `python:3.12-slim` + apt `exiftool ffmpeg` + torch-CPU + transformers +
  insightface + onnxruntime + sqlite-vec + PyExifTool + reverse-geocoder +
  pillow-heif → builds clean, all imports resolve.
- Final image: **2.99 GB** — keep model/HF caches on a volume.
- Docker build context must be the **repo root** (`COPY packages/core` after
  root context); `COPY ../../packages/core` is invalid in Docker.

## Decision log (changes to the plan)

| Plan artifact | Change |
|---|---|
| `packages/core/embeds.py` | Query shape confirmed; no change. |
| `services/worker/models.py` | Use `.pooler_output` on transformers >= 5 returns. |
| `packages/core/geo.py` | `search([(lat, lon)], mode=1)`, note offline. |
| `services/worker/exif.py` | `ExifToolHelper(common_args=["-n"])`, apply `GPSLatitudeRef`/`GPSLongitudeRef` signs; drop `size_class`. |
| worker `pyproject.toml` | `exiftool-py` → `PyExifTool>=0.5.6`. |
| worker `Dockerfile` | Repo-root context; `libheif-dev` dropped (wheel); ~3 GB noted. |
| `docker-compose.yml` | `build: {context: ., dockerfile: services/worker/Dockerfile}`; `HF_HOME=/models`. |
| Plan `Spike Findings` | Both spike wave added; library-composition callout; face-clustering risk. |

## Remaining unknowns after spike 2

- Exact CLIP image → text retrieval quality on real photos (embed a few real
  images and test a real query) — cheap, suggest running during Task 10.
- Docker Compose full-stack bring-up (web+api+worker together) — only the
  worker image was built here.
- HEIC + MOV ingest in the actual pipeline (decode verified in isolation; the
  job plumbing not yet).