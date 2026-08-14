# Phase 34D: Protocol capabilities probe hardening

Android discovers only the **active** root-module launcher at `/data/adb/modules/chrootctl-magisk/system/bin/chrootctl`. Pending `modules_update` trees are diagnostic state and are not runtime candidates until the module manager activates them after reboot. Disabled or pending-removal active modules are also excluded.

Every remaining executable or Python fallback is accepted only after `app capabilities` returns a protocol-1 JSON envelope. The capabilities command remains intentionally lightweight and service-free so it can report `runtimeHealth.status=degraded` when the full service container is not yet ready.

An incompatible `CHROOTCTL_EXECUTABLE` override is diagnostic and does not suppress normal discovery. API 36, strict lint, Binder recovery, stream-drain protection, and the no-WebView/no-HTTP-server boundary remain preserved.
