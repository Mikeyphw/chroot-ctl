# GO15 — Go-native build and release tooling

`cmd/repoctl` is the authoritative repository tooling entrypoint.

## Commands

- `repoctl build-runtime` — cross-build and seal the Android/arm64 CGO Go runtime.
- `repoctl build-module` — render/validate/zip the Go-native Magisk/KernelSU module and optionally install it with KernelSU.
- `repoctl build-source` — create a deterministic source tarball without following symlinks or packaging caches/build outputs.
- `repoctl validate` — Go tests and vet.
- `repoctl release` — validate, build runtime/module/source artifacts, and emit SHA-256 sidecars.
- `repoctl doctor-cross-arch` — report foreign-architecture execution support.

`scripts/release` is the production release wrapper. `build.sh` simply invokes `go run ./cmd/repoctl build-module`. The historical Python scripts remain compatibility shims or legacy test helpers until GO17; they are no longer part of the production build/package path.

The historical `scripts/final-release-seal.py` remains only as a GO16 differential/legacy test oracle and is not invoked by the production build/package/release path.
