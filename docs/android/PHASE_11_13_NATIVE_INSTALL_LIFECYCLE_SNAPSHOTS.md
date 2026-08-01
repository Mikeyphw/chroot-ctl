# Phase 11-13: Native install, lifecycle previews, snapshots and recovery

This phase moves the next WebUI replacement block into the native Android app while keeping the Python backend authoritative.

## Phase 11

- Adds `install.form`, `install.preview`, and `install.run` to the versioned bridge.
- Adds a native Compose install screen with editable distro, name, username, profile, desktop and mirror fields.
- Runs installation through the foreground operation service instead of a browser job.

## Phase 12

- Adds lifecycle previews for start, restart, remove and upgrade planning.
- Adds foreground start and restart operations.
- Adds guarded remove execution contract requiring typed confirmation in the bridge payload.

## Phase 13

- Adds `snapshots.list`, `snapshots.preview`, `snapshots.create`, `snapshots.restore`, and `snapshots.export` bridge contracts.
- Adds native snapshot and recovery controls to chroot detail.
- Keeps destructive restore and remove guarded by explicit confirmation at the bridge layer.

The WebUI remains present only as compatibility surface. No WebView, arbitrary shell AIDL, broad storage permission or package-query permission is introduced.

## Phase 13B caveat closure bundled into this overlay

The native UI now closes the two deliberate gaps from the first Phase 11-13 pass:

- Chroot removal is no longer bridge-only. The Lifecycle panel includes a typed confirmation field and dispatches `chroots.remove.execute` only when the entered text matches the selected chroot name.
- Snapshot restore and export are no longer bridge-only. Snapshot rows expose preview and execution actions for restore and export. Restore requires typing the selected chroot name before the foreground operation can start.
