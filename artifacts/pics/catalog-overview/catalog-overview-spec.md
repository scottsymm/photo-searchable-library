---
title: Catalog Overview — Spec
tags:
  - spec
  - catalog-overview
  - photo-management
  - dashboard
keywords:
  - Pics
  - photo catalog
  - processing funnel
  - source connections
  - Apple Photos
  - sync status
  - faces
  - places
distilled: 2026-09-15
---

# Catalog Overview — Spec

## Problem Statement

The Photos page is a source-diagnostics view masquerading as a catalog view. Its headline numbers mix different populations — mounted-folder files, Apple Photos bridge imports, processed assets — so counts appear to contradict each other (466 "files indexed" beside 4,968 imported and 8,105 in Apple Photos) and trust in the numbers erodes. There is no single place to answer: "what is in my catalog, where is everything in the pipeline, and what needs my attention?"

## Target Audience

The Pics owner-operator: a single user running Pics locally, importing from Apple Photos and a mounted folder, who checks the page to confirm imports are progressing and to spot problems. This user is technical enough to act on debug detail (error messages, counts, timestamps) but should not need to read logs or query the database to understand catalog state.

## Core Value Proposition

One page that tells the truth about the catalog. A rollup processing funnel shows where every asset is — Discovered → Ready to import → Importing → Imported → Processing → Searchable → Failed/Blocked — so missing or stuck work is visible as funnel drop-off rather than buried in per-source counters. Source connections (Apple Photos first) are shown as readiness gates feeding the funnel, and contextual blocks below show what processing actually produced: recent imports, faces and people, places.

## MVP Scope

**Funnel (top of page)**

- Rollup funnel across all sources, computed as a sum of per-source stage queries against existing tables (`assets`, `jobs`, `content_embeds`, `source_syncs`, `sources`) — one source of truth, no dual bookkeeping.
- Stage mapping:
  - Discovered: `sources.asset_count` per source + mounted-folder media scan
  - Ready to import: discovered minus known `assets.source_asset_id` per source
  - Importing: active `source_syncs` (queued/running) — approximate, labeled in-flight
  - Imported: `assets` rows, `deleted = 0`
  - Processing: import `jobs` queued/working
  - Searchable: assets with `content_embeds` rows
  - Failed/Blocked: error/partial `source_syncs` and failed jobs — approximate in v1
- Per-source drill-down under each stage (Apple Photos, mounted folder, uploads).
- Freshness labels on discovered counts ("as of last sync"); discovered totals are only as current as the source's last report.

**Source readiness (gates around the funnel)**

- Explicit states: not configured / authorization required / connected, inventory pending / connected / failed.
- Unknown inventory is shown as unknown — never as zero assets.
- On connection failure, last-known inventory is preserved and shown alongside the failure state.
- Apple Photos actions retained on the page: sync latest, full sync, live sync state, last error.

**Failure display (read-only in v1)**

- Failures are visible with enough detail to debug: error message, failed counts, timestamps.
- No retry/reconnect actions beyond the existing Apple Photos sync buttons in v1.

**Context blocks ("what the catalog gained")**

- Recent imports: latest assets that made it into the catalog, with source attribution.
- Faces and people: faces detected, assigned versus unassigned to people.
- Places: assets with versus without location data.

**Explicitly out of scope for v1**

- Per-asset failure tracking (precise "failed assets" counts) — requires a per-asset failure model.
- Retry/reconnect/inspect actions beyond existing sync controls.
- A generic plugin system for future sources — design to the existing source interface only.

## Success Metrics

- "How many assets do I have, and is everything processed?" is answerable at a glance — no mental math across cards.
- Missing work is visible as funnel drop-off (discovered versus searchable), not hidden between per-source counters.
- Zero apparently-contradictory numbers on the page: every count is labeled with its population and freshness.
- Unauthorized or disconnected sources show explicit states, never misleading zeros.
- Ingest issues are diagnosable from the page without opening logs.

## Key Risks & Open Questions

- **Discovered freshness:** bridge-reported totals update only on sync; the mounted scan is cached. Mitigate with "as of" labels rather than implying live data.
- **Importing precision:** Apple Photos assets get asset rows only on upload, so mid-sync counts come from sync progress, not asset rows. Acceptable for a funnel if labeled in-flight.
- **Failed precision:** failures are tracked per sync/job, not per asset. v1 shows approximate, read-only failure state. Open: is a per-asset failure model worth adding post-v1?
- **Future-source abstraction:** the funnel and readiness model should generalize to new sources through the existing source interface; do not build a plugin system.
- **Timeline:** none stated.
