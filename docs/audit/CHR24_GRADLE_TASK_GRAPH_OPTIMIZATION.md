# CHR24 — Gradle task graph optimization

Status: implemented

CHR24 is a post-roadmap optimization overlay for the final Android validation graph. It does not weaken the sealed gate; it removes redundant command-line roots from the artifact validator and documents the optimized invocation.

## Finding

The previous CHR23 validator invoked Gradle with all of these task roots in the first Android pass:

```bash
./gradlew --no-daemon --continue \
  :chrootctlAndroidAppSeal \
  :app:testDebugUnitTest \
  :app:assembleDebug \
  :chrootctlAndroidLintConfigurationSeal
```

`chrootctlAndroidAppSeal` already depends on `chrootctlDebugValidation`, and that internal aggregate depends on `verifyStableToolchainBaseline`, `:app:testDebugUnitTest`, `:app:assembleDebug`, and `chrootctlAndroidLintConfigurationSeal`. Listing the leaf tasks again as command-line roots is therefore redundant. Gradle will deduplicate task execution inside one invocation, but redundant roots still enlarge command construction, task selection, and Devtool phase surface area.

## Fix

The artifact validator now runs the first Android pass as the single release-authoritative aggregate:

```bash
./gradlew --no-daemon --continue :chrootctlAndroidAppSeal
```

The separate `:chrootctlAndroidLintConfigurationSeal` replay remains intentional. It proves Gradle configuration-cache reuse after the complete Android app gate has populated the cache.

## Preserved coverage

The optimized aggregate still covers:

- stable Android/Java/Kotlin/toolchain verification;
- debug JVM unit tests;
- debug APK packaging;
- deterministic lint-configuration seal;
- Room schema and migration contract presence;
- Android release-policy tests.

The Go roadmap gate remains first in `.devtool-artifact/validate.sh` through `go run ./cmd/repoctl validate`.

## Optimized Devtool apply task set

For this repository state, the optimized explicit task list is just the aggregate:

```bash
--task :chrootctlAndroidAppSeal
```

The aggregate fans out to the necessary Android leaves. Keeping separate `--task :app:testDebugUnitTest`, `--task :app:assembleDebug`, and `--task :chrootctlAndroidLintConfigurationSeal` is safe but redundant unless a developer is intentionally debugging one leaf outside the final seal.
