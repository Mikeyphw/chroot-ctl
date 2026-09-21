# Root-module rotating logging hotfix

All root-module operational diagnostics are consolidated under `/data/local/tmp/chrootctl`.

- `chrootctl.log`: redacted Go backend/application log (4 MiB, five backups).
- `module.log`: installer, post-fs-data, service, helper and uninstall lifecycle (1 MiB, five backups).
- `transport.log`: stable launcher/WebUI backend invocation metadata only; raw request JSON/arguments are never logged (1 MiB, five backups).
- `services/*.log`: managed chroot service logs with five backups.
- `clipboard-daemon.log`: clipboard daemon diagnostics with five backups.

Directories are private (`0700`) and regular logs are `0600`. Existing Android configs using the old default `/sdcard/.logs/chrootctl.log` and `/data/adb/chrootctl/logs/services` normalize to the new root; explicit custom paths remain unchanged.

Module version: 1.3.3 / versionCode 18.
