# ChrootCTL Android architecture

## Ownership boundaries

- Kotlin owns Android lifecycle, Compose presentation, notifications, Room cache, file descriptors, and Binder transport.
- Python owns chroot discovery, validation, previews, installation, lifecycle, users, services, snapshots, transfer, recovery, and support behavior.
- The bridge owns protocol versioning, allowlisted operation dispatch, redaction, durable operation state, and NDJSON progress events.
- Room is a cache and local timeline. Python state remains authoritative.

## Process path

```text
Compose feature screen
  -> feature ViewModel/repository
  -> RootServiceClient
  -> fixed IChrootRootService AIDL
  -> ChrootRootService (UID 0)
  -> RuntimeResolver + BridgeProcess
  -> chrootctl app JSON/NDJSON bridge
  -> existing services/* domain layer
```

## Security contract

The Binder interface exposes fixed capabilities only. It must never include an arbitrary command string, shell script body, environment injection, executable path supplied by the UI, or unvalidated operation name.

Bridge requests contain a protocol version, request ID, allowlisted operation name, and JSON object payload. Sensitive keys are redacted before operation requests, events, results, or retry payloads are persisted.

## Phase 0-4 scope

The initial bridge supports read-only dashboard, status, doctor and chroot queries; removal/export previews; and a persistent read-only refresh operation. Later overlays extend the same operation registry rather than adding ad hoc Binder methods.

## Persistent operation layout

The operation root is derived from the configured registry directory:

```text
<database parent>/operations/
  records/<operation-id>.json
  events/<operation-id>.jsonl
  cancel/<operation-id>
  locks/<scope>.lock
```

Records use queued, running, cancelling, cancelled, succeeded, failed, interrupted and blocked states. Active records whose process disappeared are recovered as interrupted.
