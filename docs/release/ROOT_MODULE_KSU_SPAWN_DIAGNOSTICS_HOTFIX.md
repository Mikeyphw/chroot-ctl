# Root module KernelSU spawn/diagnostics hotfix — 1.3.6 / 21

This hotfix closes the KernelSU WebUI failure that presented as `exit status -1` with no stdout/stderr and no new backend log entry.

- Native KernelSU `spawn` is treated as a root-shell transport. chrootctl now sends one fully shell-quoted command string and an empty native argv array, preventing JSON, passwords, paths, spaces, `$`, backticks, quotes, and newlines from being re-tokenized by the host bridge.
- Non-zero KernelSU results are normalized around the host event order: the manager emits `exit` first and a separate `error` event afterward. The callback remains alive briefly so the libsu error is retained before the public child exit is finalized.
- Synthetic negative exit statuses are surfaced as KernelSU bridge failures with sanitized native bridge provenance instead of generic `INSTALL_BACKEND_EXIT` errors.
- Before any mutating streamed operation, a harmless streaming preflight validates root-shell spawning, argument preservation, stdout delivery, and exit delivery. The successful probe is cached only for the selected backend executable, so changing fallback authority forces a fresh probe. A broken streaming bridge blocks the mutation before it starts.
- Technical failure cards now include bridge provenance in addition to backend, exit status, operation ID, backend log path, stdout/stderr, and structured envelopes. Native bridge messages are redacted before exposure, and the UI applies a second redaction pass for password/token/credential fields, bearer credentials, and secret-bearing URL query parameters.
- The authoritative module runtime remains `/data/adb/modules/chrootctl/runtime/arm64-v8a/chrootctl`; the legacy `chrootctl-magisk` ID remains migration-only.

The module payload is bumped to 1.3.6 / versionCode 21 so installed WebUI/runtime artifacts can be distinguished from 1.3.5 / 20.
