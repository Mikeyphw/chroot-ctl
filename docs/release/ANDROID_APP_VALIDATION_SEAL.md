# Android app validation seal

Overlay 21 of 21 adds a dedicated Android app gate after the CHR01–CHR20 Go/repoctl seal.

## Gate owner

Use the `chrootctl_android` Devtool target for Android app validation. The target owns the `android/` project and consumes the shared bridge/model contracts under `migration/contracts/v1`.

## Required tasks

The Android seal task is:

```bash
./gradlew --no-daemon --continue :chrootctlAndroidAppSeal
```

The aggregate depends on `:chrootctlDebugValidation`, which in turn runs:

- `:verifyStableToolchainBaseline`
- `:app:testDebugUnitTest`
- `:app:assembleDebug`
- `:chrootctlAndroidLintConfigurationSeal`

The full external lint engine remains `:app:lintDebug`, but it is no longer part of artifact application because native Termux can fail before source analysis while resolving the Maven-provided `androidLintTool` classpath.

The seal task also verifies that the Room schema v5 file, migration contracts, lint configuration, and the core Android test suites remain present.

## Devtool command

Run the overlay with validation enabled:

```bash
devtool --copy --target chrootctl_android apply overlay /sdcard/Download/chrootctl_android_app_validation_seal_v1.tar.gz --keep-artifact
```

Use the normal resource flags and explicit task list from the project handoff. Do not add `--no-validate`; this is a gate overlay.

## Acceptance

The Android app is sealed only when Devtool reports the Android target validation completed successfully with zero diagnostics and the Gradle graph includes unit tests, debug APK packaging, and deterministic lint-configuration checks. Run `:app:lintDebug` after prewarming the lint tool dependency cache for full source lint. A Go-only summary is not enough for this seal.


## v2 compile gate fix

The first Android seal run proved that the target and Gradle graph were correct but stopped at `:app:compileDebugKotlin`. Version 2 keeps the same validation graph and fixes the two Android compile blockers: `BridgeProcess` no longer depends on `Process.pid()`, and `ChrootRootService` no longer references the unavailable `OsConstants.O_DIRECTORY` symbol.

## v5 unit-test contract fix

The third Android seal reached `:app:compileDebugUnitTestKotlin` and exposed a test double drift: `HomeRefreshCoordinatorTest.FakeBridgeTransport` did not implement the newer `BridgeTransport.transferState` and `BridgeTransport.cancelTransfer` methods. Version 4 updates that fake transport so the Android unit-test source set compiles against the current bridge contract.


## v5 unit-test gate repair

- Preserves the Android app seal graph from v3/v4.
- Fixes `BridgeOutputValidator` so non-empty non-JSON stdout is classified as `INVALID_BRIDGE_RESPONSE`, while genuinely empty stdout with stderr remains `EMPTY_BRIDGE_RESPONSE`.
- Fixes `AndroidAppSealPolicyTest` to avoid nullable `System.getProperty("user.dir")` Kotlin type drift.

## CHR22 configuration-cache hotfix

Overlay 22 of 22 fixes the Gradle 9.7.1 configuration-cache serialization failure found after CHR21. The Android verification task actions no longer reference top-level Kotlin build-script variables or `Project` helpers at execution time. `verifyStableToolchainBaseline`, `chrootctlAndroidLintConfigurationSeal`, and `chrootctlAndroidAppSeal` resolve their files during task configuration and capture only serializable task-local state.

The hotfix keeps `org.gradle.configuration-cache=true`; it does not hide the defect by disabling configuration cache. The expected post-fix lint phase is still `:chrootctlAndroidLintConfigurationSeal`, with `:app:lintDebug` remaining the separately rerunnable full external lint engine.

