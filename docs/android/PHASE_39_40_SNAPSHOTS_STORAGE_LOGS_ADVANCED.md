# Phase 39–40 — Focused recovery, storage, logs, and advanced workspaces

## Scope

Overlay H continues the selected-chroot workspace model from Phases 35–38. The top-level Chroots screen remains a launcher. Services and Users keep their focused Phase 37/38 behavior. Phase 39–40 separates recovery, disk state, logs, and technical diagnostics into dedicated rooms without changing the privileged native architecture.

## Snapshots and recovery

The Snapshots tab is recovery-first. It keeps the snapshot list compact, opens create/restore/export work inside an action review surface, and keeps restore protected by an exact chroot-name confirmation. Create, restore, and export use `snapshots.preview` for the exact reviewed snapshot name before execution is enabled. A preview from another action or snapshot cannot unlock the current review. A failed, interrupted, or blocked operation for the selected chroot surfaces a recovery entry point to the newest loaded snapshot instead of adding recovery controls to every row.

## Storage

Storage uses the allowlisted query `storage.status`. The backend returns only structured storage facts for one registered chroot: rootfs/cache paths and size estimates, filesystem free/used/total space, mount state/counts, and the snapshot directory. The Android room also shows the footprint of currently loaded snapshot records and warnings for stale state or a missing rootfs. Support information can be previewed and exported directly from Storage, with execution gated by the accepted support preview and reusing its archive path. Storage itself does not expose a command line or a storage mutation operation.

## Logs

Logs uses the allowlisted query `logs.list`. Android requests at most 200 lines; the bridge clamps all requests to 20–500 and accepts only DEBUG, INFO, WARNING, ERROR, or CRITICAL. The workspace exposes All/Warnings/Errors filters and optional five-second polling. Polling lives in a `LaunchedEffect` owned by the Logs composition, so leaving the tab cancels the polling coroutine. Recent persisted operations and read-only service journals are shown alongside the bounded chroot log. Opening Logs loads the selected chroot service list when needed, so journals do not depend on visiting the Services tab first.

## Advanced

Advanced is the technical room and danger zone. It keeps lifecycle removal confirmation, full doctor/status checks, runtime protocol/backend capabilities, a bounded raw bridge-payload viewer, support-bundle preview/export, and selective registry repair. Support export is enabled only after an accepted preview. Registry repair remains selection-based, preview-first, and executable only when the selected plan has an accepted repair preview.

## Warning closure

The Phase 38 Kotlin warning in `ChrootsScreen.kt` is fixed by pairing the resolved service and pending service action into one nullable review value. The redundant `pendingService != null && reviewAction != null` condition is removed rather than suppressed.

## Guardrails preserved

- compileSdk and targetSdk remain 36.
- Native Android + privileged RootService architecture remains intact.
- Root-module-first runtime discovery remains intact.
- RootService stdout/stderr stream draining remains intact.
- No WebView, HTTP server, or arbitrary-shell bridge is added.
- Phase 35–36 bridge response-shape adapters remain present.
- Phase 37 Services and Phase 38 Users workspace promises remain present.

## Audit closure r2

The delivery audit tightened three behaviors that marker-only validation could previously miss: snapshot execution is bound to the exact accepted preview and reviewed snapshot name, Logs loads the selected chroot service list on entry so journals are independently usable, and Storage exposes its own preview-gated support export while reusing the archive path returned by the accepted support preview. The Phase 32 compact-card snapshot preview contract remains source-compatible through a one-argument adapter at that legacy UI boundary.
