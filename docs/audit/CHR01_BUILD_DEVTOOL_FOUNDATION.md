# CHR01 — Build & Devtool foundation closure

Baseline: `chroot-ctl-20260912-153425-968931.tar.gz`.

CHR01 owns canonical findings **D37, U097, U098, and U099**. The repository-level machine ledger also preserves all **609 source findings → 272 canonical findings → CHR01–CHR20 owner overlays** so later work cannot silently omit an audited item.

## D37 source-manifestation closure

| Source finding | Result | Evidence |
|---|---|---|
| `DANDROID-01` | Closed | `.devtool.toml`: `split_gradle = false`; one Android validation node in Devtool plan. |
| `DANDROID-02` | Closed | `.devtool.toml`: canonical `runner`/`platform`; `devtool config migrate --check` reports canonical. |
| `DANDROID-03` | Closed | Removed duplicated Gradle CLI args and repository `--no-configuration-cache`; stable project knobs remain in `gradle.properties`. |
| `DANDROID-04` | Closed | Explicit target `inputs`/`outputs`; Devtool planner reports known read/write scopes. |
| `DANDROID-05` | Closed | Validation phases explicitly set `dependencies = []`, `compile = []`, `resources = []`. |
| `DANDROID-06` | Closed | Preflight is `:verifyStableToolchainBaseline`. |
| `DANDROID-07` | Closed | Instrumentation remains `never` until real androidTest coverage is introduced. |
| `DANDROID-08` | Closed | Structured Gradle events remain disabled for the normal Android target. |
| `DANDROID-09` | Closed | Android validation `memory_guard_mb = 0`; no misleading top-level guard. |
| `DANDROID-10` | Closed | Toolchain verifier declares five inputs, deterministic stamp output, and build-cache eligibility. |
| `GRADLE-01` | Closed | Real toolchain verifier replaces `help` preflight. |
| `GRADLE-02` | Closed | Dedicated compile phase removed; README names `:app:compileDebugKotlin` only as an explicit focused gate. |
| `GRADLE-03` | Closed | Dedicated resource phase removed; package/test own transitive resource work. |
| `GRADLE-04` | Closed | `split_gradle = false`; Devtool emits one Android validation builder action. |
| `GRADLE-05` | Closed | Repository no longer injects `--no-configuration-cache`; the current Devtool/Gradle path honors the project configuration-cache setting, and CHR22 makes all custom verification task actions configuration-cache safe. |
| `GRADLE-06` | Closed | Verifier inputs/output/cache contract makes UP-TO-DATE/build-cache behavior meaningful. |
| `GRADLE-07` | Closed | `preBuild` safety remains, but verifier can now be skipped/restored when unchanged. |
| `GRADLE-08` | Closed | No separate normal compile gate remains; focused compile documentation standardizes on `:app:compileDebugKotlin`. |
| `GRADLE-09` | Closed | Removed duplicated Gradle args and all repeated phase resource profiles; one validation resource policy remains. |
| `GRADLE-10` | Closed | Removed duplicated parallel/Kotlin incremental/compiler-strategy Devtool args. |
| `GRADLE-11` | Closed | Removed `-XX:ActiveProcessorCount=2` and `org.gradle.workers.max=2`; Devtool resource policy can actually use four workers/CPUs. |
| `GRADLE-12` | Closed | Single-module `affected_module_lint` disabled. |
| `GRADLE-13` | Closed | CI invokes the release-authoritative `:chrootctlAndroidAppSeal` once with `--continue`; its internal graph retains `:chrootctlDebugValidation`. |
| `GRADLE-14` | Closed | `repoctl FinalSeal` invokes the same aggregate once and records all three historical Android evidence IDs from that shared execution. |
| `GRADLE-15` | Closed | `clean` remains available but is absent from normal validation. |
| `DCLI-01` | Closed | `chrootctl_go` is the normal CLI target with `runner = "go"`, `platform = "cli"`. |
| `DCLI-02` | Closed | Removed the unsupported/misleading `coalesce_validation = true`. |
| `DCLI-03` | Closed | Go target declares `.devtool/build/go/**` and `.devtool/package/go/**` outputs; planner reservation is known. |
| `DCLI-04` | Closed | Release target has explicit `validate = ["runner:command#test"]`; dry-run validate plans successfully. |
| `DCLI-05` | Closed | Generic `chrootctl` target is now explicitly the `release` product, separate from the normal CLI. |
| `DCLI-06` | Closed | Release target `test_command` runs `go run ./cmd/repoctl validate` and therefore includes repository/contract gates. |
| `DCLI-07` | Closed | Release target run action is `go run ./cmd/repoctl host`, not CLI help. |
| `DCLI-08` | Closed | All project/target legacy `kind`/`type` aliases migrated to canonical schema. |
| `DCLI-09` | Closed | Product identities are workspace / cli / android / release via `platform`. |
| `DCLI-10` | Closed | Removed Go `root = "."`; explicit Go inputs make Android-only changes select only `chrootctl_android` in audited Devtool affected analysis. |
| `DCLI-11` | Closed | Removed the host-sensitive Android/ARM64 Go convenience variant; `repoctl build-runtime` is the sole release-authoritative CGO Android runtime path. |

## Standalone foundation findings

| Canonical | Source | Result | Evidence |
|---|---|---|---|
| `U097` | `ANDROID-BASE-01` | Closed | `android/README.md` now names the Go backend as authoritative, documents all five destinations including Install, and documents the current target/validation model. |
| `U098` | `ANDROID-BASE-02` | Closed for the CHR01 foundation scope | `BridgeTransport`, `HomeSnapshotStore`, and directly tested `HomeRefreshCoordinator` establish a real JVM seam through privileged transport → repository orchestration → coherent Home persistence, while existing RootService recovery tests remain in place. The behavior ownership manifest requires later domain overlays to add direct tests for the behavior they change. |
| `U099` | `ANDROID-BASE-03` | Closed | `docs/android/BEHAVIOR_OWNERSHIP.md` and `behavior-ownership.json` decompose the three >4,300-line high-risk surfaces by behavior and assign each behavior an overlay/evidence owner. `repoctl validate` rejects loss of that map or the CHR01 direct test. |

## Executable gates introduced

- `ValidateAuditCoverage` enforces 20 overlays, D01–D45, U001–U227, 272 canonical entries, and 609 unique `(source report, source ID)` rows.
- `ValidateBuildFoundation` enforces canonical Devtool schema, scoped targets, resource policy, coalesced CI/repoctl Android validation, cache-aware verifier, current Android README, behavior ownership, and the direct orchestration test.
- Final-seal evidence adds `audit_coverage`, which executes both audit-accounting and CHR01 build-foundation checks.
- `verifyStableToolchainBaseline` is input/output declared, cache-eligible, and produces `build/verification/stable-toolchain-baseline.txt`.
- `chrootctlAndroidAppSeal` is the release-authoritative aggregate. Its internal `chrootctlDebugValidation` dependency covers stable-toolchain verification, unit tests, assembleDebug, and the deterministic lint-configuration seal in one Gradle graph.

## Local construction-time verification

- Audited Devtool `config migrate --check`: canonical, no migration findings.
- `chrootctl` release target dry-run validate: valid one-node explicit test workflow.
- `chrootctl_go` dry-run validate: four independent Go stages retained.
- `chrootctl_android` dry-run validate: one Android Validation action with known read/write scopes.
- Affected-target probe: Android-only Kotlin → only `chrootctl_android`; Go CLI file → only `chrootctl_go`; repoctl file → only `chrootctl`; `.devtool.toml` → all three.
- Standalone Go tests for the new audit/build-foundation validators pass.
- Full Go suite could not execute in the artifact-construction container because the module cache lacks `github.com/mattn/go-sqlite3` and outbound dependency download is blocked. The overlay validation script runs the real gates in the destination repository.

## Configuration-cache note

The repository does not disable Gradle configuration cache. The current `chrootctl_android` validation path honors `org.gradle.configuration-cache=true`; CHR22 hardened `verifyStableToolchainBaseline`, `chrootctlAndroidLintConfigurationSeal`, and `chrootctlAndroidAppSeal` so their execution actions capture only task-local serializable state. CHR23 keeps that behavior in the composite release gate and replays the lint-configuration seal to prove cache reuse.
