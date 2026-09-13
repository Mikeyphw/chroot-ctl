# Android behavior ownership map

The Android audit found that `ChrootsScreen.kt`, `MainViewModel.kt`, and `BridgeRepository.kt` together exceed 4,300 production lines and each contains multiple independent workflows. File-level labels are therefore not accepted as coverage. This map is the canonical behavior decomposition used by the CHR01–CHR20 roadmap.

`docs/android/behavior-ownership.json` is the machine-readable companion and is checked by `repoctl validate` through the CHR01 build-foundation contract.

## `ui/chroots/ChrootsScreen.kt`

| Behavior | Primary closure overlay | Expected evidence |
|---|---|---|
| Chroot list/search/filter and selected-workspace projection | CHR19 | state/unit tests plus UI behavior checks |
| Start/stop/restart/remove/rename/upgrade entry points | CHR07 | destructive-action and atomicity regressions |
| Snapshot room and restore review | CHR09 | metadata/restore and UI contract tests |
| Storage/logs workspace | CHR19 | authority/scope and stale-state tests |
| Users workspace | CHR12 | identity/sudo safety tests |
| Services workspace | CHR08 | lifecycle/log/status tests |
| Capability/degraded-backend presentation | CHR17 | protocol/capability fixture tests |
| Adaptive navigation, semantics and large-font behavior | CHR20 | accessibility/device/adaptive release tests |

## `ui/MainViewModel.kt`

| Behavior | Primary closure overlay | Expected evidence |
|---|---|---|
| Home refresh orchestration | CHR01 | direct `HomeRefreshCoordinatorTest` success/failure tests |
| Selection, stale response rejection and domain refresh | CHR19 | coroutine/state race regressions |
| Operation detail/reconcile/cancel/retry | CHR18 | operation/Room/recovery tests |
| Install draft/form/preview/start | CHR11 | installer state-machine tests |
| Snapshot/storage/logs | CHR09 / CHR19 | domain-specific tests |
| Users | CHR12 | preview/mutation/identity tests |
| Services | CHR08 | service state and mutation tests |
| Catalog/packages | CHR13 | compatibility/preflight tests |
| Transfer/artifact workflows | CHR10 | validation/TTL/publication tests |
| Support/readiness/evidence | CHR16 | truth/redaction/bundle tests |
| Debug/repair/smoke | CHR19 | typed capability and failure-state tests |

## `repository/BridgeRepository.kt`

| Behavior | Primary closure overlay | Expected evidence |
|---|---|---|
| Root transport → Home snapshot transaction | CHR01 | direct transport/store orchestration tests |
| Chroot/detail/check projection | CHR19 | bridge fixture and stale-state tests |
| Operation journal projection/reconciliation | CHR18 | Room migration/DAO/recovery tests |
| Install/upgrade bridge calls | CHR11 | typed schema/operation tests |
| Snapshot operations | CHR09 | round-trip and recovery tests |
| Users/services/catalog | CHR12 / CHR08 / CHR13 | domain fixture tests |
| Transfer/artifact descriptors | CHR10 | descriptor, bounds and publication tests |
| Support/debug/smoke | CHR16 / CHR19 | evidence/error propagation tests |
| Protocol envelope/capability handling | CHR17 | generated cross-language fixtures |

## Rules

1. A future finding against one of these files must name the behavior row it affects; “the file is covered” is not sufficient.
2. Production extraction is preferred when it creates a deterministic unit-test seam. CHR01 applies this to Home refresh with `BridgeTransport`, `HomeSnapshotStore`, and `HomeRefreshCoordinator`.
3. Cross-cutting refactors must preserve the owning overlay and its regression evidence rather than deleting a row because code moved files.
4. The final CHR20 seal must leave every behavior row with executable evidence appropriate to that domain; source scans alone are not release proof.
