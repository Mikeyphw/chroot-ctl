# CC-11 — Hosted release readiness hotfix (post CC-10)

**Status:** source changes and offline negative tests; **not** evidence of a successful GitHub build or Android device acceptance.

## Repaired defects

1. `scripts/tmux/build-static-android-arm64.sh`: the first fingerprint `printf` argument was missing its trailing line continuation. Bash therefore tried to execute the remainder of the fingerprint literals as a command, aborting before native compile. The new test evaluates the **same production function** without downloading toolchains and proves deterministic values and sensitivity to hosted-lane and Android API changes.
2. `scripts/ci/hosted-release-stage.sh`: only ZIPs and qualification previously appeared in `SHA256SUMS`, leaving the release index, source/build context and Devtool receipts outside the checksum index. Source/DAG receipt now seals its three JSON files; a separate post-DAG finalizer re-verifies initial hashes and seals **all nine** shipped files including `devtool-plan.json` and `devtool-run.json`.
3. `scripts/ci/finalize-hosted-evidence.sh`: fail-closed on missing machine receipt, symlinks, unexpected/stale files and altered input hashes. This is an **integrity index, not a cryptographic attestation**. User still needs the GitHub trusted run and independently qualified on-device identity.

## Exact release acceptance sequence

- The tracked Chrootctl source and pinned Devtool source must be clean at the expected Git revisions.
- Run reviewed Devtool `ci-release` on Ubuntu. Local source checks and unit/negative tests run in its DAG.
- After the machine receipt is produced, add plan and run JSON to the evidence directory and invoke `scripts/ci/finalize-hosted-evidence.sh out/hosted-evidence`.
- Verify the GitHub run, download artifact, validate full `SHA256SUMS`, inspect source/Devtool identity and compare both ZIPs with actual installed module identity.
- Android and Skybind R1 actual-process tests are still **open**; R3/R4 full streaming/mutation is **not qualified**.

## Source-bound application caveat

This overlay targets the exact source from CC-08–CC-10 after all prior overlays. It does not install, mutate or rebuild any Android module.
