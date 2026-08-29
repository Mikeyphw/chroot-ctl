# Native Android runtime

The supported module runtime is the complete Go `cmd/chrootctl` executable built for Android arm64 with CGO enabled for SQLite.

Build on Termux or with an Android NDK toolchain:

```bash
PYTHONPATH=src python3 scripts/build-native-android-runtime.py --jobs 2
```

The builder resolves Termux clang first, otherwise an Android NDK `aarch64-linux-android26-clang`, and invokes Go with `GOOS=android GOARCH=arm64 CGO_ENABLED=1`.

The output layout is:

```text
out/native-runtime/arm64-v8a/
├── chrootctl
└── runtime-manifest.json
```

New runtime manifests use schema 2 and `runtimeKind: go-native`. They seal the backend version, bridge protocol, compiler identity, and SHA-256/size/executable bit for every runtime file. Schema-1 `nuitka-onefile` manifests are accepted only as a migration-time read compatibility path for already-installed older modules.
