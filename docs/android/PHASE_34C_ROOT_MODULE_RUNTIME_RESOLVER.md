# Phase 34C: active-only root module runtime resolver

The native Android bridge executes the chrootctl root-module launcher only from the manager's active module tree:

`/data/adb/modules/chrootctl/system/bin/chrootctl`

`/data/adb/modules_update/chrootctl` and `/data/adb/ksu/modules_update/chrootctl` are observed for diagnostics only. Pending updates are diagnostics only and are never executable runtime candidates before reboot activation. A module carrying `disable` or `remove` is also not executable.

After the active module candidate, discovery can continue through the magic-mount `/system/bin/chrootctl`, the legacy adb-root install, Termux executables, and Python-module fallbacks. An invalid `CHROOTCTL_EXECUTABLE` override does not suppress normal fallback discovery.

Every selected candidate must still answer the protocol-1 capabilities probe. API 36, fixed AIDL, foreground-operation behavior, strict lint, and the no-WebView/no-HTTP-server boundaries remain unchanged.
