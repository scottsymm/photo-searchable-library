---
title: Admin and Ingest Automation — Spec
tags:
  - spec
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
distilled: 2026-09-10

# Admin and Ingest Automation — Spec

## Problem Statement

When the platform starts, it currently has the ability to scan, index, embed,
and cluster photos, but nothing is surfaced to the user about when these
features run. The user wants certainty that nothing reads their Photos,
generates embeddings, or clusters before they have seen what will happen and
explicitly enabled it. There is also no clear path for configuring ingest in a
Docker deployment (mount point vs. copy/upload).

## Target Audience

A single self-hosted user (the admin) who stores photos locally and wants
control over when the platform touches their library. The admin trusts the tool
but wants privacy-by-default: "no silent processing" is the core contract.

## Core Value Proposition

The app starts in a parked state and does nothing with the photo library until
the admin configures and enables it. The admin page is the single place to
understand and control ingest, embedding, indexing, and clustering — including
what runs, when, what it will touch, and its status.

## MVP Scope

**In scope:**

- Parked/setup state on first launch; no background processing by default.
- Prominent "not configured" notice with a link to the admin page (not a hard
  blocker; the app stays usable).
- Admin page with sections: Watch/Ingest, Embed/Index jobs, Clustering, Status.
- Watch toggle (on/off) and configurable Pictures directory, defaulting to
  `~/Pictures` and documented so Docker can be restarted with a different mount.
- Backfill mode selection when watch is first enabled: "backfill existing
  photos" vs. "watch new files only".
- Manual upload always available, independent of watch.
- Job status, progress, and failure visibility for embed/index and clustering
  jobs. Start and observe only; cancel/pause deferred.
- Clustering queue/rerun and review surface (reuses the face-clustering review
  plan).
- Status dashboard: worker/model state, catalog counts, disk usage.

**Out of scope (v1):**

- Watch new-file detection inside the worker (the worker runs jobs via the
  SQLite queue; the watcher polls or filesystem-watches the mounted dir and
  enqueues scans).
- Cancel/pause of running jobs.
- Multi-user admin roles.

## Success Metrics

- On a fresh launch, zero jobs are queued and nothing in the library is read.
- After the admin configures the Pictures directory and enables watch with
  backfill, existing photos become searchable, and face clusters are available
  for review.
- After backfill, new photos dropped in the watched folder become searchable
  without a restart.
- The admin can see, per flow, exactly what ran and its status/failure history.
- No flow begins without an explicit user action.

## Key Risks & Open Questions

- Mount point is fixed at Docker start; the admin page can only surface and
  document it, not change it live. The default `~/Pictures` must be baked into
  the compose file so the common case needs no customization.
- The worker runs jobs from the SQLite queue; a filesystem watcher must be
  introduced to detect new files. Backfill is a one-shot scan; live import is a
  watch loop. Both must be idempotent against the content-addressed catalog.
- Embedding and clustering are CPU/GPU-heavy; the admin should see expected
  duration and progress before starting.
- Deferred: cancel/pause operations on long jobs.