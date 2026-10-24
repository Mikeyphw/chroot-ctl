# CC-00–CC-11 promise-by-promise source audit and CC-12 hotfix

**Audited snapshot:** `chroot-ctl-20261024-141221-344834.tar.gz`, HEAD `a2c3b8a040041500360aa58e2fb7d91bac77c017` (CC-11 applied). **Review date:** 2026-10-24. **Status:** partial source delivery; **neither GitHub native builds nor installed devices are qualified**.

## Method and evidence
- Inspected source code, packaging, rendered install logic, GitHub workflow, Devtool job graph, source locks, actual Devtool machine schema and negative tests, not just documented claims.
- Ran `GOPROXY=off go test -count=1 ./internal/module ./internal/skybindr1`; two independent release/reconciliation Go script test suites; CC-11 tmux fingerprint and evidence test; Actions and R1 source gates; `bash -n`. All focused tests passed.
- Planned the actual 19-node hosted release using the supplied Devtool snapshot; plan success, 19 local jobs, 0 repository jobs. Independently executed Devtool's `invoke` against a one-job host fixture to establish authentic v2 node state, run result and envelope schema.
- Attempted `GOPROXY=off go test ./internal/repoctl -count=1`; could **not** run because `github.com/mattn/go-sqlite3` and `github.com/ProtonMail/go-crypto` were not cached; offline Go module lookup was disabled. No conclusion about pass/fail.
- No GitHub Actions build was run from this local snapshot; no actual NDK/tmux/bclone build; no Android or Skybind installed-process acceptance. Do not assert complete release qualification.

## Promise audit
| ID | Actual promise | Result | Source evidence and remaining gate |
|---|---|---|---|
| CC-00 | Exact source-bound overlays and original obligations | DELIVERED for source identity; PARTIAL overall | Snapshot has sequential applied Git commits, locks, source gates. Original full CI/Android acceptance remains open. |
| CC-01 | Two explicit editions, no ambient rclone in Standard, mandatory embedded source in Rclone | SOURCE DELIVERED | `internal/repoctl/editions.go`, `BuildRuntime`, edition manifest/ZIP tests. Native production binaries unbuilt. |
| CC-02 | One shared Chrootctl/CGO+tmux base, two isolated packages, Android API 26 | SOURCE DELIVERED; HOSTED UNQUALIFIED | `BuildEditions`, stage/pair publication, pinned Go/NDK and tmux API gate. Requires actual NDK+ELF/device acceptance. |
| CC-03 | Pinned bclone source build and 16 KiB runtime | SOURCE DELIVERED; PROVENANCE PARTIAL | `config/chrootctl/bclone-android-source.lock`, pinned tag-to-commit Git check, runtime receipt, ELF checks. No hosted fetch or two-build reproducibility proof; cached source archive uses locally generated sidecar, not independent pinned archive digest. |
| CC-04 | Runtime checksum inventory, edition-aware installer and safe live rollback | SOURCE DELIVERED; DEVICE OPEN | Module tests cover corruption, ZIP seals, staged switches, interrupted live failures. Root-manager boot and actual state retention are not proven by simulation. |
| CC-05 | Devtool authoritative hosted DAG, independent target local jobs | SOURCE DELIVERED; EXECUTION OPEN | `.devtool.toml` 19-node host graph, native-Termux graph preserved. GitHub execution not observed. |
| CC-06 | Single GitHub native build, two edition artifacts | SOURCE DELIVERED; HOSTED OPEN | `.github/workflows/devtool-chrootctl-build.yml` vs source-only `ci.yml`. Two ZIP filenames in build/validator. Need successful actual workflow and downloaded artifacts. |
| CC-07 | Exact Devtool version, dependency/toolchain caching and release receipts | PARTIAL | Exact commits, Go/NDK lock, 9-file SHA finalizer exist. **CC-12 fixes incomplete semantic machine-receipt validation and incomplete independent ZIP member verification.** Signed GitHub provenance remains opt-in and unproven. |
| CC-08 | Both editions retain scoped, approved Skybind R1 reads | SOURCE DELIVERED; REAL-PROCESS OPEN | `internal/skybindr1` R1 and mock denial/cancellation tests pass. Real UID/SELinux-approved grant from Chrootctl module untested. R3/R4 streaming/mutation intentionally unavailable. |
| CC-09 | Cross-edition reboot activation, rollback, preservation and installed snapshot | SOURCE TESTS DELIVERED; DEVICE OPEN | `internal/module/cc09_*`, device snapshot shell probe. No physical KernelSU/Magisk edition transition, power-loss/reboot or real source-to-installed byte evidence. |
| CC-10 | Reconcile hosted and installed evidence without claiming false device PASS | SOURCE DELIVERED; FINAL RELEASE OPEN | `reconcile-qualification.go` tests reject fake fixture/incorrect identities; always NOT_DEVICE_QUALIFIED. Actual production authority evidence missing. |
| CC-11 | Tmux fingerprint fix and complete SHA256SUMS finalizer | SOURCE DELIVERED; ADDITIONAL GAP FOUND | Fingerprint and checksum tests pass; pre-hotfix finalizer accepted arbitrary nonempty `devtool-run.json` including `{}` or waiting jobs. |

## Concrete defects reproduced and repaired by CC-12

1. **P1 – Incomplete independent ZIP verification.** `scripts/ci/verify-dual-release.go` checked runtime entries and three selected files but never compared the ZIP's entire member set with the staged module tree. A missing/tampered unrelated WebUI or configuration file, extra ZIP member, staged-only unshipped file or permission drift could still be accepted after recalculating the ZIP sidecar. CC-12 requires one-to-one, regular-file-only, canonical-path, SHA-256, size and mode equivalence for **every** member and staged file. Regression tests include all five negative cases.
2. **P1 – Devtool machine receipt could be a placeholder or incomplete result.** The previous finalizer required `devtool-run.json` to exist and be nonempty; it did not parse `ok`, `exit_code`, workflow nodes, failure/skipped states or the plan. CC-12 checks the pinned Devtool schema: planned `ci-release` target and 19 target-local jobs; actual `invoke` for the same target; exactly all expected nodes `passed` with nonempty results, zero failed/error/skipped and matching repository identity. The gate executes **before** final `SHA256SUMS` replacement and returns nonzero on any discrepancy. Go negative tests prove this.
3. **Audit transparency:** Existing checks are real source-level tests; labels claiming comprehensive tested Android or published release would be unsupported. Hosted/device gates remain explicitly open.

## Known remaining / deferred follow-up work
- **P0 release:** push exact source, execute GitHub Actions with NDK/Go/toolchain checks, verify external repository access to Devtool and bclone, download both ZIPs, independently inspect `SHA256SUMS`, run source-byte/ELF and attestation checks. Resolve real build failures rather than marking pending as PASS.
- **P0 device:** install each ZIP, inspect active runtime after reboot, verify both transitions/rollback, real state retention, native rclone disposable import/export, and actual Skybind read-only scope/grant/revocation from Chrootctl module service context.
- **P1 reproducibility:** strengthen bclone cached archive identity against an independently recorded content hash or Git tree revalidation; qualify clean repeat builds. Do not claim bit-for-bit reproducibility solely from source pin + checksum.
- **P1 Devtool:** expose a reusable typed producer→dual-consumer artifact/receipt validator in Devtool instead of ad hoc project scripts; move this finding into Devtool's cumulative improvements ledger when Devtool source is updated.
- **P1 full tests:** rerun the complete Chrootctl Go test/vet and UI/native tooling in a network-enabled pinned CI environment.
- **Skybind R3/R4:** no substitution for native rclone without exact streaming, immutable publication and scoped cleanup/provider conformance. Remains blocked by independent upstream API capability.

**CC-12 is a source-only hotfix.** Passing its validation does not close any hosted or on-device gate.

### Devtool transaction replay observation
An isolated replay lacking a Git committer identity passed preflight and all validators but failed at commit. The tool reported successful rollback while leaving source modifications in its sandbox working tree. A follow-up clean replay with a configured local committer is required before delivery; this is logged as DT-CC-13 and does not implicate the user's Termux repository.
