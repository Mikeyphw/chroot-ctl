# Append-only Devtool/Chrootctl improvement delta — CC-11

| ID | Finding | Evidence | Action | Status |
|---|---|---|---|---|
| DT-CC-11A | Hosted tmux source fingerprint contains shell line-continuation bug | `scripts/tmux/build-static-android-arm64.sh` previous `printf` | Fixed; added executable fingerprint/host/API negative test | SOURCE_FIXED; HOSTED_NATIVE_PENDING |
| DT-CC-11B | Incomplete release SHA256SUMS and post-DAG Devtool run receipt unchecked | previous `scripts/ci/hosted-release-stage.sh` / `.github/workflows/devtool-chrootctl-build.yml` | Full nine-file strict finalizer; corrupt/missing/stale/symlink rejection | SOURCE_FIXED; HOSTED_ARTIFACT_PENDING |
| DT-CC-11C | Devtool machine JSON only created after last DAG node; in-DAG receipt cannot hash it | Devtool `--machine-file` interface | Keep stage receipt distinct from post-DAG finalization. Consider first-class final output/attestation post-hook | DESIGN_BACKLOG |
| DT-CC-11D | GitHub main branch still has original pre-overlay workflow at `740d61457b096a7cf63d5c07e296f3f609820b03` at the time of audit | GitHub connector repository file search | Push local applied overlays and then evaluate real hosted run; don't assert GitHub qualification prematurely | OPEN_EXTERNAL |
