# Final validation evidence contract

GO17 release readiness is evidence-driven and Go-native. `repoctl final-seal` is the only supported producer of passing final-validation evidence; it executes the release gates itself and then writes `validation-results.json` atomically with mode `0600`.

Runtime readiness consumes `validation-results.json` from the chrootctl state directory, or the path named by `CHROOTCTL_VALIDATION_RESULTS`.

## Schema v3 and identity

The file uses `schemaVersion: 3` and records:

- `validationRunId` and `generatedAt`;
- optional `sourceCommit` and `sourceTree` when sealing from a Git checkout;
- `compatibilityManifestSha256`, the SHA-256 of `docs/release/compatibility-manifest.json`; and
- the exact required `checks` object.

When a Git checkout is available, `final-seal` refuses to record evidence from a dirty worktree and records the current `HEAD` and `HEAD^{tree}`. Runtime readiness rejects evidence when those recorded identities no longer match the current checkout. Installed runtimes without `.git` are anchored by the compatibility-manifest SHA-256.

## Required checks

The exact check IDs are:

- `go_test`
- `go_vet`
- `go_contracts`
- `repo_purity`
- `source_package`
- `android_compileDebugKotlin`
- `android_testDebugUnitTest`
- `android_lint_configuration_seal`
- `module_render`
- `module_zip`
- `module_shell`
- `source_no_webui`

A passing check carries `status: pass`, `exitCode: 0`, a non-empty `command`, a positive `recordedAt`, and provenance of either `subprocess` or `internal-check`. Missing, extra, malformed, or failed checks make release readiness fail closed.

`go_contracts` validates the retained GO16 test map, the frozen GO00 fixtures, and the live 78-node CLI / 86-operation bridge metadata. `source_package` builds the source archive twice and requires identical SHA-256 values. `module_zip` likewise packages the module twice and requires byte-for-byte deterministic ZIP output. The three Android checks execute the exact Gradle tasks rather than accepting caller assertions. `source_no_webui` scans the current runtime source for retired WebUI dependencies/surfaces.

Repository-internal validation also seals the CHR01–CHR03 roadmap foundations before final evidence can pass: build/Devtool configuration, generated CLI-contract freshness, the complete 609→272 audit ledger, and CHR03 configuration/registry/Room identity invariants.

## GO02 device prerequisite

The GO02 SQLite compatibility gate is separate from the 12 schema-v3 checks because it proves a physical execution environment, not a source-tree test. A final seal must either:

- run on Android/arm64, where the acceptance probe executes directly; or
- receive `--go02-evidence <file>` produced by `repoctl go02-device-acceptance --evidence <file>` on a real Android/arm64 device.

The device probe opens a frozen Python-created registry fixture with the Go SQLite layer, verifies the required PRAGMAs/schema/integrity/cascade behavior, mutates it, closes it, reopens it, and verifies the committed Go-written state. Evidence is rejected unless it is a regular non-symlink file with no group/other permissions and the expected frozen-fixture identity/invariants.

## Producer and persistence safety

Use:

```sh
scripts/final-seal --go02-evidence /path/to/go02-evidence.json
```

On Android/arm64 the `--go02-evidence` argument is not required because the probe runs directly. `scripts/release` invokes the same final seal before creating release artifacts, so release packaging cannot bypass these gates.

Evidence is written through a same-directory temporary file, file `fsync`, atomic rename, and mode `0600`. This is an execution/provenance and source-identity seal, not a public-key signature scheme; an actor with arbitrary write access as the evidence owner/root can still replace local bytes outside chrootctl.

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
- Required validation: `go run ./cmd/cli-contract-gen --check`, `go run ./cmd/repoctl validate`, and Android `:chrootctlDebugValidation` when the wrapper is available.

### CHR20 v3 gate reconciliation

The v2 Termux gate applied and built successfully, then failed two legacy overlay checks: CHR13 external catalog parent validation rejected `/data/data` because Android system ancestors are not owned by the Termux UID, and CHR15's module runtime test attempted to create an invalid identity/path row through the modern registry writer. v3 narrows the Android ancestor exemption to parent-chain validation only and updates the CHR15 test fixture to seed the legacy corrupt row directly before asserting module startup-target path validation.


## CHR21 — Android app validation seal

The Android app now has a dedicated post-roadmap seal overlay. The authoritative Android gate is `devtool --target chrootctl_android` plus the Gradle aggregate `:chrootctlAndroidAppSeal`. This gate covers stable toolchain verification, `:app:testDebugUnitTest`, `:app:assembleDebug`, `:chrootctlAndroidLintConfigurationSeal`, Room schema v5 presence, migration contract presence, and preservation of the Android behavior-policy test suite.

CHR20 sealed the Go/repoctl roadmap. CHR21 exists to prevent Android app changes from being marked fully sealed by a Go-only target summary.


## CHR21 Android app validation seal v2

This overlay is an Android gate retry after v1 confirmed the `chrootctl_android` target was running the intended Gradle graph but failed compilation. V2 fixed the Android compile blockers, then the native Termux gate reached lint and failed before source analysis while resolving the Maven-provided `androidLintTool` classpath. V3 keeps the Android app seal deterministic by requiring `:chrootctlAndroidAppSeal`, `:app:testDebugUnitTest`, `:app:assembleDebug`, and `:chrootctlAndroidLintConfigurationSeal`; the full external lint engine remains `:chrootctlAndroidLintConfigurationSeal` as a separately rerunnable check after the dependency cache is available.

## CHR21 Android app validation seal v5

The v5 gate repair keeps the deterministic Android seal graph from v3 and fixes the Kotlin unit-test compile failure in `HomeRefreshCoordinatorTest.FakeBridgeTransport` by implementing the complete `BridgeTransport` interface, including `transferState` and `cancelTransfer`.


## CHR21 Android app validation seal v5

Android seal v4 reached the Android JVM unit-test gate and failed in `BridgeOutputValidatorTest` because usage text on stdout was classified as `EMPTY_BRIDGE_RESPONSE`. v5 repairs the production validator classification and keeps the same Android seal tasks: `:chrootctlAndroidAppSeal`, `:app:testDebugUnitTest`, `:app:assembleDebug`, and `:chrootctlAndroidLintConfigurationSeal`.
