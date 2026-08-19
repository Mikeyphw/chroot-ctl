# Phase 29F: Binder death recovery

## Device failure

After Phase 29E was installed, every bridge-backed screen reported `DeadObjectException`. The Android process still retained an AIDL proxy whose libsu root-service process had died. The old client cleared the proxy in some `ServiceConnection` callbacks, but it did not consistently release the dead libsu binding, did not register an `IBinder.DeathRecipient`, and dispatched calls without a Binder health probe.

## Recovery contract

Phase 29F makes the privileged transport disposable and reconstructible:

- Register `IBinder.linkToDeath` for every accepted root-service Binder.
- Clear the exact matching proxy when its process dies, disconnects, or reports a dead binding.
- Release the libsu `ServiceConnection` and create a fresh binding on the next request.
- Probe `isBinderAlive` and `pingBinder()` before each AIDL transaction.
- Retry a read-only request at most once after a transport failure.
- Never replay operation start, cancellation, import, or export transactions because the remote side may have accepted them before the Binder response was lost.
- Replace bare `DeadObjectException` UI messages with an actionable transport explanation.
- Reset timed-out connections instead of retaining a possibly wedged proxy.

The root service remains a normal, client-bound libsu service. Daemon mode is intentionally not enabled. The allowlisted AIDL surface and Python bridge trust boundary are unchanged.

## Replay classification

Safe one-time replay:

- service status
- capabilities
- query
- preview
- operation status

No automatic replay:

- start operation
- cancel operation
- import transfer
- export transfer

## Preserved gates

- `compileSdk = 36`
- `targetSdk = 36`
- `warningsAsErrors = true`
- `abortOnError = true`
- only `OldTargetApi` is ignored by the Phase 29C lint policy
- no WebView, HTTP server, arbitrary shell AIDL method, or daemon root-service mode
