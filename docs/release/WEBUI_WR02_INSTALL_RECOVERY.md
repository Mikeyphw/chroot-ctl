# WebUI Android-retirement WR02/12 — install advanced/recovery parity

WR02 closes the Android Install wizard gap for advanced install and recovery controls.

## Delivered

- Release and version overrides are editable and flow through the existing typed `install.preview` / `install.run` contract.
- Resume and Repair are explicit, mutually exclusive recovery modes.
- Overwrite existing is an independent explicit destructive opt-in.
- Distro/form refresh preserves the advanced draft instead of silently dropping recovery intent.
- Backend preview renders the normalized recovery mode, release/version, and authoritative `overwrite_existing` decision before Install is enabled.
- Retry after an install failure continues to obtain a fresh preview proof before rerunning the exact advanced/recovery payload.

The WebUI therefore exposes the advanced `InstallDraft` controls that existed in Android without introducing a second install execution path.
