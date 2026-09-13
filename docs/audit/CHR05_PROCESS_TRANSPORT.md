# CHR05 — Process, signals & RootService transport

CHR05 closes the process-lifecycle and privileged-transport portion of the 2026-09-12 master audit. Its executable owner set is **18 canonical findings / 35 source manifestations**:

- `D05`, `D06`, `D31`
- `U081`–`U092`
- `U223`, `U226`, `U227`

The accounting remains part of `docs/audit/roadmap-coverage.json` and is enforced by `repoctl`.

## Go process boundary

`internal/system.Runner` now has one explicit output policy (`capture`, `inherit`, `discard`). Legacy `NoCapture` maps to discard in both foreground and background execution instead of inheriting output only in the background case.

Captured output is bounded in memory by `MaxCaptureBytes`; it no longer writes an unlimited temporary spool and then truncates it afterward. The bounded writer preserves useful head/tail evidence and sets `RunResult.Truncated`. Captured stdout/stderr are materialized once rather than reread from temporary files.

Attached execution treats timeout/cancellation as authoritative failure states even when a child traps `SIGTERM` and exits zero. Process identities are created in dedicated process groups; termination signals the whole group, waits for the group to disappear, then escalates the group to `SIGKILL`. This prevents a leader exiting early from making surviving descendants look terminated.

Service `ExecStop` has a finite timeout. Transfer import/export now use `TransferControl`: progress callbacks and cancellation are checked between phases and inside checksum/copy/archive extraction work, while spawned tar/zstd/openssl processes inherit cancellation through the shared runner.

## Android RootService ownership and Binder boundary

`RootServiceClient` is process/application-owned. `MainViewModel` no longer unbinds it when an Activity/ViewModel is cleared, so foreground operation work cannot lose its shared privileged connection because the UI was recreated.

The client no longer serializes all calls behind a global Binder-call mutex. Binding itself remains serialized, but independent healthy calls may proceed concurrently. A coroutine timeout no longer blindly tears down a process-wide connection, because synchronous Binder work may still be completing server-side.

Requests crossing Binder are capped at 256 KiB. RootService uses a bounded `ThreadPoolExecutor` (maximum four workers and a bounded queue) instead of `newCachedThreadPool`.

Operation streams duplicate and immediately relinquish the incoming Binder descriptor, own the duplicate in the worker, and close the stream deterministically. Client cancellation closes its read side so a blocked stream read has an EOF/cancellation boundary. Native stream exit code, timeout, truncation, and stderr are converted into a `bridge_process_failed` event instead of being discarded.

## Descriptor transfers

Large descriptor transfers no longer keep one synchronous Binder call blocked for the duration of the file copy.

`transferFromDescriptor` / `transferToDescriptor` now admit a request, duplicate/own the descriptor, persist a request journal, enqueue bounded worker work, and return. The AIDL surface exposes `transferState(requestId)` and `cancelTransfer(requestId)`; the client polls durable state to terminal completion. A lost Binder response is therefore reconciled by request ID and is never automatically replayed.

Transfer journals persist running/progress/terminal state under the hardened RootService transfer directory. Cancellation closes the worker-owned descriptor and flips an atomic cancellation flag. A stale `running`/`cancelling` record discovered after service restart becomes `interrupted` rather than remaining an immortal success-unknown request.

Import staging enforces a 16 GiB ceiling plus a free-space reserve, uses partial-file + fsync + rename publication, and periodically persists byte progress. Export copies have the same maximum size. The client uses an idle-progress watchdog rather than the old fixed total transfer timeout, so a large transfer can continue as long as it is making progress.

The privileged transfer root and request-journal directory are canonical, non-symlink, root-owned, and forced to mode `0700`; state files are mode `0600`. Protocol-shaped descriptor requests validate protocol version, request ID, expected operation, and exact allowed payload keys before any bytes move.

Managed-artifact convergence/TTL/reconciliation remains owned by CHR10; CHR05 deliberately limits itself to the safe transport/staging boundary.

## Bridge process and protocol evidence

Android native bridge invocations clear the environment and retain the curated CHR04 root PATH. Timeout/interruption now terminates the native process **and descendants** by walking `/proc/<pid>/task/<pid>/children`, signaling deepest children first, then escalating to `SIGKILL` when required.

Bounded bridge output is fail-closed: a truncated response is `BRIDGE_RESPONSE_TRUNCATED`, not a JSON parse accident. Request-bearing bridge responses must return the expected `requestId`; mismatches are `BRIDGE_REQUEST_ID_MISMATCH`.

## Runtime authentication

Runtime caching now stores an authenticated generation identity. Active-module generation includes canonical/stat identities for module compatibility files and every native runtime file; external runtimes include their root-managed executable identity. If those identities change, the cached runtime is discarded and full compatibility/seal validation runs again.

Native runtime validation now verifies ELF64, little-endian, `EM_AARCH64`, and a Bionic-compatible `PT_INTERP` when one exists. Compatibility fields named `minimumSupported*` are treated as minimum/range constraints instead of exact version equality. Capability probing is bounded to 10 seconds and successful authenticated runtimes reuse the generation cache rather than rehashing their entire sealed inventory for every bridge request.

## Foreground cancellation continuity

A cancellation-only foreground-service restart no longer fires one cancel RPC and then leaves the service without reconciliation work. If an operation ID is not yet known, persisted work is resumed/discovered; once known, cancellation is followed through reconciliation until a durable terminal state before foreground teardown.

## Executable gates

CHR05 adds `repoctl.ValidateProcessTransportBoundary`, wired into `repoctl validate` and the final seal. The gate asserts the process-group, bounded-capture, transfer-control, Binder ownership, bounded-worker, descriptor ownership, request-correlation, runtime-generation and cancellation-continuity invariants above.

Regression coverage includes:

- attached timeout despite a child trapping TERM and exiting zero;
- cancellation despite `AllowFailure`;
- foreground/background `NoCapture` parity;
- bounded capture behavior;
- full process-group termination;
- transfer-copy cancellation before mutation;
- transfer progress failing closed after cancellation;
- bridge truncation and request-ID mismatch;
- ARM64 ELF-header acceptance and wrong-architecture rejection.

## Validation in the artifact build environment

Passed:

- `go test ./internal/system -count=1`
- focused CHR05 transfer-control tests
- `go test ./internal/repoctl -count=1`
- compile of every Go package using the offline sqlite3 compile shim
- `go vet ./...` using that shim
- standalone Kotlin compilation of the complete modified RootService package against Android/Binder/JSON stubs and the real coroutine library
- standalone Kotlin compilation of the CHR05 root-package test sources in the same module
- `git diff --check`

The real Android Gradle gate could not run in the artifact sandbox because Gradle 9.7.1 is not cached and outbound network access is unavailable; even `./gradlew --offline` attempts to retrieve that distribution. The production Gradle/JVM tests remain in the overlay for the Termux validation environment.

The complete SQLite-backed Go service suite is likewise not executable here because the sandbox lacks the real `github.com/mattn/go-sqlite3` module; focused process/repoctl/transfer-control tests are executable, and every package is compile/vet checked with the compile-only stub.

## Next boundary

CHR06 owns the universal mutation engine and **Gate A**. CHR05 does not mark `D02`, `D03`, or `D04` closed merely because process cancellation and descriptor transfer state are now recoverable; those global mutation/locking/recovery guarantees remain explicit CHR06 work.
