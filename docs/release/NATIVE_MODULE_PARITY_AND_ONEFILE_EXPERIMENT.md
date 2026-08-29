# Native module runtime parity

The supported Magisk/KernelSU runtime is now the Go-native Android arm64 executable under `runtime/arm64-v8a/chrootctl`.

Module packaging validates the runtime seal before copy, validates the copied seal again, and then validates the final ZIP. The checked-in Android resolver constants and `docs/release/compatibility-manifest.json` are checked against the same release identity sources.

The former Nuitka onefile implementation is no longer a supported build path. Its schema-1 manifest identity remains readable only so an older installed module can be diagnosed during the migration window.
