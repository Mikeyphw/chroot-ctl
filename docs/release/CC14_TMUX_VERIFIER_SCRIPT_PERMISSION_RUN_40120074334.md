# CC14: GitHub run 40120074334 — Bash call-site hardening

**Base commit:** `44e3c594b50bb1d7f4e41f8ae6eb9c984b5d4edf` (CC13). **Scope:** reproducible source hotfix only. **Release state:** unqualified until a fresh GitHub-hosted and actual device run passes.

## Actual observed failure

`https://github.com/Mikeyphw/chroot-ctl/actions/runs/40120074334`, job `dual-release`, job ID `120949501319`, passed five of the nineteen hosted Devtool DAG nodes, failed one (`verify-tmux`), skipped thirteen. `scripts/ci/hosted-release-stage.sh: line 54: scripts/tmux/verify-static-android-arm64.sh: Permission denied` (exit 126). Release candidates were not uploaded.

CC13's toolchain preflight passed; native tmux compilation ran for ~2m50s. The failure was attempting to directly execute a tracked non-executable Bash script rather than evaluating its content. `scripts/tmux/verify-static-android-arm64.sh` is tracked with mode `100644`. So is the subsequent `scripts/install-rclone-android-runtime.sh`, which would have failed similarly in the next build stage. These are call-site errors, **not proof of an invalid compiled tmux artifact or wrong NDK revision**.

## Fix

- `scripts/ci/hosted-release-stage.sh`: explicitly invoke both tracked non-executable scripts with `bash`; keep original verified arguments and API 26 source-lock enforcement.
- `scripts/devtool/root-module-stage.sh`: invoke tmux verifier with `bash` in native `build-tmux-verify` and `package-runtime`, preventing equivalent failures in the Termux and package-checking paths.
- `scripts/ci/test-hosted-script-invocation.sh`: executable source regression with a fixture whose verifier and rclone builder have mode `0644`. It first proves direct execution is denied, then proves both hosted stages and the native Devtool tmux-verifier stage work through `bash`; it also supplies a fixture NDK API 26 compiler/lock and denies ambient NDK selection.
- Hosted `test-verifier` stage runs the new regression test. No script is made executable as a workaround; no NDK lock is weakened; no opaque binary changes.

## Evidence and acceptance

Local source/negative checks: source gates (`go run ./cmd/devtoolgates actions` and `r1`); Go module and Skybind R1 tests; dual-release verifier and Devtool receipt tests; CC11–13 regression tests, tmux fingerprint and the new 0644-script fixture all pass. A full actual Android toolchain run is not available in this container. Only a fresh GitHub `ci-release` run can qualify the `verify-tmux` and later rclone/Go package stages. The final 19-node receipt and both separate edition packages are still required, followed by physical-device Skybind and upgrade tests.

## Deliberate limits

No changes to Chrootctl's runtime ABI, edition identity, Skybind scopes, NDK revision, API 26 target, rclone source pin, or release evidence gate. A successful Bash invocation is **not** proof that the verifier validates the resulting binary; that independent check still runs unmodified in GitHub Actions.
