# ChrootCTL Android architecture

## Ownership boundaries

- Kotlin owns Android lifecycle, Compose presentation, notifications, Room cache, file descriptors, and Binder transport.
- Go owns chroot discovery, validation, previews, installation, lifecycle, users, services, snapshots, transfer, recovery, support behavior, persistent operations, and authoritative registry state.
- The Go bridge owns protocol versioning, allowlisted operation dispatch, redaction, durable operation state, and NDJSON progress events.
- Room is an Android-side cache and local timeline; the Go registry/service layer remains authoritative.

## Process path

```text
Compose feature screen
  -> feature ViewModel/repository
  -> RootServiceClient
  -> fixed IChrootRootService AIDL
  -> ChrootRootService (UID 0)
  -> RuntimeResolver + BridgeProcess
  -> chrootctl app JSON/NDJSON protocol-v1 bridge
  -> internal/services transport-neutral Go layer
```

## Security contract

The Binder interface exposes fixed capabilities only. It must never include an arbitrary command string, shell script body, environment injection, executable path supplied by the UI, or unvalidated operation name.

Bridge requests contain a protocol version, request ID, allowlisted operation name, and JSON object payload. Sensitive keys are redacted before operation requests, events, results, or retry payloads are persisted.

## Persistent operation layout

The operation root is derived from the configured registry directory:

```text
<database parent>/operations/
  records/<operation-id>.json
  events/<operation-id>.jsonl
  cancel/<operation-id>
  locks/<scope>.lock
```

Records use queued, running, cancelling, cancelled, succeeded, failed, interrupted and blocked states. Active records whose verified process identity disappeared are recovered as interrupted.
