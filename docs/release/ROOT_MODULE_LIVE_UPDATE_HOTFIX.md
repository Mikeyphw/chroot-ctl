# Root-module live-update hotfix

Existing `chrootctl-magisk` installations now activate a validated module update in the current `/data/adb/modules/chrootctl-magisk` tree during installation while retaining the root manager staged copy for reboot fallback.

## Transaction

`customize.sh` detects an existing active module and a distinct installer `MODPATH`. It clones the active tree to a sibling candidate so manager-owned marker files are preserved, overlays only chrootctl-owned payload roots from the newly extracted module, verifies the required launcher/runtime/package-manifest files and executable bits, then swaps the candidate into the active path with same-filesystem renames. The previous active tree remains a rollback directory until the swap succeeds.

On successful activation, `post-fs-data.sh` refreshes `/data/adb/chrootctl/bin/chrootctl` and `service.sh` reloads module runtime behavior unless the module is disabled or pending removal. The root-manager staged update remains present, so its normal reboot promotion remains a fallback and preserves manager bookkeeping.

A first install has no active tree to replace and follows the root manager's normal activation model. Root-manager magic-mount changes outside chrootctl's own launcher/runtime/WebUI may still require reboot.

The module package version is 1.3.1 (`versionCode=16`) so managers and diagnostics can distinguish this behavior from the pre-live-update package.
