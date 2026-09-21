# WebUI Overlay 7 of 8 — Logs & diagnostics

This overlay promotes **Logs** from a roadmap placeholder to a bounded diagnostic workspace.

## Delivered contracts

- Reads chrootctl logs only through the typed `logs.list` backend query.
- Supports backend severity thresholds and bounded 100/200/500-line views.
- Renders structured log entries as text; WebUI never interprets log content as HTML.
- Runs authoritative `system.doctor` checks for the selected chroot and preserves PASS/WARN/FAIL plus backend next-step guidance.
- Lists only services returned by `services.list` for the selected chroot and reads their bounded journals through `services.journal`.
- Does not display backend log/config filesystem paths or add arbitrary-file readers.
- Backend read failures remain visible and are not collapsed into an empty-success state.

The existing CHR16 backend remains the authority for log redaction, private file permissions, bounded reads, and journal sanitization.

## Deferred gate

This is overlay 7 of 8 and is intended to be applied with `--no-validate`. The embedded validator remains available to the final campaign validation.

## Final promise-audit repair

Logs now includes a backend/module/Rclone readiness card in addition to doctor, service journals, operation events, filtering, follow mode and copy actions. Known doctor checks whose detail/next fields contain host filesystem locations are rendered with path-free guidance, and diagnostic read failures no longer echo backend error strings that may contain private log/database/config paths.
