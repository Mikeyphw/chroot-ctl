# Native Android runtime

The supported module runtime is the complete Go `cmd/chrootctl` executable built for Android arm64 with CGO enabled for SQLite.

Build with the Go-native repository tool:

```sh
scripts/repoctl build-runtime --jobs 2
```

The builder resolves an Android-capable arm64 C compiler and invokes Go with `GOOS=android GOARCH=arm64 CGO_ENABLED=1`.

The output layout is:

```text
out/native-runtime/arm64-v8a/
├── chrootctl
└── runtime-manifest.json
```

Runtime manifests use schema 2 and `runtimeKind: go-native`. They seal backend version, bridge protocol, compiler identity, and SHA-256/size/executable metadata for the runtime files. Current Android runtime resolution does not accept Python or legacy Nuitka candidates.
