# Phase 05-07: Native read-only foundation

This phase turns the Phase 0-4 Android shell into a useful native read-only app surface.

## Phase 05: Android data and repositories

- Adds Room entities for chroots, checks and the Home snapshot.
- Adds DAOs for chroot state, check state and dashboard snapshots.
- Adds `BridgeRepository`, the first Android-side repository that talks to the fixed root bridge.
- Caches dashboard, chroot and operation state so the UI can render the last useful view while refreshes run.
- Adds protocol envelope parsing for object and array responses.
- Adds a Python `operations.list` bridge query so the Activity screen can hydrate without starting a job.

## Phase 06: Navigation shell and feature screens

- Replaces placeholder foundation tabs with dedicated screens:
  - Home
  - Chroots
  - Activity
  - Tools
- Keeps the compact bottom bar and wide navigation rail from the DustUI-derived shell.
- Splits reusable UI pieces into `ui/components`.
- Keeps all static UI copy in resources for lint cleanliness.

## Phase 07: Home and Quick Start replacement

- Home now collects root bridge status, backend capability status, chroot count, operation count and warning count.
- Adds readiness rows for root bridge, backend, chroots and operations.
- Adds a recommended next action based on root availability, active operations, failures and first-run state.
- Chroots, Activity and Tools are now read-only native replacements for their first WebUI surfaces.

## Guardrails

- SDK remains 36.
- WebUI remains in place as a compatibility layer.
- No WebView is introduced.
- No arbitrary shell AIDL method is introduced.
- No broad storage permission is introduced.
- Mutating operations remain for later phases.
