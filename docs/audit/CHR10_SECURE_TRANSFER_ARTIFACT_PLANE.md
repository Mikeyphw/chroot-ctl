# CHR10 — Secure transfer and managed artifact plane

CHR10 closes the transfer/import/artifact defects from the audit ledger.  The
implemented contract is intentionally narrow: any artifact that leaves or enters
the Android/root bridge is published under the managed transfer root, receives a
checksum sidecar when it can be imported later, and is visible through the same
registry-backed artifact plane that the CLI and Android UI query.

## Invariants

- `EnsureManagedTransferRoot` creates a real, non-symlink, private directory and
  every registered artifact path must be contained by it.
- `transfer export` writes archives through a partial file, renames into place,
  fsyncs the directory, writes an atomic `.sha256` sidecar, then registers the
  archive and checksum as managed artifacts.
- `transfer inspect` and `transfer import` require the `.sha256` sidecar, verify
  it before decompression, enforce compressed/expanded/member limits, and reject
  manifests that are not CHR09 metadata-faithful.
- `transfer import --dry-run` now performs checksum and manifest validation
  without mutating the filesystem.
- A committed import runs `chroots validate-import` semantics before returning
  success and cleans the staged managed import plus checksum sidecar afterward.
- Android SAF import staging publishes a checksum sidecar next to the staged
  archive so the Go importer can enforce the same trust rule on phone transfers.
- `artifacts list`, bridge `artifacts.list`, smoke results, support bundles, and
  module builds all use the managed artifact registry instead of ad-hoc paths.
- Cleanup removes checksum sidecars and reports unlink errors instead of deleting
  registry rows while files remain on disk.

## Validation

The CHR10 source seal is executable through `repoctl validate` and lives in
`internal/repoctl/transfer_artifact_plane.go`.  It checks the Go services,
bridge, Android root service, CLI contract, and audit coverage ledger so future
patches cannot silently reopen the artifact-plane gaps.

## v2 edge-case hardening

- Bridge support-bundle previews now validate custom archive paths against the
  managed artifact root, matching module-build and smoke-artifact behavior.
- Smoke result artifact persistence returns a dry-run payload without attempting
  to register a file that was intentionally not written.
- Export progress emits the checksum phase once, so UI progress consumers do not
  receive duplicate publication events after the archive has already committed.
- Android descriptor transfers reject any reused transfer request id, including
  stale running state left by a root-service restart, instead of overwriting an
  old journal entry.
- Android checksum sidecar publication now removes failed partial sidecars in a
  `finally` block.
