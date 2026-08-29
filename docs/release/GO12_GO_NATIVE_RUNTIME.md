# GO12 Go-native module runtime

GO12 replaces the module's Python/Nuitka userspace with the complete Go `cmd/chrootctl` Android/arm64 executable.

The build requires an Android arm64 C compiler because the SQLite driver uses CGO. `scripts/build-native-android-runtime.py` resolves Termux clang or an Android NDK clang and builds with `GOOS=android GOARCH=arm64 CGO_ENABLED=1`.

New runtime artifacts contain only `chrootctl` plus `runtime-manifest.json`. The manifest uses schema 2 and `runtimeKind: go-native`. Validation still accepts the old schema-1 `nuitka-onefile` form solely so an already-installed old module can be diagnosed during migration.

Bridge protocol remains version 1. Compatibility-manifest schema remains version 2 until GO13.
