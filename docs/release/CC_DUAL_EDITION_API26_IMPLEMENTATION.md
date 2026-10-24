# Chrootctl CC-00 through CC-03 — dual-edition foundations / Android API 26

Date: 2026-10-24. **Status: SOURCE DELIVERY CANDIDATE; NOT A HOSTED RELEASE OR DEVICE QUALIFICATION.**

## Exact overlay base

Chrootctl source Git commit: `740d61457b096a7cf63d5c07e296f3f609820b03` from the October 24 snapshot. Overlay inventory also pins each pre-existing touched file SHA-256. Devtool snapshot under review: `445044ac4941c1542754cc19d74ebd785b5d8595`; no Devtool source was modified in this batch. The BKX lock was used as the reviewed **source identity reference**; this build still needs independent Android API 26 qualification.

## Delivered source changes

- Explicit edition identity `standard` or `rclone` in Chrootctl runtime manifest, Android API 26 value and generated `config/chrootctl/build-variant.json` (bound to exact runtime manifest SHA-256 and existing sealed module package inventory).
- `repoctl build-runtime --edition standard|rclone` and `repoctl build-module --edition standard|rclone`. Existing unqualified local/development `build-runtime` without an edition preserves compatibility; **do not use that implicit mode for CI releases**.
- `repoctl build-editions --rclone /absolute/rclone --output-root out/dual-release`: validates pinned rclone input, requires explicit tmux, builds a Standard base **once**, constructs separate Standard/Rclone runtime trees from only recorded base files, atomically publishes two independently validated module ZIPs as a pair, and verifies the Chrootctl executable is byte-identical between editions.
- Standard release paths never probe ambient `rclone` in PATH or old out/ directories. Rclone release paths require an explicitly supplied executable, Android/ARM64/CGO Go buildinfo, 16 KiB PT_LOAD ELF alignment, and a local SHA-bound `rclone-build-receipt.json` matching the reviewed source lock.
- `scripts/install-rclone-android-runtime.sh`: no mutable latest-release resolution; fetch a reviewed bclone tag through Git, verify the peeled commit against a full SHA in `config/chrootctl/bclone-android-source.lock`, archive that exact checked-out commit, require reviewed `go1.27.2`, and bind the resulting executable SHA to its receipt.
- API 26 for static tmux build/verifier and bclone source builder. The hosted Chrootctl release compiler target must be named `aarch64-linux-android26-clang`; old `CHROOTCTL_ANDROID_API=24` and tmux `CHROOTCTL_TMUX_ANDROID_API=24` overrides fail. Keep Bionic `glob` pre-28 and `reallocarray` pre-29 compatibility; the pre-26 `nl_langinfo` branch is inactive at the release floor.
- ZIP validation now binds the edition descriptor to the runtime manifest and checks each contained runtime entry's hash and execution mode against the edition-aware runtime manifest. Module ID/version/API-facing WebUI and Skybind R1 source paths remain unchanged.

## Suggested command for the *future hosted build*, after provisioning the reviewed Go compiler, NDK r29, static tmux and downloading pinned source

```bash
# All commands from the Chrootctl repository root.
# The installer requires the exact compiler named in the checked-in source lock.
scripts/install-rclone-android-runtime.sh out/rclone "$ANDROID_NDK_ROOT"
CHROOTCTL_TMUX_PATH="$PWD/out/tmux/arm64-v8a/tmux" \
  go run ./cmd/repoctl build-editions \
  --rclone "$PWD/out/rclone/arm64-v8a/rclone" \
  --output-root out/dual-release
# Intended outputs:
# out/dual-release/chrootctl-standard-arm64.zip
# out/dual-release/chrootctl-rclone-arm64.zip
```

The command above is **not** a claim it was run. GitHub Actions still uses the old direct `repoctl` workflow and must be migrated during CC-05–CC-07.

## Promise status and remaining gates

| Phase | Promise | Status/evidence |
|---|---|---|
| CC-00 | Exact input source commit and file SHA binding | DELIVERED for overlay preflight; full original CI obligations ledger remains OPEN |
| CC-00 | Full original DAG evidence inventory / source-tree + Devtool SHA inside released output | OPEN — CC-04/CC-05 work |
| CC-01 | Explicit two editions, no ambient Standard rclone, binary required in Rclone | SOURCE DELIVERED; actual cross-build open |
| CC-01 | Single shared backend, isolated staging and two module ZIPs | SOURCE DELIVERED; native execution not tested |
| CC-01 | Exact base runtime byte identity and package edition manifests | SOURCE DELIVERED; full hosted evidence open |
| CC-02 | Chrootctl/CGO + tmux + bclone Android API 26 | SOURCE DELIVERED; compilation and API device proof OPEN |
| CC-02 | ELF/16 KiB and downgrade-negative checks | PARTIAL: static parser and negative flags; native linker/toolchain evidence OPEN |
| CC-03 | Immutable bclone Git SHA, Go/NDK/API lock and build SHA receipt | SOURCE DELIVERED; pinned upstream fetch/build not executed |
| CC-03 | Cache verification against immutable build inputs | PARTIAL: tag fetch SHA verified, cache SHA and Go/API/commit folder keys; independent archive lock/SBOM/repeat-build checks OPEN |
| Skybind R1 | Read-only integration unchanged for both source variants | SOURCE MAINTAINED; real installed caller/grant/revocation tests OPEN |
| Skybind R3/R4 | Native rclone-equivalent streaming/write | NOT QUALIFIED; not implemented by this overlay |

## Tests executed against this overlay candidate

- `GOPROXY=off go test ./internal/module ./internal/skybindr1 -count=1`: PASS.
- Isolated edition-source Go compile/negative checks with temporary stubs (removed afterwards): PASS; this is **not** a full `internal/repoctl` test run.
- `bash -n` on the rclone/tmux producer/verifier: PASS.
- Intentional API-24 tmux override: rejected before network access.
- Intentional mismatched local bclone compiler: rejected before source download (local compiler go1.23.2, checked lock go1.27.2).
- Full `internal/repoctl` tests: BLOCKED locally by missing cached Go dependencies and no Go proxy connectivity. No hosted/Android build executed.

## Next merge window (overlay B)

CC-04: strengthen package safety for Standard↔Rclone install/upgrade/downgrade, source/Devtool SHA-bound runtime/module seals, tamper/downgrade/upgrade fixture gates, and evidence for actual installed runtime identity. Then merge CC-05–07 hosted Devtool DAG and GitHub Actions publishing only after this package contract is stable.
