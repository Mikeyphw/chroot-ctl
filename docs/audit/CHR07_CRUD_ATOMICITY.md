# CHR07 — CRUD atomicity & destructive safety

Baseline: CHR06 `Universal mutation engine + Gate A`.

## Closure scope

CHR07 closes exactly nine canonical findings / twenty-one source manifestations:

- `D04` — filesystem/registry mutations were not crash-atomic and recovery journaling was incomplete (13 source manifestations)
- `U149` — destructive rename/remove could accept the configured chroot management root (1)
- `U150` — rename did not require the target to be fully unmounted (1)
- `U151` — per-chroot configuration overrides were not migrated on rename (1)
- `U152` — snapshot registry identity cascaded while physical snapshot namespaces did not (1)
- `U153` — rename discarded configuration errors (1)
- `U154` — the chroot list was labeled `Installed Chroots` while including every registered row (1)
- `U155` — import overwrite did not durably identify its backup before target displacement (1)
- `U156` — old import-backup cleanup failures were ignored (1)

`D41` remains CHR10-owned and planned. CHR07 contributes strict path containment and durable rename/removal primitives, but it does not claim the later general privileged-output publication/artifact-plane closure.

## Destructive identity preflight

Rename and remove now resolve one registry-authoritative `ResolvedTarget` and fail closed before crossing a mutation boundary when identity evidence is unsafe.

The target must:

- resolve through the canonical registry row;
- be a real directory rather than a symlink or special file;
- satisfy the CHR03 name/path identity invariant;
- not equal the configured chroot management root;
- not resolve into reserved management storage;
- remain uniquely owned by the selected registry identity.

Rename additionally requires the complete target mount set to be unmounted. Both rename and remove reject active managed services and fail closed on stale/unverifiable PID state instead of guessing that a service is stopped.

## One namespace transaction

A chroot identity is no longer just the rootfs directory plus one SQLite key. CHR07 treats these pieces as one destructive namespace:

- rootfs directory;
- registry identity/path;
- registered snapshot paths;
- physical snapshot namespace;
- persisted and in-memory `chroot_overrides` identity;
- service process identity/PID state;
- service logs;
- target `.enabled` markers.

### Rename

Rename performs the following recoverable transaction:

1. validate old/new identity, configuration, mount state, service activity, snapshot namespace, and destination collisions;
2. durably journal exact rootfs and dependent namespace moves;
3. rename the rootfs and fsync its parent;
4. move snapshot/service/log/enabled namespace entries and fsync their parents;
5. migrate the persisted per-chroot override while the old registry row is still authoritative;
6. atomically rename the registry row and every registered snapshot path in one SQLite transaction;
7. persist the committed mutation state;
8. persist terminal completion.

If configuration or registry publication fails before registry commit, configuration, dependent namespace and rootfs are reversed. If rollback itself encounters conflicting evidence, the mutation becomes `repair_required` rather than being falsely marked rolled back.

A crash after the configuration identity moves but before registry commit is also deterministic: recovery sees the old registry owner as authoritative and reverses the override plus filesystem namespace. Once the new registry row is authoritative, recovery completes any remaining namespace/override publication. Rename recovery can be discovered using either the old target name or the new identity, avoiding stranded cleanup debt after the primary-key change.

### Remove

Remove checks the exact registry-authoritative target, verifies no managed service is live, unmounts that exact runtime, then verifies it is fully unmounted. It does not recursively erase the authoritative tree before registry convergence.

Instead it:

1. records an exact rootfs tombstone and all dependent staging paths;
2. renames the rootfs to the tombstone and fsyncs the parent;
3. stages the snapshot/service/log/enabled namespace;
4. deletes the registry identity;
5. records the committed state;
6. removes the rootfs tombstone and staged dependent state;
7. removes the persisted per-chroot override;
8. fsyncs cleanup parent directories;
9. records `complete`, or `cleanup_debt` when committed cleanup is incomplete.

A registry failure restores the staged rootfs and dependent namespace. Conflicting rollback evidence becomes `repair_required`.

## Snapshot namespace integrity

Rename validates every registered snapshot path against the old managed snapshot root before moving anything. `Registry.RenameIdentity` then updates the chroot identity and all snapshot paths in one SQLite transaction with strict `RowsAffected` checks.

Remove performs the same containment/existence validation before allowing SQLite cascade deletion. The complete managed snapshot tree is staged and deleted only after registry commit. A corrupted registry row pointing outside the managed snapshot namespace therefore blocks removal rather than losing the DB handle to an orphaned physical snapshot.

CHR09 still owns full snapshot metadata fidelity and the broader snapshot authority/recovery model; CHR07 closes only the destructive CRUD namespace split represented by U152.

## Persisted configuration overrides

`config.RewriteChrootOverride` provides an atomic same-directory config rewrite:

- validates old/new chroot names and config shape;
- refuses a destination override collision;
- stages a temporary file in the destination directory;
- preserves the existing file mode;
- fsyncs content;
- atomically renames the replacement;
- fsyncs the parent directory.

Rename propagates `ConfigFor` validation errors rather than discarding them, and it never uses an unrelated destination-name override to choose the new rootfs path. The destination root is derived only from the authoritative old rootfs parent plus the validated new identity.

## Transfer overwrite seal

CHR06 introduced the corrected import transaction; CHR07 is the owning closure for U155/U156 and now seals its ordering explicitly:

- the generated overwrite backup path is part of durable mutation detail before the first `target -> backup` rename;
- old-backup deletion failure transitions to `cleanup_debt` rather than being ignored or converting an already-committed import into an ordinary pre-commit failure.

## Failure-injection matrix

CHR07 adds direct regressions for:

- mounted-target rename refusal;
- active managed service refusal;
- configured management-root destructive-target rejection;
- malformed source override propagation;
- destination override collision refusal;
- rootfs parent-fsync failure after rename with rollback;
- dependent namespace move failure with rootfs rollback;
- configuration publication failure before registry commit;
- registry rename failure with rootfs/namespace/config rollback;
- registry delete failure with rootfs/snapshot/service namespace restoration;
- split/out-of-namespace snapshot removal refusal;
- committed remove cleanup failure becoming recoverable `cleanup_debt`;
- rollback conflict becoming `repair_required`;
- crash recovery completing committed rename namespace/config using the new target identity;
- crash recovery reversing namespace/config when the old registry owner remains authoritative;
- committed remove recovery finishing tombstone/state/config cleanup;
- atomic snapshot-path update inside `Registry.RenameIdentity`;
- destination collision/failure preservation in persisted override migration.

These sit on top of Gate A's cross-process lock, signal, zero-write dry-run, operation-journal and mutation-journal failure-injection suites.

## Executable release seal

`ValidateCRUDAtomicity` is wired into normal `repoctl validate` and final-seal internal validation. It verifies that the destructive preflight, namespace transaction, config publication, registry/snapshot transaction, recovery targeting, transfer-backup ordering and `Known Chroots` output contract remain present.

The audit coverage validator requires the exact CHR07 canonical set and exactly 21 source manifestations. It also verifies that D41 remains planned under CHR10.

## Validation constraints in the construction sandbox

The construction sandbox still lacks a runnable cached `github.com/mattn/go-sqlite3` implementation and outbound module access. SQLite-dependent CHR07 tests are therefore compile/vet checked here and remain real executable tests for the user's Termux environment; they are not replaced with mocks or disabled.

Pure config tests and source-level repoctl seals run directly in the construction environment. Every Go package is compiled and vetted using the same external compile-only sqlite shim used by the prior overlays; the shim is not included in the artifact.

## Deliberate boundary

CHR08 owns service lifecycle/journal and mount/session correctness beyond the destructive guard needed here. CHR09 owns metadata-faithful snapshot semantics. CHR10 owns the general transfer/archive/artifact publication plane and D41. CHR07's job is narrower: make destructive chroot identity changes fail closed, reversible before commit, and recoverable after crashes without splitting the identity across rootfs, SQLite, configuration, snapshots and external control state.
