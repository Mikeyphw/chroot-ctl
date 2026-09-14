# CHR22 Android configuration-cache hotfix

Overlay 22 of 22 repairs the Gradle 9.7.1 configuration-cache failure exposed by the `chrootctl_android` lint phase after CHR21.

## Failure

`devtool lint` reached `:chrootctlAndroidLintConfigurationSeal`, the task itself was `UP-TO-DATE`, and Gradle then rejected configuration-cache storage because the Kotlin DSL task action captured top-level build-script state.

## Fix

The custom Android verification tasks now resolve every execution-time path inside each task-registration block. Their `doLast` actions capture only task-local `File`, `String`, and collection values, never top-level Kotlin build-script variables or `Project` helpers. The same repair is applied to:

- `:verifyStableToolchainBaseline`
- `:chrootctlAndroidLintConfigurationSeal`
- `:chrootctlAndroidAppSeal`

The old top-level provider variables are removed so later edits cannot accidentally reintroduce the same configuration-cache serialization failure. The generated lint/app-seal stamps record `configurationCacheSafe=true`.

## Regression coverage

`AndroidAppSealPolicyTest` asserts that configuration cache stays enabled, that task-local path resolution remains present, that `file(relativePath)` is not called from the app-seal action, and that the removed top-level task-state names do not return.

## Device validation

Apply this hotfix through the `chrootctl_android` target with validation enabled and explicitly request the lint configuration seal plus the Android app seal/test/package tasks. A successful run must no longer end with `cannot serialize Gradle script object references`.
