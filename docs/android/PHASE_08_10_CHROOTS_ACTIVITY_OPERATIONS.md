# Phase 08-10: Chroot detail, activity detail, and foreground operations

This overlay continues the Android replacement path after the read-only shell landed.
It keeps the WebUI available while moving more of the human-facing surface into the
native app.

## Phase 08: Chroot list-detail

- Chroot cards are selectable.
- The selected chroot exposes a read-only detail panel.
- Detail refresh calls the bridge for `chroots.get`, `system.status`, and `system.doctor`.
- Status and doctor checks are cached by chroot-scoped Room rows.
- The UI shows registry status, release, path, bridge payload size, and checks.

## Phase 09: Activity detail and operation events

- Operation cards are selectable.
- The selected operation exposes a detail panel with persistent state and timeline events.
- The bridge now exposes `operations.get` as a query operation.
- Android can refresh operation detail through the fixed root service `operationState` call.
- Streamed NDJSON events are cached as `OperationEventEntity` records.

## Phase 10: Foreground operation service

- `ChrootOperationService` runs the allowlisted `system.refresh` operation in the foreground.
- `OperationNotificationController` owns the notification channel and progress updates.
- The notification uses the `dataSync` foreground-service type and SDK 36-compatible contracts.
- Cancellation is routed back through `cancelOperation`; no arbitrary shell surface is added.
- Home exposes a native action to run the foreground refresh operation and then review Activity.

## Guardrails

- SDK remains pinned to 36.
- The app still contains no WebView.
- The fixed AIDL still exposes only typed bridge calls.
- No broad storage or package visibility permission is introduced.
- Mutating install/lifecycle flows are still deferred to later phases.
