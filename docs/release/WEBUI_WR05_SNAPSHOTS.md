# WebUI Android-retirement WR05/12 — Snapshots

WR05 replaces Android's snapshot workspace with the same backend authority.

- `snapshots.list` drives the recovery-point inventory.
- Create, restore, and export require `snapshots.preview`.
- `snapshots.create`, `snapshots.restore`, and `snapshots.export` require preview proof.
- Restore requires exact chroot-name confirmation.
- Preview exposes mounted-target, missing-snapshot, duplicate-name, and legacy/non-metadata-faithful blockers from the backend.
- Persistent NDJSON operation progress and cancellation are surfaced.
- Snapshot kind, size, creation time, note, and authority metadata are rendered.
- Export supports the backend-managed default destination and an optional explicitly preview-bound archive path.
