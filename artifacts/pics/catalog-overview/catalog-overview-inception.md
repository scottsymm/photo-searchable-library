---
title: Catalog Overview
tags:
  - inception
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
incepted: 2026-09-15
---

# Catalog Overview

## Idea

The Photos page today is a source-diagnostics view whose headline numbers mix different populations — mounted-folder files, Apple Photos imports, processed assets — so counts appear to contradict each other (466 "files indexed" beside 4,968 imported and 8,105 in Apple Photos) and the real state of the library stays hidden. Catalog Overview redefines the page as a holistic reflection of the photo catalog and its connections: a rollup processing funnel at the top shows where every asset is and where work is stuck, with each source (Apple Photos first) presented as a readiness gate feeding that funnel. Below the funnel, contextual blocks show what processing actually produced — recent imports, faces and people, places. The page serves the Pics owner-operator, who needs to trust the numbers at a glance and debug ingest problems without opening logs.

## Goal

Success criteria:

- "How many assets do I have, and is everything processed?" is answerable at a glance — no mental math across cards.
- Missing work is visible as funnel drop-off (discovered versus searchable), not hidden between per-source counters.
- A source that is unauthorized, disconnected, or has unknown inventory shows an explicit state — never a misleading zero.
- Every count is labeled with its population and freshness ("as of last sync"), so numbers never appear to contradict each other.
- Failures are readable with enough detail to debug (error message, failed counts, timestamps) — read-only in v1.
- All funnel stages are computed from existing tables (`assets`, `jobs`, `content_embeds`, `source_syncs`, `sources`) as per-source queries summed into the rollup — no dual bookkeeping.

v1 feature list:

- Rollup funnel: Discovered → Ready to import → Importing → Imported → Processing → Searchable → Failed/Blocked, as a sum of per-source stage counts.
- Per-source drill-down under each stage (Apple Photos, mounted folder, uploads).
- Source readiness states: not configured / authorization required / connected, inventory pending / connected / failed — with last-known inventory preserved on failure.
- Apple Photos actions retained on the page (sync latest, full sync) with live sync state and last error.
- Freshness labels on discovered counts; importing labeled as approximate in-flight progress.
- Context blocks framed as "what the catalog gained": recent imports; faces and people (assigned versus unassigned); places (with versus without location).
- Open: precise per-asset failure counts require a per-asset failure model — post-v1 decision.
- Open: no timeline stated.

## Interview Results

**What's the idea?**
i expect the photos page to be a reflection of the photo assets and connections. the actions around the apple photo libary are still needed. that might be just one example of showing the user what state things are in.

**What should the page help the user understand first: the contents of the catalog, the health of connections, or whether processing is complete?**

Total assets or assets that are importable, or assets that are still importing or processing etc is kind of like the top of the funnel and should kind of indicate where things are and maybe where issues are. and the other things you mentionned are important for context

**Which asset facts are most valuable at a glance? For example, total assets, photos versus videos, searchable assets, faces and people, locations, recent imports, or assets still processing.**

**How should the funnel be defined from the user's perspective? Which stages should be visible, such as discovered, ready to import, importing, imported, processing, searchable, or failed?**

those funnel steps seem correct if they can map to current concepts in the code and also maybe a state for things like the apple library before it's connected ? i am not sure where that maps in the funnel

**How should the page distinguish a source connection state from an asset processing state?** For example, should an Apple Photos library that is not yet authorized appear as a separate source readiness state or as zero discovered assets in the funnel?

**When a source is connected but its total is not yet known, should the page show an explicit “waiting for source inventory” state rather than treating it as empty?**

**When the page shows an issue, what should the user be able to do immediately: retry the affected work, reconnect a source, inspect failures, pause processing, or simply understand that work is still in progress?**

**Should the funnel represent all assets Pics can discover from connected sources, or only assets that Pics has already accepted into its catalog?**

**Funnel granularity — one combined funnel or per-source?**
top level numbers seem to make it easier to see missing data, but you of course need to drill down to know what is going on. and if rollup numbers create tech debt or too much complexity, keeping separate is ok too

Recommendation given: rollup funnel at top with per-source drill-down, implemented as a sum of per-source stage queries (single source of truth, no dual bookkeeping). Caveats: discovered counts are only as fresh as the source's last report; importing is approximate in-flight progress; failed is tracked per sync/job today, not per asset — precise per-asset failure counts are a v1 scoping decision.

**Which connections should the page anticipate beyond Apple Photos, and should each connection expose actions directly on this page or link to a dedicated settings/source view?**

**When the page shows failures, what should the user be able to do from this page in v1?**
i think read only is fine for now on failure with enough information to debug.

**Should the design anticipate future connections beyond Apple Photos and the mounted folder?**
support for future connections is good if the abstraction does get too complicated.

**Below the funnel, which contextual blocks matter most in v1?**
knowing what was imported and made it into the catalog, and whether it added to faces/people or locations seems most important, but open to suggestions

## Timeline
No timeline or deadline stated during inception.
