# Root-module WebUI transport hotfix

This post-WR12 hotfix fixes the KernelSU WebUI transport getting stuck at **Checking backend** even while the bundled Go backend is healthy.

## Root causes closed

- The WebUI transport previously required `ksu.spawn`; managers exposing only `ksu.exec` could lose the synchronous bridge exception before the caller attached an error listener, leaving startup Promises unresolved forever. The adapter now supports both APIs and defers synchronous native errors until listeners are attached.
- KernelSU's native WebView `spawn` implementation constructs a root-shell command by concatenating the provided argument strings. Raw JSON passed via `--request-json` therefore crossed a shell boundary without quoting. Every command/argument token is now POSIX single-quoted before it is handed to native `ksu.spawn`, preserving JSON and user-controlled values byte-for-byte.
- Backend discovery now prefers the stable launcher `/data/adb/chrootctl/bin/chrootctl`, then the module-owned runtime, and only then `/system/bin/chrootctl`. This avoids depending on a magic-mount refresh for WebUI operation access.
- Non-streaming bridge calls now have a bounded timeout and surface `WEBUI_BRIDGE_TIMEOUT` instead of leaving the UI indefinitely on a loading state.

## Validation

The `chrootctl_root_module` target now syntax-checks `kernelsu.js` and runs `internal/module/webui_transport_test.mjs`. The transport test seals native-spawn argument quoting, synchronous-error delivery, and the exec-only compatibility fallback.

The module version is bumped to **1.3.2 / versionCode 17** so the fixed WebUI payload can be distinguished from 1.3.1.
