# Phase 34C: Root-module runtime resolver hotfix

Phase 34C corrects the Android backend discovery order to match what this repository actually builds and installs.

The repo renders a Magisk/KernelSU root module with id `chrootctl-magisk`. Its launcher is packaged at `system/bin/chrootctl` inside the module. The Android app must therefore look for the module launcher directly before it falls back to magic-mount visibility, legacy development installs, or Termux binaries.

## Runtime search order

The Android root service now probes executable `chrootctl app capabilities` candidates in this order:

1. `/data/adb/modules/chrootctl-magisk/system/bin/chrootctl`
2. `/data/adb/modules_update/chrootctl-magisk/system/bin/chrootctl`
3. `/data/adb/ksu/modules/chrootctl-magisk/system/bin/chrootctl`
4. `/data/adb/ksu/modules_update/chrootctl-magisk/system/bin/chrootctl`
5. `/system/bin/chrootctl`
6. legacy adb-root install at `/data/adb/chrootctl/bin/chrootctl`
7. Termux user install at `/data/data/com.termux/files/home/.local/bin/chrootctl`
8. Termux package install at `/data/data/com.termux/files/usr/bin/chrootctl`

The existing Python-module fallback remains available after executable candidates.

## Compatibility guard

Every candidate is still required to expose the Android bridge protocol by returning a protocol-1 capabilities envelope. Stale regular CLI binaries, wrong module launchers, non-JSON output, unsupported bridge protocol versions, and missing executables are skipped rather than trusted.

The `CHROOTCTL_EXECUTABLE` override remains highest priority for explicit diagnostics and developer recovery.

## Preserved boundaries

- Android API 36 is preserved.
- `compileSdk = 36`
- `targetSdk = 36`
- `warningsAsErrors = true`
- `abortOnError = true`
- only `OldTargetApi` is ignored by lint
- Phase 29F Binder recovery remains unchanged
- no WebView backend is reintroduced
- no HTTP server is reintroduced
- no arbitrary shell bridge is added

This phase only changes backend discovery. It does not alter Activity, Tools, Install, Chroots, the root-service process model, or the bridge protocol surface.
