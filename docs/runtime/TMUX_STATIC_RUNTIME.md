# Bundled static tmux runtime

chrootctl owns a read-only Android/ARM64 tmux runtime. It is a backend component for persistent interactive sessions and explicitly persistent jobs; it does not replace structured chrootctl operations and the WebUI must not invoke tmux directly.

TMUX-01 pins tmux 3.7c, libevent 2.1.12-stable and ncurses 6.5. The production toolchain is pinned to Android NDK 29.0.14206865, API 24, and its Bionic static libc (`libc: bionic-static`). The build rejects any other NDK revision unless the pin is deliberately changed in source. It uses the NDK AArch64 compiler, static archives, no UPX, `-trim`-style source path normalization via compiler prefix maps, a fixed locale/timezone, and no ELF build-id. `scripts/tmux/build-static-android-arm64.sh` verifies every source archive by SHA-256 before extraction and rejects a result with an ELF interpreter or `DT_NEEDED` entries.

The packaged files are `runtime/arm64-v8a/tmux`, `tmux-runtime-manifest.json`, and `tmux.sha256`. The ordinary native runtime manifest also inventories these files, so module validation covers their bytes and executable mode.

Licensing/provenance: tmux is ISC licensed; libevent is BSD-3-Clause; ncurses uses the permissive ncurses license. Release/source distributions must retain the applicable upstream license notices. Source URLs and exact SHA-256 values are encoded in the build script and provenance manifest. The binary is intentionally not compressed with UPX.

Reproducibility check: build twice with the same NDK/toolchain and `SOURCE_DATE_EPOCH`, then compare `sha256sum out/tmux/arm64-v8a/tmux`. A differing digest is a release-seal failure unless a deterministic exception is identified and documented with toolchain evidence.


Build verification policy: TMUX-01 never executes the produced Android target binary and does not depend on an embedded human-readable version string. Version and source identity are sealed in `tmux-runtime-manifest.json`; the canonical verifier checks ELF64/AArch64 structure, fully-static linkage, checksum integrity, and pinned provenance. Real-device execution is deferred to the TMUX-07 device seal.

Devtool lifecycle integration: restore downloads and SHA-verifies the pinned source archives; build produces and verifies the runtime; test runs TMUX-01 contract tests; lint checks the shell integration; package verifies the expanded runtime, checksum sidecar, and exact tmux bytes inside the module ZIP.

## Android API 24 glob compatibility

Bionic exposes `glob()` and `globfree()` only from Android API 28. TMUX-01 keeps the runtime floor at API 24 and therefore links a narrow in-tree compatibility implementation for tmux `source-file` path expansion when `ANDROID_API < 28`. The implementation supports the exact tmux 3.7c call contract (`flags == 0`), including `*`, `?`, bracket matching through `fnmatch()`, backslash-escaped literal path components, hidden-file semantics, deterministic sorting, `GLOB_NOMATCH`, and `globfree()`. API 28+ builds use Bionic directly.

### Verification contract

`verify-static-android-arm64.sh` is the single authoritative runtime verifier. It never executes the target tmux binary and does not use `/tmp`; it checks ELF64/AArch64 identity, absence of `PT_INTERP`/`DT_NEEDED`, checksum integrity, and the pinned runtime/source provenance recorded in `tmux-runtime-manifest.json`. The build producer does not duplicate those checks.

### Resumable native build cache

The native builder records `out/tmux-build/.chrootctl-tmux-build-fingerprint` only after
the tmux ELF, canonical manifest, and checksum are complete. A later validation run
reuses that output only when the fingerprint still matches all pinned source hashes,
API/NDK/toolchain/build flags and compatibility-source hashes, and the canonical ELF
verifier passes. Set `CHROOTCTL_TMUX_FORCE_REBUILD=1` to bypass the cache.

A complete pre-fingerprint TMUX-01 build may be adopted without recompilation only
when `tmux`, `tmux-runtime-manifest.json`, and `tmux.sha256` are all present and the
canonical runtime verifier succeeds. The current fingerprint is written only after
that verification. Existing but invalid/incomplete outputs are never adopted.
