---
title: Apple Photos Connection Progression
tags:
  - inception
  - apple-photos-progression
  - apple-photos
  - bridge
  - ux
keywords:
  - Photos bridge
  - PhotoKit authorization
  - library detection
  - sync progression
  - source readiness
incepted: 2026-09-15
---

# Apple Photos Connection Progression

## Idea

> Guide the user from a detected Apple Photos library through bridge startup, authorization, inventory, and the first import instead of presenting sync controls before the bridge is ready.

## Goal

> Make the Apple Photos source truthful and actionable with server-backed bridge presence, progressive UI states, and a clear first-sync path.

## Interview Results

- A `.photoslibrary` bundle detected by Docker is evidence that the library is mounted, not proof that PhotoKit access is authorized.
- The UI should lead with the next action and reveal bridge startup instructions progressively.
- Sync controls should become primary after the bridge reports authorization and inventory.
