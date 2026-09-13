# CHR18 Android operation/Room/recovery engine

Overlay 18 of 20 closes the Android operation persistence and recovery cluster.
It changes the app from a state-only recovery surface into a metadata-driven
operation engine backed by Room reconciliation.

## Closure

- Foreground operation admission no longer silently discards a second request.
  The service emits an explicit blocked notification and preserves the already
  admitted/persisted operation for reconciliation.
- Recovery polling is bounded. A missing or failing backend cannot keep the
  foreground service in an infinite loop; persisted state remains available for
  Activity-driven refresh or later service restart.
- Room operation rows now preserve parent lineage, request/retry JSON, warnings,
  next steps, retry flags, recovery actions, refresh/reconcile clocks and
  missing-backend tombstones.
- Home refresh treats the backend operation list as authoritative. Active local
  rows absent from the backend journal are marked interrupted with
  `MISSING_BACKEND_OPERATION` rather than shown as immortal running ghosts.
- `operation_interrupted` and `bridge_stream_interrupted` map to the interrupted
  Room state; they are no longer left as running progress rows.
- Retry and retry-with-fixes buttons are gated by backend replay metadata instead
  of state alone. Preview-bound or redacted requests force a new preview/manual
  re-entry path.
- Snapshot recovery and cancel affordances are denied for missing-backend or
  already-cancelling rows.
- Request discovery uses `operations.find_request`, an exact request-id lookup,
  instead of scanning the most recent 1,000 operation records.
- Recovery confirmation state is process-local, not saveable across Activity
  recreation.

## Evidence

`ValidateAndroidOperationRoomRecovery` enforces the source invariants for this
phase. Focused Android unit tests cover recovery eligibility and interrupted
state mapping, while Go source-gate tests make this overlay visible to the later
release gate.
