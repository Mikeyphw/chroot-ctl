# Root module standalone async + KernelSU fallback hotfix — 1.3.7 / 22

This hotfix closes two WebUI execution failures found after the 1.3.6/21
KernelSU spawn diagnostics release.

## Standalone browser mutations

The standalone WebUI no longer holds a mutating `/api/v1/run/*` request open
for the complete operation. The HTTP endpoint starts the typed operation against
the server lifetime, returns `202 Accepted` with the stable request/operation
identity as soon as it is available, and the WebUI follows progress from the
persistent operation journal.

Mutation-start POSTs are explicitly non-replayable. If the browser loses the
start response after the backend accepted the request, the WebUI recovers the
operation with `operations.find_request` using the same request ID instead of
re-sending the one-shot preview-bound mutation. This prevents an accepted
install from consuming its preview and then being replayed as
`PREVIEW_NOT_FOUND`.

Standalone cancellation uses the typed `/api/v1/operations/<id>/cancel` route and that cancellation POST is also non-replayable. Active operations suppress the standalone server idle shutdown, while authenticated polling renews the browser session before expiry so a long-running install does not lose its control channel merely because it crosses the normal session lifetime.

## KernelSU without working `ksu.spawn`

A failed harmless streaming probe no longer makes mutating operations
unavailable. When ordinary `ksu.exec` is healthy, the WebUI runs the typed
operation exactly once through that compatibility transport. The UI explicitly
reports that live progress and cancellation are limited while this fallback is
active, because this KernelSU manager buffers `exec` output until the command
finishes.

A real mutating `ksu.spawn` failure is still never replayed: fallback is selected
only when the read-only streaming preflight fails before mutation. The fallback
itself never retries the preview-bound mutation.

## Install diagnostics UX

The install failure dialog now includes a **Copy error** action beside Retry and
Close. It copies the rendered, redacted diagnostic text through the standard Clipboard
API. If that API is unavailable, the UI keeps the diagnostic visible and asks the
user to select it manually; no legacy `document.execCommand` execution path is used.

## Version

The root-module payload is 1.3.7 / versionCode 22. The checked-in compatibility
manifest and version contract tests are updated with the same values.
