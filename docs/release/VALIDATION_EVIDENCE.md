# Final validation evidence contract

Runtime release readiness is driven by the **root-module product gate**. The authoritative producer is the `chrootctl_root_module` Devtool lifecycle: restore → build → test → lint → package. The package stage converts the successful stage markers into `schemaVersion: 4` evidence, embeds that evidence into the sealed module at `config/chrootctl/validation-results.json`, rebuilds/verifies the module ZIP, and `post-fs-data.sh` publishes the exact sealed bytes to `/data/adb/chrootctl/validation-results.json` with mode `0600`.

Runtime readiness consumes `/data/adb/chrootctl/validation-results.json`, or the path named by `CHROOTCTL_VALIDATION_RESULTS`. The active installed module and bundled runtime are checked independently at runtime; a passing historical build is never enough when the installed module seal is broken.

## Schema v4 and identity

The evidence records:

- `validationRunId` and `generatedAt`;
- optional `sourceCommit` and `sourceTree` when a producer can bind evidence to an immutable Git identity;
- `compatibilityManifestSha256`, the SHA-256 of the exact compatibility manifest embedded in the module; and
- the exact root-module lifecycle `checks` object.

Installed runtimes are anchored by the compatibility-manifest SHA-256. When a Git checkout is available and evidence contains Git identities, runtime readiness additionally verifies those identities and requires a clean source worktree.

## Required checks

The exact schema-v4 build check IDs are:

- `root_restore`
- `root_build`
- `root_test`
- `root_lint`
- `root_package`

A passing check carries `status: pass`, `exitCode: 0`, a non-empty `command`, a positive `recordedAt`, and provenance of `devtool-stage`, `subprocess`, or `internal-check`. Missing, extra, malformed, or failed build checks make the evidence fail closed.

Runtime readiness then appends two live checks that are **not caller-authored evidence**:

- `installed_module` — the activated persistent module payload matches the package seal; and
- `native_runtime` — the bundled native runtime is active, executable, and passes its runtime manifest seal.

The old Android-companion evidence IDs (`android_compileDebugKotlin`, `android_testDebugUnitTest`, `android_lint_configuration_seal`, and the synthetic `android_localization_rtl` pending row) are retired from runtime readiness. They cannot make the root-module product Ready or block it forever.

## Producer and persistence safety

Use the normal Devtool target validation:

```sh
devtool -r "$HOME/Code/chroot-ctl" --target chrootctl_root_module validate
```

The package stage requires markers from restore, build, test, and lint before it can publish `root_package`. Evidence is written into the package with mode `0600`, included in the package manifest, and the ZIP checksum is regenerated after evidence sealing. The active module publishes the same sealed bytes atomically to the state directory during boot and live activation. An unvalidated module build carries no passing runtime evidence, and activation removes stale state evidence when the active package does not contain a sealed evidence file.

`repoctl final-seal` remains a broader source/release audit entrypoint for historical roadmap and cross-surface checks, but it is not the authoritative producer consumed by root-module runtime readiness.

## CHR07 destructive CRUD seal

`repoctl validate` and final-seal now execute `ValidateCRUDAtomicity` after Gate A. The CHR07 seal preserves registry-authoritative destructive targeting, mounted/live-service guards, atomic per-chroot override publication, rootfs/snapshot/service namespace migration, strict registry/snapshot `RowsAffected` semantics, crash recovery by old/new rename identity, import-backup ordering, and exact 9-canonical/21-source audit closure. General privileged-output publication remains CHR10-owned.

## CHR08 mount/session/service-runtime seal

`repoctl validate` and final-seal execute `ValidateMountServiceRuntime`. The CHR08 gate requires option-aware decoded mount evidence, transactional mount rollback and `/data` flag restoration, shared start/exec session construction, fail-closed status/doctor checks, strict trusted service-unit parsing/execution, durable process-state lifecycle semantics, Android operation reconciliation markers, and exact audit closure of D13/D25/D26 plus U116–U132/U225 (21 canonical findings / 49 source manifestations). D12 remains reserved for CHR16's logging/diagnostics closure.

## CHR09 metadata-faithful snapshot seal

`repoctl validate` and final-seal execute `ValidateSnapshotFidelity`. The CHR09 gate requires the Linux/Android metadata-preserving archive primitive, configured `snapshot_dir` as the single managed snapshot authority, rootfs-tar-v1 manifest/payload validation, restore refusal for legacy metadata-lossy snapshots, operation-provenance linkage for recovery snapshots, normal CLI snapshot commands, Android recovery selection tied to matching provenance, and exact audit closure of D16/D17 (2 canonical findings / 16 source manifestations). Install/upgrade and Android storage/UI follow-ups remain assigned to their later roadmap overlays with CHR09 recorded only as supporting work where appropriate.
## CHR11 installer/upgrade reconstruction evidence

- `internal/install/policy.go` is the backend source of truth for install distro, architecture, preset, profile, desktop, mirror, package-name, and shell-quoting policy.
- `install.form`, `install.preview`, CLI install, and Android install draft payloads use the same normalized request shape, including `resume`, `repair`, and `overwrite_existing`.
- `ValidateInstallerUpgradeReconstruction` is part of `repoctl validate` and the final release seal, covering Android form parity, upgrade preflight, catalog-completion install marking, package validation, locale/hooks, and CHR11 roadmap closure.

## CHR12 user identity safety

Intermediate overlay scope. Focused local checks cover user policy classification, sudo state derivation, password confirmation semantics, bridge preview payload compatibility, and repoctl source invariants. Full repo validation remains deferred to a later gate overlay because this overlay is intentionally applied with `--no-validate`.

## CHR13 catalog and package workflow

- Overlay: `chrootctl_chr13_catalog_package_workflow_v1`
- Scope: catalog/package preflight, risk/state propagation, external catalog trust, Android catalog controls, package inventory truncation truth.
- Intermediate policy: apply with `--no-validate`; full gate validation remains reserved for the next sensible seal overlay.
- Focused source gate: `ValidateCatalogPackageWorkflow`.

## CHR14 clipboard privileged integration

- Added `ValidateClipboardPrivilegedIntegration` source gate to repoctl and the final seal.
- Clipboard daemon control state now uses the Termux-private runtime root, rejects unsafe custom parents, serializes starts, refuses live socket takeover, cleans stale socket/token state on stop, and records bounded daemon lifecycle logs.
- Clipboard host set/get now default to the daemon host socket, preserve explicit empty text versus stdin, cap stdin at 1 MiB, and keep trailing newlines through both host CLI and generated chroot wrappers.
- Wrapper requests now carry the installing target name; the daemon requires marked wrappers for target-scoped requests, and `clipboard doctor --name` reports target-specific enablement.

## CHR15 module/runtime/release trust seal

- Added `ValidateModuleRuntimeReleaseTrust` to `repoctl validate` and final-seal.
- Focused checks for the overlay cover package manifest generation, rendered-tree and ZIP seal validation, module-runtime fail-closed readiness, real module-build preflight, shared startup-target resolution, Android module-build payload parity, rollback-capable replacement promotion, dynamic-library validation, executable production wrappers, and CHR15 audit closure.
- This is an intermediate overlay and should be applied with `--no-validate`; full release validation remains reserved for a later gate overlay.
## CHR16 — Logging, diagnostics, audit & evidence

Intermediate overlay validation performed in the sandbox:

- `go test -modfile=/mnt/data/chrootctl_chr15.local.mod ./... -run '^$' -count=1`
- Focused no-DB tests for logging, redaction, operations journal permissions, services severity helpers, and repoctl CHR16 source gate.

Full device validation remains deferred to a later gate overlay per the current roadmap workflow.

## CHR17 — Bridge protocol V2 convergence

Status: intermediate overlay, focused local checks only. Full validation is reserved for a later gate overlay.

Focused checks used during overlay construction:

```bash
go run ./cmd/cli-contract-gen --check
go test ./internal/bridge ./internal/repoctl -run 'CHR17|BridgeProtocolV2|ResponseSchema|Timeline|ValidateBridgeProtocolV2Convergence' -count=1
go test ./... -run '^$' -count=1
```

The sandbox used a temporary sqlite module stub for compile/focused checks only; the overlay does not modify `go.mod` and keeps the real sqlite dependency for Termux validation.


## CHR18 Android operation/Room/recovery engine

- Overlay 18 of 20 is implemented as an intermediate no-validate patch.
- Source gate: `repoctl` now calls `ValidateAndroidOperationRoomRecovery`.
- Focused checks: Android recovery policy tests and operation recovery contract tests cover retry gating, interrupted mapping, and cancel gating.
- Full Android/Go validation is intentionally reserved for a later gate overlay.

## CHR19 Android product/workspace correctness

- Overlay: 19 of 20.
- Source gate: `ValidateAndroidProductWorkspaceCorrectness`.
- Focused local checks: `go test ./internal/services ./internal/bridge ./internal/repoctl -run 'CHR19|AndroidProductWorkspace|StorageStatus|Logs' -count=1`; `go test ./... -run '^$' -count=1`.
- Android Gradle validation remains deferred to the final gate overlay per intermediate-overlay policy.

## CHR20 — Navigation, adaptive UI & final release seal

- Overlay: 20 of 20.
- Gate status: final validation gate, not an intermediate `--no-validate` overlay.
- Evidence: navigation/back-stack policy, proven operation notification deep links, lazy destination warmups, height/font-scale adaptive navigation, selected/live-region accessibility semantics, removed workspace restore cleanup, Android instrumentation checklist, and final validator wiring.
- Source gate: `ValidateNavigationAdaptiveFinalReleaseSeal`.
- Required validation: `go run ./cmd/cli-contract-gen --check`, `go run ./cmd/repoctl validate`, and Android `:chrootctlAndroidAppSeal` when the wrapper is available.

### CHR20 v3 gate reconciliation

The v2 Termux gate applied and built successfully, then failed two legacy overlay checks: CHR13 external catalog parent validation rejected `/data/data` because Android system ancestors are not owned by the Termux UID, and CHR15's module runtime test attempted to create an invalid identity/path row through the modern registry writer. v3 narrows the Android ancestor exemption to parent-chain validation only and updates the CHR15 test fixture to seed the legacy corrupt row directly before asserting module startup-target path validation.


## CHR21 — Android app validation seal

The Android app now has a dedicated post-roadmap seal overlay. The authoritative Android gate is `devtool --target chrootctl_android` plus the Gradle aggregate `:chrootctlAndroidAppSeal`. This gate covers stable toolchain verification, `:app:testDebugUnitTest`, `:app:assembleDebug`, `:chrootctlAndroidLintConfigurationSeal`, Room schema v5 presence, migration contract presence, and preservation of the Android behavior-policy test suite.

CHR20 sealed the Go/repoctl roadmap. CHR21 exists to prevent Android app changes from being marked fully sealed by a Go-only target summary.


## CHR21 Android app validation seal v2

This overlay is an Android gate retry after v1 confirmed the `chrootctl_android` target was running the intended Gradle graph but failed compilation. V2 fixed the Android compile blockers, then the native Termux gate reached lint and failed before source analysis while resolving the Maven-provided `androidLintTool` classpath. V3 keeps the Android app seal deterministic by requiring `:chrootctlAndroidAppSeal`, `:app:testDebugUnitTest`, `:app:assembleDebug`, and `:chrootctlAndroidLintConfigurationSeal`; the deterministic gate remains `:chrootctlAndroidLintConfigurationSeal`; the full external lint engine remains `:app:lintDebug` as a separately rerunnable check after the dependency cache is available.

## CHR21 Android app validation seal v5

The v5 gate repair keeps the deterministic Android seal graph from v3 and fixes the Kotlin unit-test compile failure in `HomeRefreshCoordinatorTest.FakeBridgeTransport` by implementing the complete `BridgeTransport` interface, including `transferState` and `cancelTransfer`.


## CHR21 Android app validation seal v5

Android seal v4 reached the Android JVM unit-test gate and failed in `BridgeOutputValidatorTest` because usage text on stdout was classified as `EMPTY_BRIDGE_RESPONSE`. v5 repairs the production validator classification and keeps the same Android seal tasks: `:chrootctlAndroidAppSeal`, `:app:testDebugUnitTest`, `:app:assembleDebug`, and `:chrootctlAndroidLintConfigurationSeal`.

## CHR22 — Android configuration-cache task hotfix

The post-CHR21 `devtool lint` run reached `:chrootctlAndroidLintConfigurationSeal` and marked it `UP-TO-DATE`, but Gradle 9.7.1 failed while storing the configuration cache because the Kotlin DSL action captured a build-script object through top-level variables. CHR22 moves every execution-time path used by the three custom Android verification actions into task-registration scope, removes the top-level provider variables, and adds policy coverage preventing those captures from returning. The hotfix intentionally keeps configuration cache enabled rather than suppressing the failure with `--no-configuration-cache`.

## CHR23 — Roadmap convergence seal

Overlay 23 of 23 restores a single composite release gate after the Android-only CHR21/CHR22 work. `.devtool-artifact/validate.sh` again runs `go run ./cmd/repoctl validate` before Android `:chrootctlAndroidAppSeal`, then replays `:chrootctlAndroidLintConfigurationSeal` to prove configuration-cache reuse.

The convergence gate closes all 272 canonical roadmap findings, including the 16 CHR16-owned findings and their 42 source manifestations. It adds production mutation audit coverage, CLI error redaction, bounded/symlink-safe log tails, service-log rotation, Android password-state cleanup and non-overlapping live-log refreshes, exact CHR14–CHR20 audit-coverage enforcement, and the schema-v4 root-module validation evidence contract consumed by the active module.

Acceptance requires the Devtool overlay apply itself to complete with zero diagnostics; Android-only success is no longer sufficient to claim full roadmap closure.
### Legacy final-seal isolation

`repoctl final-seal` remains available for the broader historical repository audit, but its schema-v3 output is repository-local (`dist/legacy-final-seal-results.json`) unless an explicit path is supplied. It must never overwrite `/data/adb/chrootctl/validation-results.json`; runtime readiness accepts only the schema-v4 evidence embedded by the root-module Devtool gate and published by the installed module lifecycle.

