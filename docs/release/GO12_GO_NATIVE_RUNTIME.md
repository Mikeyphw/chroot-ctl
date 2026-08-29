# GO12 Go-native module runtime

GO12 replaced the module's Python/Nuitka userspace with the complete Go `cmd/chrootctl` Android/arm64 executable.

The runtime build requires an Android arm64 C compiler because the SQLite driver uses CGO. Current builds are owned by `cmd/repoctl` and use `GOOS=android GOARCH=arm64 CGO_ENABLED=1`:

```sh
scripts/repoctl build-runtime --jobs 2
```

New runtime artifacts contain only `chrootctl` plus `runtime-manifest.json`. The manifest uses schema 2 and `runtimeKind: go-native`. Bridge protocol remains version 1.

GO12 originally retained read compatibility for older schema-1 Nuitka artifacts during the transition. GO14 subsequently removed that Android fallback; current runtime resolution and release validation accept Go-native runtime artifacts only.
