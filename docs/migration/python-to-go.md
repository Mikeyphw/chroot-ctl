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
| Compatibility manifest schema | 3 |
| Native runtime manifest schema | 2 |
| Current native runtime kind | `go-native` |
| Current production backend | Go 0.11.0 |

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

### GO08 — Persistent operations, locking, cancellation, recovery — COMPLETE

Implemented in `internal/operations` with shared `internal/redaction`: schema-v2
records with legacy alias decoding, atomic JSON/JSONL persistence, bounded event
compaction, global/target `flock` locks, cancellation markers, verified process
identity signalling, explicit stale-operation reconciliation/recovery, redacted
requests/results/progress, retry metadata, and fail-closed corrupt-record placeholders.

### GO09 — Service layer — COMPLETE

Implemented in `internal/services`: one transport-neutral container composes
registry, controller, operations, users, catalog, install, snapshots, transfer,
preview/repair, support, lifecycle/module readiness, release evidence and service
unit control. GO10 and GO11 consume this layer instead of duplicating backend
business logic in the bridge or CLI.

### GO10 — Android bridge protocol-v1 parity — COMPLETE

Implemented in `internal/bridge`: strict protocol-v1 request parsing and limits,
generated metadata for all 86 frozen operations, query/preview/run dispatch over
the Go service layer, one-shot preview approvals, operation lifecycle/retry,
cancel/reconcile, NDJSON streaming, redaction, and malformed-request validation
before service/config construction. The Android build gate compiles the complete
SQLite-backed bridge as a CGO Android/arm64 executable.

### GO11 — Human CLI parity — COMPLETE

Implemented in `internal/cli` from the frozen 66-node CLI contract. The native
parser preserves the existing command/argument surface, static and dynamic
completion paths, root escalation policy, target/user resolution, interactive
session I/O, and service-layer dispatch. `app` delegates to the GO10 bridge.
The legacy `magisk render` implementation remains a deliberate transitional
delegation until GO12 replaces module/runtime packaging; no runtime schema is
changed in GO11.

### GO12 — Go-native module/runtime packaging — COMPLETE

The module runtime now builds `cmd/chrootctl` as an Android/arm64 CGO Go ELF.
New artifacts use native-runtime schema 2 with `runtimeKind=go-native`; runtime
validators and the Android resolver retain explicit schema-1 `nuitka-onefile`
read compatibility for already-installed modules during the transition. The
module launcher no longer creates a Nuitka onefile extraction directory or
sets Python/loader environment state.

### GO13 — Release identity schema transition — COMPLETE

Compatibility manifest schema 3 replaces `pythonPackage` with generic `backend`
and `nativeRuntime` identities. New module/runtime identity is Go-native while the
Android/Python/Go diagnostic readers explicitly retain schema-2 compatibility
for already-installed modules. Bridge protocol remains version 1.

### GO14 — Remove Android Python fallback ✅

Android runtime resolution is Go-only. Python executable/module candidates, Python-version
compatibility checks, legacy Nuitka runtime acceptance, and Python-only process environment
variables have been removed. An enabled module remains authoritative and fails closed; when no
module is active, explicit/system/Termux **Go chrootctl executables** remain valid development
candidates after the normal protocol-v1 capabilities probe.

### GO15 — Build/release tooling conversion ✅

`cmd/repoctl` now owns Android runtime sealing, Magisk/KernelSU module packaging/install, source
archives, validation, cross-architecture diagnostics, and release artifacts. `build.sh` and
`scripts/repoctl` are thin Go wrappers. Devtool packaging and the Go-native CI job no longer use
Python/Nuitka. Legacy Python test/development commands remain only for GO16 differential coverage
and GO17 removal.

### GO16 — Test-suite conversion ✅

The 82-file legacy Python test inventory is frozen in `migration/go16-test-map.json`. Every
file maps to surviving Go/Kotlin tests or an explicitly retired frozen contract, and
`internal/testseal` makes unmapped coverage a validation failure. `repoctl differential`
is the final transition-only Python/Go oracle: it verifies byte-identical zsh completion
and deterministic frozen-contract parity while both implementations still exist.

### GO17 — Python purge + final release seal ✅

The legacy Python package, tests, validators, packaging metadata, compatibility shims, and
Nuitka-era execution fallbacks are removed. Devtool and CI are Go/Kotlin-only.
`repoctl validate` enforces repository purity and the retained GO16 migration-test map;
`repoctl final-seal` additionally proves the 66-node CLI / 86-operation bridge contracts,
builds a real Android/ARM64 CGO runtime, and requires byte-for-byte deterministic source
and module archives before reporting a final seal.
