# Post-WR12 five-pass roadmap and CLI parity audit

This audit uses the post-WR12 repository as authority and checks the complete OV01–OV08 + WR01–WR12 promise chain after retirement of the standalone Android app.

## Pass 1 — roadmap promise inventory

All promised workspaces remain present: Chroots, Create/install recovery, Users, Services, Snapshots, Storage/artifacts, Catalog/packages, Maintenance/support/repair, Diagnostics/debug/smoke/readiness, Transfer/Rclone, Operations, Logs, and Settings. WR12 retirement guards, root-module packaging authority, and the protocol-v1 bridge remain active.

## Pass 2 — bridge/capability contract

A real gap was found: WR11 promised that query/preview/**run** calls are the intersection of the WebUI allow-list and live backend capabilities, but several run helpers only checked the static allow-list or called `app run` directly. Transfer preview also bypassed capability negotiation. This hotfix gates every typed query, preview, and run path against `app capabilities`, adds the missing protocol-v1 stream check to the generic operation helper, and removes duplicate shadowed smoke/debug function declarations.

## Pass 3 — CLI management parity

The WebUI has management parity with the normal safe CLI surface by semantic capability, not by duplicating every CLI spelling:

| CLI surface | Root-module WebUI authority |
| --- | --- |
| version/status/doctor/logs | backend chip, Chroot details, Logs & diagnostics, Readiness |
| mount/unmount/start/restart | Chroots lifecycle Start/Stop/Restart; Stop remains the bounded legacy `unmount` CLI invocation |
| install/upgrade | Create + typed lifecycle Upgrade |
| chroots list/show/remove/rename | Chroots; remove/start/restart/upgrade typed, rename bounded legacy CLI |
| chroots export/import/validate-import | Transfer typed preview/run and import inspection |
| chroots diff | Catalog package comparison |
| snapshots * | Snapshots |
| transfer * | Transfer |
| remotes * | Rclone |
| artifacts * | Storage / managed artifacts |
| events list | Operations + Logs event views |
| support-bundle | Maintenance support bundle |
| users * | Users |
| tools/addons * | Catalog |
| enable/disable/journal | Services |
| magisk render | Settings module-build preview/run |
| clipboard get/set | browser clipboard integration for WebUI-facing copy/paste; root-module clipboard daemon remains backend/module infrastructure |

The following CLI surfaces are intentionally **not** WebUI parity targets because exposing them would violate the roadmap security boundary or they are CLI/bootstrap machinery: `exec`, interactive `start`/`run --boot` shell semantics, `clipboard daemon run/start/stop` process control, `completion`, `wrapper install`, hidden `__complete`, arbitrary filesystem output flags, and arbitrary shell/package-manager/rclone command execution. `fix-tty` remains an internal runtime prerequisite rather than a standalone browser control.

## Pass 4 — security and retirement invariants

No arbitrary-shell WebUI API is introduced. Backend capability negotiation rejects protocol mismatch and any backend advertising arbitrary shell. Credential-bearing transfer/Rclone flows stay typed and bounded. WR12 continues to reject Android application source/build definitions, the retired Android Devtool target, and APK CI authority.

## Pass 5 — executable convergence

The hotfix adds an executable regression seal for capability coverage and duplicate/shadowed bridge helpers. Final validation runs JS syntax checks and focused Go tests for module, bridge, operations, users, services, Rclone, catalog, and repoctl. The root-module Devtool target remains the packaging authority.
