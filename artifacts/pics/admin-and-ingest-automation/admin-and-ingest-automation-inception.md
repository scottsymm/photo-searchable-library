---
title: Admin and Ingest Automation
tags:
  - inception
  - admin-and-ingest-automation
  - ingest
  - admin
  - self-hosted
keywords:
  - photo import
  - watch folder
  - backfill
  - docker mounts
  - admin page
  - no silent processing
  - job status
  - clustering
incepted: 2026-09-10

# Admin and Ingest Automation

## Idea

One self-hosted library that never touches, reads, or indexes photos until the
user explicitly says so. On first launch the app is "parked": watch, embedding,
indexing, and face clustering are all off. The admin page is the single place to
enable and understand ingest — configure the Pictures directory (default
`~/Pictures`), decide whether watch backfills existing photos or only imports
new ones, and see status, progress, and history for every job. Manual uploads
always stay available.

## Goal

Success criteria:

- On first launch the app processes nothing automatically; a prominent
  "not configured" notice links to the admin page.
- The admin can enable watch for a configured Pictures directory (default
  `~/Pictures`), with a choice between backfilling existing photos or watching
  only new files.
- The admin can start and see status/progress/failures for embed/index and
  clustering jobs. Cancel/pause is out of scope for v1.
- The status dashboard shows worker/model state plus catalog counts.
- Manual upload continues to work independently of watch.
- No background flow begins without an explicit user action.

v1 feature list:

- Parked/setup state on first launch with prominent notice + link
- Admin page with sections: Watch/Ingest, Embed/Index jobs, Clustering, Status
- Watch toggle (on/off) and Pictures directory display (default `~/Pictures`)
- Backfill mode selection (backfill existing vs. new files only)
- Documentation for restarting Docker to change the mount point
- Manual upload available independently
- Job status/progress/failure visibility (start + view; cancel/pause deferred)
- Clustering queue/rerun and review surface
- Status dashboard (worker/model state, catalog counts, disk usage)

## Interview Results

**What's the idea, broadly?**
When running the platform I want to be forced to configure via an admin page to ingest photos and other features. Are we required to copy photos to a volume or do we watch the mounted library?

**Should we copy photos, or watch a mount?**
Both. I want the user to configure the Pictures directory before watching starts.

**What's the importance of knowing the mount before starting Docker?**
Maybe we default to `~/Pictures`, and the admin UI shows that and shows documentation about how to restart Docker with a different mount point. In either case the intent is the admin user has control of when the feature starts.

**Should copy-upload still exist?**
Yes, copy-upload can be used in addition to watch.

**What should happen on first run before ingest is configured?**
A prominent "not configured" notice with a link — not a hard blocker. The app remains usable; the notice guides the admin to set up ingest.

**How should watch-mode backfill behave when first enabled?**
Make backfill configurable: the admin chooses whether to import all existing photos in the watched directory on first enable, or only watch new files going forward.

**What's the real concern behind the forced setup?**
My concern is that the app does not start reading photos and clustering or indexing etc. before the user has a chance to confirm and know what is going on. There is always the ability to know what is happening before anything runs.

**Which 'no silent processing' shape feels right for v1?**
Parked on first launch. The app shows a setup/park state; watch, embed, and cluster stay off until the user explicitly enables them. Upload stays available. The user also has the ability to configure whether watch does a backfill.

**Which flows should the admin page control or surface for v1?**
Watch/ingest (toggle on/off, backfill or new-only, Pictures path), embed/index jobs (run, see status, cancel), clustering (queue, rerun with thresholds, see review), and a status dashboard (worker model status, catalog stats, disk usage).

**What's the strongest test that this feature works?**
All of those are defining-done candidates: backfill finishing with all photos searchable and face clusters available to review; new photos dropped in the watched folder becoming searchable without a restart; and the user being able to enable/disable each flow and see a full history of what ran.

## Timeline
(Consider the time taken to complete the task. Include any timelines or deadlines that are expected, but leave placeholders during the interview.)

**Is cancel/pause in scope for v1?**
No — v1 ships start, status/progress, and failure visibility for embed/index jobs. Cancel and pause are deferred follow-ups.