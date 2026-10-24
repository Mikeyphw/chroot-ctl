# CC16 — Hosted source-test parity hotfix (GitHub Actions 40131873604)

**Authoritative failure:** https://github.com/Mikeyphw/chroot-ctl/actions/runs/40131873604 (source commit `32c217fe15fa6f3a581147a0f081d9634896fdfa`). The full 19-node hosted DAG reached 15 PASS, 1 FAIL (`release.test-source`) and 3 SKIPPED. Native API 26 tmux and bclone, Go tests (including OpenPGP), lint, Skybind consumer and edition-upgrade suite all passed. No release artifact was published.

## Two independent source-test defects and safe remediation

**CC16-01 — Mis-targeted Android Actions negative fixture.** `cmd/devtoolgates/main_test.go:TestNativeSourceGatesRejectTampering` mutated `setup-android@v4` in `.github/workflows/ci.yml` and required it to be present. Under the consolidated pipeline, `ci.yml` is intentionally source-only; the exact SDK/NDK step has moved to `.github/workflows/devtool-chrootctl-build.yml`. The failing assertion was stale. Fix: target the hosted release workflow in the negative fixture. `actionsChecks()` already checks the hosted workflow, so the test still proves a downgrade from v4 to v3 is rejected. Do not weaken production source checks, introduce duplicate CI builds, or silently skip this test.

**CC16-02 — Dedicated reconciler test leaked into package discovery.** `scripts/ci/reconcile-qualification.go` carries `//go:build ignore` because it is a standalone `go run` command, but `scripts/ci/reconcile-qualification_test.go` did not. Consequently `go test ./...` discovers the `_test.go` file without its `reconcile()` implementation and fails to compile (`undefined: reconcile` at five assertions). Fix: apply the same `//go:build ignore` directive to the companion `_test.go`. It remains fully exercised by the existing Devtool `release.test-verifier` command `go test -count=1 scripts/ci/reconcile-qualification.go scripts/ci/reconcile-qualification_test.go` (explicit file-mode Go tests honor the specified files regardless of the ignore tag). Do not delete the test or alter reconciler security semantics.

## Proofs and status
- Before patch both defects reproduced via `GOPROXY=off go test -count=1 ./cmd/devtoolgates ./scripts/ci`.
- After patch `go test ./cmd/devtoolgates` passes; package-wide discovery no longer includes the intentionally excluded standalone `scripts/ci` test, while the explicit `go test -count=1 scripts/ci/reconcile-qualification.go scripts/ci/reconcile-qualification_test.go` passes. Additional source-gate tamper regression tests pass.
- Source-bound to the exact GitHub commit above and SHA-256 of both original files; use Devtool's transactional apply.
- Full `go test ./...` and native Android GitHub build must still run on the hosted runner. Source-only proof must not be represented as completed release acceptance.
- Next hosted run must prove `test-source` PASS and then proceed through `build-editions`, `verify-editions`, `receipt`, independent Devtool machine receipt finalization, and upload of both ZIPs.
- Device/installed Skybind and reboot qualification remain separate/open.
