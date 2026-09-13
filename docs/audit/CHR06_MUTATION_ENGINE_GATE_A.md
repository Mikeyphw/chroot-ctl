# CHR06 — Universal mutation engine + Gate A

Baseline: CHR05 `Process, signals & RootService transport`.

## Closure scope

CHR06 closes exactly seven canonical findings / nineteen source manifestations:

- `D02` — global dry-run is not enforced at the mutation boundary (10 source manifestations)
- `D03` — normal CLI mutations bypass shared target/global locking (4)
- `U217` — operation recovery only scans newest 1000 records (1)
- `U218` — chroot remove marks mutation completed before registry deletion (1)
- `U219` — transfer import does not persist backup path before the critical rename window (1)
- `U220` — install promotion leaves committed cleanup debt without a recovery consumer (1)
- `U221` — mutation journal update errors are routinely discarded (1)

`D04` remains CHR07-owned and planned. CHR06 supplies its shared locking, typed journal, recovery and durability foundation without prematurely claiming the final CRUD/destructive-atomicity closure.

## Universal mutation boundary

`internal/mutation` is the common mutation safety layer used by normal CLI and Android/bridge operation execution. It provides:

- hierarchical process-shared `flock` locking;
- a global exclusive mutation gate;
- target locks that hold the global gate shared, allowing independent targets to proceed concurrently while excluding global mutations;
- explicit lock-mode tracking so a target-scoped shared global gate cannot be silently upgraded to a global exclusive lock;
- re-entrant same-context lock reuse without self-deadlock;
- typed filesystem mutation state transitions;
- durable recovery of incomplete filesystem mutations;
- deterministic `repair_required` and `cleanup_debt` states when automatic convergence is unsafe or incomplete.

Normal CLI mutation admission derives from generated CLI mutability metadata and acquires this same lock layer before dispatch. Android/bridge `operations.Manager` also uses `mutation.AcquireScope`, eliminating the old CLI-vs-bridge lock split.

## Zero-write dry-run boundary

Dry-run now exists below command-specific behavior rather than depending on every caller remembering to suppress individual writes.

`services.New(..., dryRun=true, ...)`:

- uses `config.LoadReadOnly`, so Android/config layout migration is not run;
- opens an existing registry read-only/query-only;
- uses a schema-complete in-memory query-only registry when no registry exists yet;
- does not create the operation journal or preview store;
- uses console-only/read-only logging and never creates the configured logfile;
- constructs a dry-run mutation engine that performs neither persistent locking nor mutation-journal writes.

Root-required execution paths now use `Runner.RequireRoot()`: dry-run planning reaches validation/dispatch without privilege escalation, while real execution still requires root.

The known D02 command families are sealed individually as well:

- chroot rename/remove perform zero persistent mutations in dry-run;
- transfer export/import perform no archive, staging, registry or artifact writes;
- catalog apply validates but does not persist running/completed catalog state;
- support export does not create/truncate a bundle;
- clipboard start/stop/run/set are planning-only;
- Magisk render does not publish output;
- wrapper installation retains the CHR04 zero-write implementation;
- production Ubuntu/Arch installer factories now wire their real fetch/download callbacks instead of reaching the downloader-not-configured failure.

## Typed mutation journal and recovery

Filesystem mutation state vocabulary is centralized in `internal/registry`:

- `pending`
- `staged`
- `promoting`
- `committed`
- `cleanup_debt`
- `complete`
- `rolled_back`
- `failed`
- `repair_required`

Legacy `completed` transitions normalize to `complete`. Mutation state updates validate their state and require exactly one affected journal row.

The production recovery consumer handles the CHR06 mutation families:

- `chroot-remove`
- `chroot-rename`
- `snapshot.create`
- `snapshot.restore`
- `chroot.import`
- `install.extract`
- `catalog.apply`

Recovery is idempotent where evidence is authoritative. Ambiguous evidence is never guessed: the row becomes `repair_required` and mutating admission fails closed until the condition is reviewed.

## Destructive workflow ordering fixed by CHR06

### Chroot remove

Removal no longer recursively deletes the live rootfs and marks the journal complete before deleting the registry row. It now:

1. records the exact tombstone path;
2. renames the rootfs to the tombstone;
3. durably records the promoted filesystem state;
4. deletes the registry row;
5. marks the transaction committed;
6. removes the tombstone;
7. marks complete, or records `cleanup_debt` when final cleanup cannot finish.

Registry failure restores the tombstone to the original path. Rollback failure is persisted as `repair_required`.

### Chroot rename

Rename remains nonterminal until the filesystem path and registry identity agree. Registry failure rolls the filesystem back; an unsuccessful rollback becomes durable `repair_required` evidence rather than a false terminal mutation.

### Snapshot create / restore

Exact stage and backup paths are persisted before rename windows. Every irreversible boundary has a checked journal transition. Snapshot create registry failure records a completed rollback only after target cleanup succeeds. Snapshot restore uses `committed` and `cleanup_debt` to distinguish a valid restored rootfs from leftover backup cleanup work.

### Transfer import

The generated overwrite backup path is persisted before the old target is displaced. The committed registry record carries `_chrootctl_mutation_id`, allowing recovery to distinguish an authoritative committed import from an interrupted pre-commit promotion. Missing required backup evidence fails closed.

### Install promotion

Install promotion uses durable `staged -> promoting -> committed -> complete` transitions. Cleanup failure records `cleanup_debt`; the production recovery consumer removes that debt during later mutating preflight. Rollback and rollback-fsync errors can no longer be silently discarded.

### Catalog apply

Catalog dry-run is write-free. Real catalog script execution is journaled; a crash with ambiguous arbitrary-script outcome becomes `repair_required` rather than being guessed safe to replay.

## Operation-journal durability

Bridge operation recovery now enumerates all active records instead of only the newest 1,000 history entries.

Operation state/event persistence is part of the operation result contract:

- queued/start/cancelling states must persist;
- successful/failed/blocked/cancelled terminal state must persist;
- terminal event persistence failure is returned as an execution error;
- cancellation-marker cleanup failure is returned instead of ignored;
- record publication uses temp-file fsync, atomic rename and parent-directory fsync.

An operation therefore cannot truthfully report success while its durable terminal record was lost.

## Gate A executable seal

`ValidateMutationEngineGateA` is wired into repoctl validation/final-seal paths. Gate A checks include:

- generated CLI mutation classification;
- universal lock-source invariants;
- shared CLI/bridge lock usage;
- zero-write dry-run construction;
- read-only/ephemeral SQLite policy;
- typed mutation vocabulary and strict mutation-row updates;
- production filesystem recovery coverage;
- no reintroduction of discarded mutation-journal transition errors;
- process-tree/signal regressions retained from CHR05;
- cross-process global/target lock behavior;
- operation recovery beyond 1,000 history rows;
- terminal journal durability failure injection;
- crash-state recovery fixtures for remove, rename, install/import promotion and snapshot creation;
- dry-run controller filesystem behavior.

## Validation performed while constructing the overlay

The sandbox has no cached real `github.com/mattn/go-sqlite3` source and cannot download modules, so a compile-only sqlite3 stub was used only for compilation/vet of SQLite-dependent packages. That stub is not part of the overlay.

Passed in the construction environment:

- `go run ./cmd/cli-contract-gen --check`
- full compile of every Go package (`go test ./... -run '^$'`) using the compile-only sqlite stub
- `go vet ./...` using the same compile-only stub
- full non-SQLite suites for operations, system, catalog, CLI, repoctl and controller
- process-shared mutation lock regression suite, including shared-to-exclusive upgrade refusal
- CHR06/Gate A source seal

The SQLite-backed zero-write and crash-recovery behavior tests remain real production tests and are intentionally not weakened to accommodate the construction sandbox. The artifact validation gate runs them on the real repository environment where the sqlite3 dependency is available.

## Deliberate boundary after Gate A

CHR07 remains responsible for the final `D04` closure and the complete destructive CRUD safety seal: mounted/live-service checks, namespace migration for per-chroot overrides/snapshots/service state, and the final failure-injection matrix for rename/remove. CHR06 makes those operations use one lock/journal/recovery authority first.

## Gate A v2 regression-fixture correction

The first real Termux Gate A run of the v1 overlay built successfully and reached the complete Go test suite, where five legacy tests exposed assumptions invalidated by the stricter CHR06/CHR04 boundaries. Devtool rolled the overlay back atomically, so no partial CHR06 state remained in the repository.

The v2 artifact keeps every production invariant and corrects those test fixtures:

- installer factory construction tests now provide the required dry-run runner instead of constructing an impossible runner-less production installer;
- ordinary shared-service wiring/repair tests construct a writable container (`dryRun=false`), while the dedicated dry-run boundary test remains query-only/zero-write;
- the CHR03 canonical identity test expects the stronger basename/identity rejection that now fires before a duplicate-owner error;
- the CHR04 re-exec argv regression uses an unexported test seam for the trusted executable resolver, so an Android/Termux test host does not need a real active module under `/data/adb` merely to test argv preservation.

The trusted executable seam is process-local Go state only. Production resolution still accepts only the same active/root-managed paths and does not honor an environment override.
