# Devtool cumulative improvements append — Chrootctl API26 build

Keep previous Devtool improvements ledger intact; **this is an append payload**, not a claim to have altered Devtool's repository.

| ID | Observed issue | Affected code/products | Suggested remedy | Status |
|---|---|---|---|---|
| CC-DT-01 | Existing root-module Devtool DAG not directly usable on hosted Ubuntu; adoption doctor: 1 eligible, 10 blocked | Devtool Actions exporter; Chrootctl `.devtool.toml` | Target-local host-portable release DAG using isolated dual-variant producer | OPEN |
| CC-DT-02 | Two direct GitHub workflows duplicate native runtime builds and bypass complete Devtool DAG | Chrootctl Actions; Devtool release orchestration | Single Devtool DAG as authoritative release coordinator | OPEN |
| CC-DT-03 | Chrootctl source-build rclone previously resolved latest; Standard could accidentally inherit ambient binary | Chrootctl repoctl/source restore | Reviewed pinned API26 commit and enforced edition-positive/negative inventories | SOURCE IMPLEMENTED, host build unverified |
| CC-DT-04 | Exact source/Devtool SHA required through final ZIP and build receipts, beyond marker timestamps | Chrootctl module evidence + Devtool | Versioned host receipts, output+source+toolchain+edition digests, signed/hashed artifact proof | OPEN |
| CC-DT-05 | Current Actions source gates use literal YAML string assumptions | Chrootctl `devtoolgates` + Devtool | Semantic workflow exporter/CI obligations validation with negative cases | OPEN |
| CC-DT-06 | Inability to execute all Chrootctl Go tests in isolated audit image | Local offline Go dependency cache | Preserve truth status; run complete Go tests through hosted immutable dependency setup | OPEN |

## CC-04 addition — package source/installed runtime safety (append-only)

| ID | Finding and evidence | Recommendation/implementation | Status |
|---|---|---|---|
| CC-DT-07 | The old live update checked executable presence, not per-file SHA, and could report a hot update across variant transitions while old binaries might remain live. | Source-bound `runtime-sha256.list`, offline ZIP and installed validators, installer checksum+edition gates, cross-edition reboot-only stage, verified same-edition rollback. | SOURCE IMPLEMENTED; Android root-manager/device acceptance OPEN |
| CC-DT-08 | Root-module seal schema-v4 had optional Git source fields left unset; no exact Devtool SHA/source lock recorded in released edition manifests. | Hosted `build-editions` requires clean/pinned Chrootctl and Devtool Git identities; v2 edition descriptor captures both Git SHAs, tree, bclone lock SHA and Go compiler version. Next hosted DAG must record authoritative job IDs and enforce source binding independently. | SOURCE IMPLEMENTED for hosted dual-edition descriptor; Devtool receipt integration OPEN |
| CC-DT-09 | Local audit lacks cached CGO/crypto deps so full `repoctl` suite cannot run offline. | Hosted DAG installs reviewed pinned dependencies and runs full suite; retain local shell/module/R1 success distinctly from native/device gates. | OPEN (environment), not a source failure |
