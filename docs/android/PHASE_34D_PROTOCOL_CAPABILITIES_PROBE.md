# Phase 34D: Protocol capabilities probe hardening

Phase 34D fixes the runtime-discovery state where Android reports that it found chrootctl runtime candidates, but none exposed the protocol-1 Android bridge.

The Android resolver already probes the repo-built root-module launcher first, including:

- `/data/adb/modules/chrootctl-magisk/system/bin/chrootctl`
- `/data/adb/modules_update/chrootctl-magisk/system/bin/chrootctl`
- `/data/adb/ksu/modules/chrootctl-magisk/system/bin/chrootctl`
- `/data/adb/ksu/modules_update/chrootctl-magisk/system/bin/chrootctl`

Those candidates are still accepted only after `app capabilities` returns a protocol-1 JSON envelope. Phase 34D makes that capabilities command intentionally lightweight and service-free: it no longer constructs the full service container before replying to the protocol probe.

This matters on fresh or partially bootstrapped module installs. If the service layer is not ready yet, `chrootctl app capabilities` still exposes the bridge protocol and reports `runtimeHealth.status=degraded` with warning/next-step metadata. Later state/query/run commands still go through the full service container and can report the actual dependency, configuration, or backend failure.

Preserved boundaries:

- API 36 remains pinned.
- Strict lint remains enabled.
- Only `OldTargetApi` is ignored.
- The Phase 29F Binder recovery remains intact.
- The Phase 34B stream-drain crash fix remains intact.
- The Phase 34C root-module-first resolver remains intact.
- No WebView, HTTP server, or arbitrary shell bridge is introduced.
