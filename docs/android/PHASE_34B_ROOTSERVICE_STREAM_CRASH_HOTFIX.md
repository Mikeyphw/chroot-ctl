# Phase 34B RootService stream crash hotfix

## Evidence

The real-device log showed the privileged process dying repeatedly in background reader threads:

- `FATAL EXCEPTION: chrootctl-bridge-stdout`
- `FATAL EXCEPTION: chrootctl-bridge-stderr`
- `java.io.InterruptedIOException: read interrupted by close() on another thread`
- `com.mikeyphw.chrootctl.root.BridgeProcess.drain`

This is not a Compose or repository error. The app recovered the UI state, but the libsu RootService process was killed because a daemon reader thread let a stream-close exception escape uncaught.

## Fix

`BridgeProcess.drain` now catches every reader-thread failure, records a bounded Android-side diagnostic, and lets the root-service Binder process stay alive. The fix protects both normal bridge invocations and streaming foreground operations.

The captured diagnostics are appended to `errorOutput` as `android-stream-drain` notes. They are not written to stdout, so JSON responses from the Python bridge remain parseable.

## Boundaries preserved

- `compileSdk = 36`
- `targetSdk = 36`
- `warningsAsErrors = true`
- `abortOnError = true`
- only `OldTargetApi` is ignored by lint
- the fixed AIDL interface remains allowlisted
- no WebView or HTTP server is introduced
- no arbitrary shell command bridge is introduced

## Acceptance

background stream readers must not kill the libsu RootService process when the bridge process exits, times out, is destroyed, or closes its stdout/stderr while another thread is reading.
