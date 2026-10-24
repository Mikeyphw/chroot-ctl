# CC-04 — Chrootctl package safety / edition transition

**Source delivery:** CC-04 (after source-bound CC-00–CC-03 Overlay A). 2026-10-24. **Status:** implemented source and local qualification; not yet a GitHub-native or Android-device-qualified release.

## Promises implemented

1. **Typed release provenance:** dual-edition `repoctl build-editions` requires clean Git Chrootctl and separately selected Devtool checkouts. `CHROOTCTL_EXPECTED_SOURCE_SHA` must equal Chrootctl HEAD; `CHROOTCTL_EXPECTED_DEVTOOL_SHA` must equal the clean Devtool HEAD in `CHROOTCTL_DEVTOOL_ROOT`. Release Go compiler must equal the `go_version` in the reviewed `config/chrootctl/bclone-android-source.lock`; API must be 26. A v2 `build-variant.json` seals the Chrootctl commit+tree, Devtool commit, source lock SHA-256, runtime manifest SHA, Go compiler version, edition and API. The whole descriptor is sealed into the module package manifest. Local, non-release single-edition rendering remains compatible with schema v1.
2. **Runtime checksum contract:** every rendered module includes `config/chrootctl/runtime-sha256.list`, derived from the runtime manifest with flat safe paths. `ValidateRendered`, `ValidateZipArchive` and `ValidateInstalled` independently verify it. Installer verifies hashes and exact file inventory before active runtime replacement using Android-compatible sha256sum/toybox, plus descriptor/edition/API consistency, executable presence and no stray `rclone` in Standard. The installed Go verifier now checks the edition descriptor, fixing the old gap.
3. **Edition changes:** Standard↔Rclone are *staged for reboot*. No live swap mixes old running binaries with a different sealed edition. A Standard staging tree includes no rclone, and the installed root-module validator rejects extra runtime files. Old persistent `/data/adb/chrootctl` state is untouched. Root-manager boot-time replacement and removal of old rclone still need real installed-device verification in CC-09; source-level tests do **not** prove root-manager behavior.
4. **Same-edition hot updates:** prior active module checksum verification, complete staged sibling construction, checksum verification before and after rename, marker preservation, rollback to previous verified tree on partial rename/check failure. If the old tree is unverified, or abandoned `.chrootctl.live-{new,old}.*` siblings exist, do not attempt a second live transaction; leave the new package staged for root-manager reboot activation. Do not destroy unknown recovery trees.
5. **Honest status:** module live-file installation is distinguished from independent service health. Stage-only cross-edition switches explicitly require reboot. No automatic Skybind fallback or credential migration is introduced.

## Evidence

- `GOPROXY=off go test ./internal/module ./internal/skybindr1 -count=1`: PASS.
- `GOPROXY=off go vet ./internal/module ./internal/skybindr1`: PASS.
- Independent offline compile/typecheck harness for `internal/repoctl/editions.go`: PASS; temporary harness deleted afterward.
- Tests include clean staged installer, executable byte corruption, stray Standard rclone, checksum-list tamper, installed descriptor tamper/missing, v2 release provenance tamper after re-seal, re-sealed malicious ZIP SHA list, Standard→Rclone and Rclone→Standard staging, same-edition success, injected live-rename failure with old-tree restoration, corrupt previous active tree, and abandoned update siblings.
- Full `./internal/repoctl` regression suite: **BLOCKED** in local audit image (uncached `github.com/mattn/go-sqlite3` and `github.com/ProtonMail/go-crypto`, `GOPROXY=off`). This is not interpreted as source failure or success.
- Hosted API26 native builds, GitHub evidence, actual KernelSU/Magisk installer, reboot edition transitions and Skybind real-process conformance: **NOT RUN**; next phase/qualification obligations remain open.

## Hosted Release call after CC-05–07 supplies CI authority

```bash
export CHROOTCTL_EXPECTED_SOURCE_SHA="$(git rev-parse HEAD)"
export CHROOTCTL_DEVTOOL_ROOT="/path/to/pinned/devtool-checkout"
export CHROOTCTL_EXPECTED_DEVTOOL_SHA="$(git -C "$CHROOTCTL_DEVTOOL_ROOT" rev-parse HEAD)"
# Must also use Go compiler pinned by bclone source lock, an NDK API26 compiler,
# pinned static tmux and explicit built/receipt-bound rclone.
export CHROOTCTL_TMUX_PATH=/absolute/static-tmux
# go run ./cmd/repoctl build-editions --rclone /absolute/rclone --output-root out/dual-release
```

Do not derive expected SHAs from whatever happens to be on PATH in release Actions: the Devtool/Chrootctl CI checkout refs must be independently pinned and verified against the GitHub event/reviewed lock. These export examples are not a substitute for that CI authority.

## Remaining dependencies

- **CC-05–07:** hosted Linux Devtool DAG, exact checkout/toolchain binding, GitHub artifact verification, repeat-build/release receipts and full Go regressions.
- **CC-08:** independent installed Skybind R1 checks for both editions. Skybind R3/R4 is not claimed.
- **CC-09:** actual device root-manager staging/reboot and upgrade/rollback including stale rclone absence after activation and private state preservation.
- **CC-10:** full promise-by-promise behavior audit and source-bound CI/device evidence closure.
