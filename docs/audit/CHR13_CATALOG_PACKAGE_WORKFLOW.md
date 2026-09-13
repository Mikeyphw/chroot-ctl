# CHR13 catalog and package workflow

CHR13 closes the catalog/tools/package workflow findings from the full bug-hunt ledger. The overlay moves catalog actions from presentation-only metadata to executable domain state that the bridge, Android UI, and source gate all agree on.

## Closed findings

- `D23`
- `U047` through `U053`
- `U178` through `U184`

## Runtime invariants

- `sync-uid` is blocked as a catalog entry. The packaged script remains for compatibility and documentation, but previews and apply paths reject it before runner execution because UID/GID changes must go through the host-managed user identity service.
- Built-in and external catalog entries now carry source, script hash, rollback, risk level, destructive intent, confirmation requirement, and state reason.
- External catalog trust checks validate parent directories, reject symlinks and writable files, and re-stat manifests and scripts after reading to close simple TOCTOU windows.
- Python catalog scripts are no longer accepted by the parser because the apply runner only executes shell scripts.
- Arch catalog scripts use package database sync plus install, not full system upgrade, so a catalog add-on no longer unexpectedly upgrades the entire chroot.
- `winehq-staging` no longer reports success after installing a different Wine package.
- Package inventory now reports total count, requested limit, returned packages, and `truncated=true` when the bridge returns a partial list.

## Android UX invariants

- Built-in catalog rows expose blocked/installed/failed/available state instead of silently hiding problematic entries.
- Category chips are actual filters, not just labels.
- Target selection prefers installed chroot chips from authoritative chroot state, while still allowing a manual target when necessary.
- Apply remains disabled until a bridge preview approves `catalog.apply`.
- Package inventory explicitly warns when only a truncated package list is displayed.
