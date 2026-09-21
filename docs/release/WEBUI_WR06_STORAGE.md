# WebUI Android-retirement WR06/12 — Storage and managed artifacts

WR06 adds the Android storage/artifact authority to WebUI:

- `storage.status` reports rootfs/cache/snapshot usage, filesystem capacity, reliability flags, and mount mismatch state.
- `transfer.artifact_root` exposes the backend-managed transfer root.
- `artifacts.list` renders managed artifacts only.
- Destructive cleanup requires `artifacts.cleanup_preview`, proof binding, and `artifacts.cleanup`.
- Cleanup supports one managed artifact or all managed artifacts and never exposes arbitrary filesystem deletion.
- Persistent operation progress and cancellation are surfaced.

This overlay is the roadmap midpoint validation gate: unlike WR01–WR05, validation is required and should be run through the dedicated `chrootctl_webui` Devtool target.
