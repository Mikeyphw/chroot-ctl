# CHR09 — Metadata-faithful snapshot subsystem

CHR09 closes the snapshot fidelity and authority layer after Gate A and CHR08.
It owns D16 and D17 and records supporting work for later install/upgrade and
Android UI/storage overlays without double-counting those owners.

## Closure accounting

Closed by this overlay:

- D16 — Snapshots/imports do not preserve rootfs filesystem metadata faithfully
- D17 — Snapshot storage/recovery workflow has split authority or unsafe preconditions

Exact implemented count: 2 canonical findings / 16 source manifestations.

Supporting-only work recorded:

- U010 remains CHR19-owned; CHR09 supplies unique snapshot naming and provenance.
- U139, U140 and U141 remain CHR11-owned; CHR09 supplies the managed snapshot primitive that install/upgrade will consume.
- U152, U155 and U156 remain CHR07-owned; CHR09 extends snapshot/import integration over the safer transaction foundation.

## Snapshot storage authority

The managed snapshot root is now the configured `snapshot_dir` from the base
configuration. `SnapshotService.Root()` no longer hardcodes
`<chroot_root>/.snapshots`; storage/status/restore/export/list now use one
snapshot authority. Existing legacy snapshot rows outside that authority are
listed with metadata marking them as legacy/external and are refused for restore
or export until migrated/recreated.

## Metadata fidelity

The previous directory copy implementation was removed from the snapshot path.
Snapshots now publish a managed directory containing:

- `manifest.json` with the snapshot schema, chroot identity, snapshot identity,
  source path, creation time, note, metadata contract, and optional protected
  operation provenance; and
- `rootfs.tar.gz`, a metadata-preserving tar payload.

The Linux/Android archive primitive preserves UID/GID, setuid/setgid/sticky
bits, access/modification times, xattrs/ACL/capability carrier metadata,
hardlink identity, symlinks, FIFOs, device nodes where the platform allows them,
and sparse zero ranges. Live socket entries are refused because they represent
runtime state rather than restorable rootfs state.

Transfer import now extracts `chrootctl-rootfs-v1` tar members through the same
metadata-restoring primitive instead of recreating entries with permission bits
only. Transfer export invokes tar with numeric-owner, ACL, xattr, sparse, and
one-file-system flags where supported.

## Snapshot transactions and recovery

Snapshot creation now writes into a private partial directory, writes and fsyncs
the payload and manifest, fsyncs the staging directory, atomically renames into
the managed snapshot namespace, verifies the manifest, then registers the row.
The filesystem mutation journal remains nonterminal until both the managed
filesystem namespace and registry row agree.

Snapshot restore verifies the selected snapshot is managed and metadata-faithful,
including the complete CHR09 metadata contract recorded in the manifest. It
requires the target to be fully unmounted, extracts into a staged target, moves
the previous rootfs to a backup when present, promotes the staged rootfs, fsyncs
the parent directory, and records cleanup debt if removing the previous backup
fails. Legacy snapshots are refused for restore so a metadata-lossy copy cannot
be promoted as a safe recovery point.

## Operation provenance and Android recovery

Bridge-dispatched snapshot operations now attach operation provenance to the Go
context. Snapshot manifests and registry metadata carry the protected operation
ID and operation kind when a safety snapshot is created for a later destructive
workflow. Android recovery selection now requires a matching provenance-aware
snapshot rather than blindly selecting the newest snapshot for any failed or
blocked operation.

The Android snapshot workspace also gets a collision-resistant default snapshot
name, refreshes the snapshot pane after successful snapshot operations, surfaces
metadata-faithful kind/provenance fields, and can hand a managed snapshot export
artifact to the existing SAF CreateDocument flow. The Activity event reducer now
persists the `operation_succeeded` result payload so `snapshots.export` keeps the
`exported_archive` path emitted by the native operation manager.

## Normal CLI parity

The generated CLI contract now exposes a normal `snapshots` command family:

- `snapshots list`
- `snapshots create [SNAPSHOT] [--note NOTE]`
- `snapshots restore SNAPSHOT [--yes]`
- `snapshots export SNAPSHOT [ARCHIVE]`

The CLI uses the same managed snapshot service as Android/bridge, so preflight,
restore, export, metadata format, and storage authority no longer diverge by
surface.

## Validation

`repoctl validate` and final seal now run `ValidateSnapshotFidelity`, which
seals the metadata-preserving archive primitive, the single snapshot storage
authority, normal CLI snapshot commands, operation-provenance wiring, Android
recovery gating, exact D16/D17 closure accounting, and ownership boundaries for
supporting-only findings.
