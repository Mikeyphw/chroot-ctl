# CHR16 — Logging, diagnostics, audit & evidence

Status: implemented as overlay 16 of 20.

`ValidateLoggingDiagnosticsAuditEvidence` is the executable source gate for this overlay. It prevents the CHR16 fixes from becoming prose-only by checking the logging, redaction, support-bundle, audit, journal, bridge/CLI, Android secret-clearing, and roadmap-evidence invariants in source.

## Sealed scope

- Log files are created privately (`0600`) and log directories are created under private owner-only permissions.
- Oversized log files rotate before append, preventing unbounded growth on device storage.
- Runtime log output is redacted before console/file persistence and before log-list surfaces hand lines to CLI or Android consumers.
- `logs --level` is implemented as a severity threshold, not a substring match.
- Log reading reports real I/O and scanner failures instead of silently returning partial success.
- `logs --follow`, `journal --follow`, and `run --logs --follow` now preserve redaction and filtering while streaming appended lines.
- Operation records, event journals, cancel markers, and journal directories are written with private permissions.
- Audit events redact event messages, actor/target values, and metadata before persistence and before model export.
- `events list` is bounded at the registry layer as well as the parser layer.
- Support bundles are managed `tar.gz` evidence artifacts, not mislabeled ZIP files.
- Support bundles include chroot rows, host doctor evidence, lifecycle state, module runtime state, audit events, operation records, configuration paths, optional extra payload, and a redacted tail of `chrootctl.log`.
- Support-bundle failures are fail-closed: evidence component errors abort the bundle rather than reporting partial success.
- Support-bundle exports are atomically promoted, registered as managed artifacts, checksum-tagged, and recorded as audit events.
- Android clears the in-memory import password immediately after dispatching a transfer-import operation.
- Production audit events cover user mutations, service lifecycle mutations, catalog applies, snapshot creation, and support-bundle export; mutation failures are captured where the service boundary can observe them.
- Human and JSON CLI error responses pass through the shared redaction boundary before emission.
- Bounded log-tail reads scan backwards instead of loading the whole file, reject symlinks, cap individual records, and report exact truncation when an older matching record exists.
- Service lifecycle logs rotate when oversized and remain private owner-only files.
- Android live-log refreshes cancel the prior in-flight refresh before starting another, and user password/confirmation review state is cleared immediately after dispatch.

## Deferred to later overlays

CHR17 owns bridge protocol V2 convergence. CHR18–CHR20 own deeper Android persistence, Room-backed operation recovery, workspace correctness, adaptive navigation, and the final release seal.
