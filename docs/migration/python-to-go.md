# Python → Go migration ledger

This document tracks the staged replacement of the Python chrootctl backend with
a native Go backend. The Android application remains Kotlin. Catalog YAML and
shell installer resources remain data/scripts unless a later phase has a
specific reason to replace them.

## Non-negotiable cutover rules

1. Production behavior stays on Python until the corresponding Go slice passes
   differential/golden parity tests.
2. Existing `chroots.sqlite3` databases and operation journals are migrated in
   place. No parallel Go-only persistence format is allowed.
3. Bridge protocol version 1 stays stable during the backend rewrite.
4. The Android app must not need feature-level changes merely because the
   backend language changes.
5. The final production/module/build/test path must not require Python, pip,
   venv, Pydantic, Rich, PyYAML, or Nuitka.
6. A phase is complete only when its old Python tests are represented by Go,
   Kotlin, or explicitly-retired contract tests.

## Frozen GO00 baseline

The committed fixtures under `migration/contracts/v1/` currently define:

| Surface | Baseline |
| --- | ---: |
| Human CLI command nodes | 66 |
| `app` bridge CLI subcommands | 8 |
| Android bridge operations | 86 |
| Bridge protocol | 1 |
| Operation journal schema | 2 |
| Compatibility manifest schema | 2 |
| Native runtime manifest schema | 1 |
| Current native runtime kind | `nuitka-onefile` |
| Current production backend | Python 0.11.0 |

The bridge operation distribution is 36 query, 16 preview, and 34 operation
handlers. Arbitrary shell execution is not part of the bridge contract.

## Phase ledger

### GO00 — Freeze compatibility contracts — COMPLETE

Delivered:

- deterministic Python contract exporter;
- committed CLI, bridge, persistence, and release fixtures;
- drift check mode suitable for tests/CI;
- Go-side decoder and invariant validation;
- critical-operation presence checks.

Exit criterion: contract fixtures can be regenerated deterministically and both
Python and Go checks reject drift.

### GO01 — Go skeleton + Android ARM64 build spike — COMPLETE

Delivered:

- `go.mod` and initial `cmd/chrootctl` entrypoint;
- internal version and contract packages;
- Go unit tests;
- Linux native build proof;
- `GOOS=android GOARCH=arm64 CGO_ENABLED=0` build proof;
- scaffold refuses production commands until parity is implemented.

Observed GO01 artifact characteristics in the development environment:

- Android target: ELF 64-bit ARM aarch64 PIE;
- Android interpreter: `/system/bin/linker64`;
- no cgo required by the current scaffold.

This proves the executable delivery path only. It does **not** prove SQLite,
root, chroot, mount, signal, Unix socket, or `/proc` behavior; those remain
later real-device gates.

### GO02 — SQLite compatibility spike — IMPLEMENTED; DEVICE ACCEPTANCE PENDING

Delivered:

- native SQLite compatibility layer using `github.com/mattn/go-sqlite3`;
- Python-created registry fixture opened and mutated by Go, then reopened by
  Python;
- schema object, foreign-key cascade, WAL, busy-timeout, `foreign_keys=ON`,
  `synchronous=FULL`, integrity, and foreign-key checks;
- Android ARM64 cgo compilation gate plus the existing cgo-free scaffold gate.

The SQLite driver is not considered release-accepted until the compatibility
probe is executed on a real Android ARM64 device. GO03 is independent of that
device gate. GO04 must not become production-authoritative until the device gate
has passed.

### GO03 — Models, validation, config — COMPLETE

Delivered:

- all 40 `src/chrootctl/models.py` dataclass shapes mirrored as Go structs with
  frozen snake_case JSON field names;
- model helper behavior for operation counters, session success, log snapshots,
  installer defaults, and app-build next steps;
- Python-compatible validation for safe names, usernames, booleans, bounded
  integers, string lists, catalog uniqueness, relative chroot paths, and archive
  names with golden success/error cases;
- environment-aware config defaults, JSON loading, mount/path normalization,
  repository aliases, per-chroot overrides, shell resolution, and Android state
  path migration;
- Android legacy database migration semantics expressed through an injected
  chroot-row counter so GO03 remains independent of a concrete SQLite driver;
  GO04 wires that counter to the accepted registry implementation;
- structured application/HTTP error payloads and Python-compatible default
  titles/messages;
- dual console/file logging with Python-equivalent logger name, format, levels,
  verbose behavior, and file-failure fallback;
- `foundations.json` Python oracle fixture consumed directly by Go tests.

### GO04 — Registry and transactional persistence — COMPLETE

Delivered:

- production Go registry package owning the GO02 SQLite compatibility handle;
- canonical Python schema creation and legacy snapshot foreign-key repair with
  identical orphan-row refusal behavior;
- chroot CRUD, rename/delete cascades, and atomic preflighted mutation batches;
- snapshot CRUD, filesystem mutation journal, artifact TTL/pruning, and audit
  event persistence with Python-compatible ordering/defaults;
- defensive corrupt-JSON read markers so one damaged metadata row does not
  break registry reads;
- `CountChroots` adapter for GO03 Android state-layout migration without making
  config depend directly on SQL internals.

The Go registry does not replace the production Python service layer yet; GO09
performs that service cutover after controller/operation parity.

### GO05 — System runner and low-level host primitives — COMPLETE

Delivered:

- Go subprocess runner with dry-run, clean/chroot environments, stdin, bounded
  capture, background execution, timeout and cancellation behavior;
- independent process groups for managed commands plus PID/PGID/start-time/boot
  identity capture and fail-closed signalling to prevent reused-PID kills;
- root detection/requirement, sudo re-exec, Go self re-exec arguments, uid/gid
  discovery, host architecture and current-user helpers;
- `/proc/mounts` parsing, QEMU-user discovery and binfmt_misc capability checks;
- secure detached-output creation with no-follow semantics;
- CGO-free Android/ARM64 compile proof for the low-level system package.

Controller/install behavior remains out of scope until GO06.

### GO06 — Controller and distro installers — COMPLETE

Implemented in `internal/controller`, `internal/install`, and
`internal/integrity`: mount/session orchestration, Ubuntu/Arch extraction and
bootstrap paths, pinned signature/checksum verification, phase/resume tracking,
filesystem promotion journaling/rollback, snapshots, and foreign-architecture
QEMU/binfmt guards.

### GO07 — Users, catalog, clipboard, completion — COMPLETE

Implemented in `internal/users`, `internal/catalog`, `internal/clipboard`,
`internal/completion`, and `internal/output`. Built-in manifests/scripts and the
exact frozen zsh completion program are Go-embedded from top-level `resources/`.
The clipboard daemon preserves token + SO_PEERCRED authentication and verified
PID/PGID/start-time/boot-id lifecycle controls.

### GO08 — Persistent operations, locking, cancellation, recovery

Port operation records/events, global/target locks, cancellation markers,
process tracking, stale-operation reconciliation, compaction, and recovery.

### GO09 — Service layer

Port all backend services so CLI and Android bridge share one Go business-logic
layer.

### GO10 — Android bridge protocol-v1 parity

Port `capabilities`, `state`, `query`, `preview`, `run`, `operation`, `cancel`,
and `reconcile`, including NDJSON streaming and all frozen error/redaction rules.
All 86 operations must pass parity gates.

### GO11 — Human CLI parity

Recreate the frozen CLI without redesigning it. New UX work waits until the
migration is complete.

### GO12 — Go-native module/runtime packaging

Replace Nuitka and the bundled Python userspace with the Go executable and a
new runtime manifest. Keep old schema support only as a transition mechanism.

### GO13 — Release identity schema transition

Introduce generic backend/runtime identity fields and update compatibility
manifest/runtime resolver with explicit backward compatibility.

### GO14 — Remove Android Python fallback

After Go module parity, remove Python candidate resolution and Python-version
checks from the Android runtime resolver.

### GO15 — Build/release tooling conversion

Replace Python repository/release/native-runtime tooling with Go commands and
thin shell wrappers where appropriate.

### GO16 — Test-suite conversion

Map every meaningful Python test to Go/Kotlin or an explicitly retired contract.
Keep differential tests while both implementations exist.

### GO17 — Python purge + final release seal

Delete Python product code, Python scripts/tests, Python packaging/dependencies,
Nuitka logic, and compatibility fallbacks. Add a repository guard preventing
runtime/build/validation Python from returning.
