# Phase 23: Generated Artifact Purge

Phase 23 removes stale generated module output from the repository after the WebUI retirement.

## Why this exists

Phase 20-21 removed the WebUI source and module renderer paths, and Phase 22 sealed the release hardening contracts. The checked snapshot still carried old generated artifacts under `out/`, `tmpout/`, and zip files that contained WebUI binaries, webroot files, Playwright fixtures, and `src/chrootctl/web` payload copies.

Those generated directories are build products, not source of truth. Keeping them in the repository makes audits noisy and can trick future module/package checks into thinking the WebUI still exists.

## What Phase 23 enforces

- `out/` must not be committed.
- `tmpout/` must not be committed.
- `chrootctl-magisk.zip` must not be committed.
- `tmpmod.zip` must not be committed.
- `.gitignore` must ignore those generated outputs.
- WebUI retirement remains enforced after the purge.
- Android SDK remains pinned to 36.

## What still builds the module

`build.sh` remains the module build entry point. It renders a fresh module tree from `src/chrootctl/magisk.py`, validates it, then zips it. Fresh generated output is allowed during a local build, but it should not live in source overlays.

## Guardrail

The Phase 23 validator intentionally checks for broad stale generated-output roots rather than just WebUI filenames. This prevents future overlays from accidentally carrying old module output forward like a fossil in amber.
