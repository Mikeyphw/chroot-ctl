# GO04 registry and transactional persistence

GO04 moves the persistence implementation behind `internal/registry` while
preserving the Python database contract byte-for-byte at the schema level.

## Compatibility invariants

- Existing `chroots.sqlite3` files are opened in place through GO02's SQLite
  compatibility layer.
- Every connection preserves 5s busy timeout, foreign keys, WAL and FULL
  synchronous mode.
- Legacy `snapshots` tables are upgraded only when no orphan rows would be
  discarded; orphaned data causes the same fail-closed error as Python.
- Chroot mutation batches use one immediate SQLite transaction and roll back
  fully on any invalid mutation or SQL failure.
- Chroot rename/delete continues to cascade to snapshots.
- JSON corruption is surfaced as `_corrupt` / `_field` metadata markers on
  reads rather than making the whole registry unreadable.

## Scope boundary

This phase ports storage, not service/controller behavior. Python remains the
production business-logic owner until the later service cutover. GO05 may use
registry-independent system primitives; GO09 wires the migrated services to
this registry.
