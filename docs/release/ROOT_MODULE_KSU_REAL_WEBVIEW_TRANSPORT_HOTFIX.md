# KernelSU real WebViewInterface transport hotfix

Grounded against KernelSU Manager's current `WebViewInterface.kt`.

* Bounded query/preview RPC uses native `ksu.exec`, which accepts one root-shell command and returns errno/stdout/stderr through a callback.
* Streaming NDJSON operations use `ksu.spawn`.
* For `spawn`, the executable remains raw while each argv item is POSIX-shell quoted because KernelSU concatenates command and argv strings before submitting them to its root shell.
* Spawn callback objects remain global until completion.
* Regression tests include apostrophes, dollar expansion, backticks, quotes and newlines.

## Promise-audit v4
The v3 audit found two missing promises: no pre-RPC bridge self-test and no bounded failure if KernelSU never invokes an exec callback. v4 adds a cached readiness probe (`id` + `chrootctl version`) before capabilities/application RPC and bounded exec callback timeout, with regression coverage.

## Complete promise seal v5

v5 closes the remaining end-to-end UI promise. Startup now explicitly enters
`Checking backend…`, awaits the KernelSU/root/backend readiness probe, and
renders a persistent backend failure card instead of leaving a generic
connecting state. The card distinguishes unavailable bridge, callback timeout,
root-shell probe failure, and backend/version probe failure and provides a
Retry connection action. A UI wiring regression test prevents restoration of
the old fire-and-forget bootstrap.
