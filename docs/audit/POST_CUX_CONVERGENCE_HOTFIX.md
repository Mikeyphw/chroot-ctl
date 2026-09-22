# Post-CUX convergence hotfix

This hotfix closes defects found after the CUX-07 release seal by comparing live module behavior with the final roadmap promises and by probing the installed backend directly.

## Confirmed defects

- Activated module health incorrectly reused the strict rendered-tree validator. Root managers may consume installer-only files such as `customize.sh`, so a healthy active module was reported as `module_missing`, `active=false`, and `packageSealReady=false`.
- Runtime release readiness still consumed the legacy schema-v3 final-seal evidence model, including retired Android-companion checks and an unconditional localization `pending` row. The current root-module product could therefore never become Ready after a successful Devtool gate.
- The authoritative `chrootctl_root_module` Devtool lifecycle did not publish evidence to the running module.
- Diagnostics launched four privileged KernelSU query RPCs concurrently and treated any one parsing/transport failure as a failure of the entire Diagnostics surface. Direct probes showed all four backend operations returned valid protocol-v1 JSON individually.
- KernelSU executable discovery was repeated for every request instead of reusing the executable that passed the typed bridge self-test.
- Home route hierarchy/scroll restoration, Terminal unavailable-state gating, Rclone action wording, smoke cancellation visibility, and technical-error presentation did not fully match the CUX roadmap.
- A retired hidden Debug & readiness workspace still duplicated System → Diagnostics.

## Converged behavior

- `ValidateInstalled` checks the persistent activated-module surface and package/runtime seals without requiring consumed installer-only files. `ValidateRendered` remains strict for build/package validation.
- Root-module validation uses schema-v4 checks: `root_restore`, `root_build`, `root_test`, `root_lint`, and `root_package`. The package stage embeds the evidence into the module package seal and `post-fs-data.sh` atomically publishes the exact sealed bytes to `/data/adb/chrootctl/validation-results.json` with mode `0600`.
- Runtime readiness independently verifies the active installed-module seal and native runtime in addition to build evidence. Retired Android-companion evidence IDs do not participate.
- Legacy `repoctl final-seal` evidence remains repository-local so it cannot overwrite authoritative runtime evidence.
- KernelSU typed query RPCs are serialized, the executable that passes the typed `app capabilities` self-test is pinned, and bridge parse errors retain operation/backend/stdout/stderr details for expandable technical diagnostics.
- Diagnostics uses independent settled results so a failure in one card does not blank the others. The duplicate hidden readiness workspace is removed.
- Home places route hierarchy before dashboard content and resets route scroll; unavailable Home metrics are explicit. Terminal exits `Checking` on failure and disables create/reconnect until runtime readiness is authoritative. Rclone uses `View Rclone status` when unavailable. Smoke cancellation is hidden until an operation exists.

## Validation

Local artifact preparation performs five audit passes: scope convergence; installed-module/evidence truth; WebUI/bridge transport and DOM integrity; Devtool lifecycle/package semantics; and source-guarded artifact reconstruction/integrity. The full `chrootctl_root_module` Devtool validation remains required on the target host because this artifact sandbox cannot fetch the uncached `github.com/mattn/go-sqlite3` dependency used by the wider repoctl/services graph.

## Promise-delivery re-audit (v2)

A second promise-by-promise audit used the supplied offline `go-sqlite3` source to execute the real root-module Go package graph rather than the earlier compile-only SQLite stub. It found and closed three gaps in v1 before publication:

1. `TestCUX07FinalRoadmapGate` still required the retired `readiness-panel`, so v1 would have failed the authoritative root-module test gate despite intentionally removing that duplicate surface. The final gate now requires the single System → Diagnostics surface, rejects a resurrected readiness panel, and verifies the legacy route redirect.
2. The bridge capability schema for `release.readiness` still advertised the retired `summary` field instead of the schema-v4 evidence/readiness contract. The response schema now advertises evidence identity/problem, validation identity, check counters, checks, and final readiness.
3. Standalone HTTP and capability-gate failures could lose the exact operation/backend/raw-response provenance promised for technical details. Typed request errors are now annotated at the request boundary; malformed standalone JSON preserves a bounded raw response and identifies `standalone-http` plus the exact operation.

The post-fix root-module test surface passes with the supplied SQLite dependency, including the KernelSU serialization test, a new standalone malformed-JSON provenance test, the corrected CUX-07 final gate, and the release-readiness response-schema contract. `go vet` also passes across the authoritative root-module package set. A repository-wide `go test ./...` additionally exposed one unrelated pre-existing `internal/completion` command-count failure (`nodes=92`), which reproduces unchanged on the post-permission baseline and is therefore outside this convergence overlay.
