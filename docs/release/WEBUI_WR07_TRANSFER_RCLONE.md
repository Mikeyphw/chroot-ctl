# WebUI Android-retirement WR07/12 — Transfer and Rclone convergence

WR07 closes the remaining transfer/Rclone parity and safety gaps rather than adding a second transfer implementation.

- Import and export remain backend-authoritative through `transfer.import_preview`, `transfer.preview_export`, `transfer.import`, and `transfer.export`.
- Preview proof is now mandatory in the WebUI bridge before either transfer operation can run.
- Remote paths can only enter transfer forms through the credential-free `rclone://` browser handoff.
- Transfer passwords are scrubbed after blocked previews, failures, and terminal operations.
- Rclone status/list remain query-only and do not expose secret option values.
- Staged `rclone.conf` import is surfaced as a persistent operation with progress and cancellation; backend ownership/validation/removal of the staged credential copy remains authoritative.
- WebUI does not expose arbitrary rclone command execution or configuration secrets.
