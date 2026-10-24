# CC-05–CC-07 — Hosted Devtool DAG, dual-edition GitHub Actions, API 26

**Status:** Source implementation delivered; only source-level tests and Devtool workflow planning have been executed locally. **NOT** a completed GitHub-hosted native build, installed-module qualification, or R3/R4 Skybind conformance.

## Scope and authority

- Keep `[targets.chrootctl_root_module]` and existing native-Termux jobs untouched.
- Add `[targets.chrootctl_hosted_release]` with **17 named target-local command jobs**, all in host/Linux execution environment. DAG `ci-release` runs preflight, Go dependencies, static tmux restore/build/verification, locked bclone runtime, `repoctl` producer, Go/WebUI/tmux tests, Go/native lint, source contracts, one `repoctl build-editions` shared Go/CGO runtime producer, independent two-edition verification, and final receipts.
- GitHub Actions `.github/workflows/devtool-chrootctl-build.yml` is the **only native Android build workflow**; `.github/workflows/ci.yml` stays source-contract-only. Remove duplicate heavyweight native `repoctl` builds from CI.
- Chrootctl Go/CGO runtime, tmux and bclone remain exactly **API 26**. The hosted tmux compiler path (`CHROOTCTL_TMUX_HOSTED_NDK=1`) explicitly uses the pinned NDK API-26 toolchain rather than host glibc or Termux-private builtins/unwind. Native-Termux compile lane is retained.
- Devtool is checked out at the exact reviewed SHA `445044ac4941c1542754cc19d74ebd785b5d8595` into `RUNNER_TEMP` before execution, and verified against `config/chrootctl/devtool-hosted-source.lock`. For a private Devtool repository, the workflow needs the user-created GitHub Actions secret `DEVTOOL_READ_TOKEN` with read-only contents permission; `github.token` cannot read other private repositories.
- Reviewed bclone source/toolchain remains locked at `config/chrootctl/bclone-android-source.lock`; required Go compiler `go1.27.2`, Android NDK `29.0.14206865`, 16 KiB. Cache only inputs compiled from pinned sources and verify files before reuse.
- `repoctl build-editions` compiles base Go/CGO Chrootctl once and builds two alternative Magisk/KSU ZIPs: `chrootctl-standard-arm64.zip` (forbid embedded rclone) and `chrootctl-rclone-arm64.zip` (pinned binary). They retain module ID, WebUI, bridge, runtime and read-only Skybind R1 contract.
- `scripts/ci/verify-dual-release.go` (Go-only to meet repository's Python-purity invariant) independently checks both ZIP sidecars, safe/unique ZIP member paths, ZIP/expanded/module/runtime byte equivalence, API 26, edition descriptor and exact Chrootctl/Devtool source identity, base backend identity and rclone inclusion/exclusion. `verify-dual-release_test.go` includes real ZIP fixture and negative tamper cases.
- CI artifacts contain two zip files, two `.sha256` sidecars, `SHA256SUMS`, `release-evidence.json`, `build-context.json`, Devtool execution plan and Devtool machine receipt; on GitHub runners the `GITHUB_RUN_ID` links them to the workflow run. The receipt schema labels them **HOSTED_CANDIDATE_NOT_DEVICE_QUALIFIED**.
- `actions/attest@v4` is opt-in via repository variable `CHROOTCTL_ATTEST_RELEASE_CANDIDATES=true`; it requires applicable repository permissions/plan eligibility. Do not confuse SHA-256 checksum files and Devtool machine receipts with independent signed provenance.

## Commands for hosted release

On GitHub Actions, the job checks out both exact source revisions and invokes:

```sh
"$RUNNER_TEMP/devtool-venv/bin/python" -m devtool --repo "$GITHUB_WORKSPACE" \
  --machine-file "$RUNNER_TEMP/chrootctl-devtool-run.json" \
  invoke ci-release --target chrootctl_hosted_release --workflow-max-workers 2
```

Stage shell script `scripts/ci/hosted-release-stage.sh` exposes deterministic stage names and forbids unrecognized actions. The native module installer is not reachable from the CI target.

## Open gates

1. Full `go test ./...`, `go vet ./...` and Devtool DAG end-to-end on GitHub Actions. Local Go test dependencies (notably `github.com/mattn/go-sqlite3` and `github.com/ProtonMail/go-crypto`) are missing and offline. These tests were **not falsely marked PASS**.
2. Confirm pinned `Mikeyphw/devtool` SHA is available with the token used by this repository; private cross-repo checkout may require `DEVTOOL_READ_TOKEN`.
3. Validate NDK-hosted static tmux link path and bclone source compilation on actual `ubuntu-24.04`; no Android NDK is installed in the source-audit runner.
4. GitHub archive and attestation retrieval, independent digest verification, exact installed root module evidence and both edition switch/reboot tests.
5. Both editions' actual privileged Skybind R1 read-only caller test; later full `cat`/`rcat`/`moveto --immutable`/scoped cleanup stay separately gated by Skybind R3/R4.

## Local evidence

- Devtool `plan ci-release --target chrootctl_hosted_release --json`: **17 nodes**, **17 target-local jobs**, DAG plan PASS (no jobs executed).
- `go run ./cmd/devtoolgates actions` and `r1`: PASS source contracts.
- `go test ./internal/module ./internal/skybindr1`: PASS.
- `go test scripts/ci/verify-dual-release.go scripts/ci/verify-dual-release_test.go`: PASS positive fixture and negative tests.
- `bash -n` hosted/tmux stage scripts: PASS.
- Full repoctl Go test: BLOCKED by Go dependencies in disconnected source-audit environment.

**Next:** CC-08–CC-10 device, Skybind consumer, edition migration/rollback and cross-source release gates. Do not claim these from source checks or GitHub-hosted build status alone.
