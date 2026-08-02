# Phase 29: Real-device bugfix seal

Phase 29 fixes bugs found during the post-Phase 28 audit without adding new feature scope.

## Fixes

- Python and Android now share one managed transfer artifact root contract.
- `transfer.artifact_root` exposes the active managed artifact root to the bridge.
- `transferToDescriptor` uses canonical path containment instead of string-prefix matching.
- Smoke result handoff treats failed smoke checks as failures even when the operation record completed normally.
- `includeOptional=false` is honored by the smoke plan.
- Home exposes an Android 13+ notification-permission action so long-running foreground operation progress remains visible.
- Legacy browser upload/TUS service helpers and web-control lifecycle helpers are removed after WebUI retirement.
- Devtool runtime reports/state/test history are ignored and deliberately not targeted by overlay inventory because `.devtool/*` is Devtool-owned metadata.

## Guardrails

- SDK remains pinned to 36.
- No WebView or arbitrary-shell AIDL is introduced.
- Storage import/export remains SAF/descriptor based.
- Managed artifact export remains root-validated before copying to a user-selected document.
