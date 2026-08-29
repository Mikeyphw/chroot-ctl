# GO09 — Shared Go service layer

GO09 composes the Go registry, controller, users/catalog, operations, snapshots,
transfer and host/runtime primitives behind `internal/services.Container`.

The service layer is intentionally transport-neutral. GO10 and GO11 must call
these services rather than duplicate business logic in the Android bridge or
human CLI.

Delivered surfaces include system/doctor/dashboard/logs, chroots, users,
catalog, install/upgrade, snapshots, transfer export/inspect/import, preview,
registry repair, audit, support bundles, lifecycle/module runtime status,
release-readiness evidence and service-unit control.

Compatibility rules retained during migration:

- SQLite and filesystem mutations remain fail-closed and transactional;
- paths are constrained to configured roots before destructive operations;
- service processes use verified PID/PGID/start-time/boot-id identities;
- support and operation payloads pass through shared secret redaction;
- final-seal evidence never invents a passing state;
- legacy bridge-facing field/check names remain stable until the later schema
  cutover phases.

Python remains the production backend until the bridge and CLI parity gates are
complete.
