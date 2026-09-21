# Root-module Android-retirement WR09/12 — Maintenance, support, and recovery

WR09 replaces Android's Repair/Support workspace with root-module-native WebUI surfaces.

- `system.runtime` and `system.module_status` expose root-module/runtime health without Android flattening.
- Support export is `support.preview` -> proof-bound `support.bundle`; WebUI never accepts an arbitrary output path. Backend publishes a sanitized managed `tar.gz`, checksum, artifact identity, TTL registration, and audit event.
- Temporary cleanup is `cleanup.temp_preview` -> proof-bound `cleanup.temp`, limited to managed temporary artifacts.
- Registry repair is explicitly global, not presented as a selected-chroot action.
- Repair scan preserves the full recommendation inventory. Selected plans preserve item ID, action, path, expected path, impact, exact diff lines, destructive warnings, and next-step summary.
- All execution paths require fresh preview proof and expose persistent-operation cancellation.
