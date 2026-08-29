# Native module runtime parity

The supported Magisk/KernelSU runtime is the Go-native Android arm64 executable under `runtime/arm64-v8a/chrootctl`.

Module packaging validates the runtime seal before copy, validates the copied seal again, and validates the final ZIP. The checked-in Android resolver constants and `docs/release/compatibility-manifest.json` are checked against the same release identity sources.

The former Nuitka onefile implementation is retired. Current Android runtime resolution, module packaging, and final release validation do not accept it as an execution fallback.
