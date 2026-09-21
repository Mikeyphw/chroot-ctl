# WR12/12 — Android retirement and root-module convergence seal

The standalone Kotlin/Gradle Android companion is retired. The supported Android delivery surface is now the Magisk/KernelSU root module, embedded WebUI, and Go-native backend.

## Retirement boundary

Removed:
- `android/` application source, Gradle wrapper/build logic, Android resources/tests and APK release path;
- `chrootctl_android` Devtool target;
- Android APK CI job.

Retained intentionally:
- Go `GOOS=android` runtime compilation and NDK/toolchain support because the root module itself runs on Android;
- historical Android audit/migration documents and frozen protocol fixtures where they remain evidence for the bridge contract;
- the protocol-v1 bridge itself, now consumed by the root-module WebUI.

## Final authority

`chrootctl_root_module` is the product target. Its validation covers JavaScript syntax, focused Go module/bridge/service/catalog/operation tests, and an actual root-module package build. The repository-level `repoctl validate` remains the broader source/contract gate.

The final WR12 artifact adds a retirement guard so standalone Android application source, Gradle project files, `chrootctl_android`, and the Android CI job cannot silently return.

## Historical executable seals

The pre-WR12 CHR01/03/04/05/08/09/10/11/12/13/15/16/17/18/19/20/23 repoctl validators encoded standalone-Android source paths. They are retained as historical Go source/audit documentation but are no longer invoked by `repoctl validate`; their Android-coupled unit wrappers are retired. Active validation now uses the current Go tests, frozen live bridge contracts, the WR12 retirement guard, WebUI parity tests, and root-module packaging.

The GO16 legacy-test map marks Android-only mappings as `retired-contract` and points them at the WR12 retirement seal.

## Generated Android workspace residue

Devtool's overlay inventory retires the standalone Android **product source and build definition**. It intentionally does not claim ownership of untracked machine-local/generated state such as `android/local.properties`, `.gradle/`, or `app/build/`. Those files may survive rollback/apply cycles until normal cleanup removes them; they are not a supported product surface and are ignored by the retirement seal. The seal fails if Gradle project definitions, wrapper files, or Android application source/test trees return.

### Empty source directories

Devtool may leave empty `android/app/src/main`, `src/test`, or `src/androidTest` directory nodes after deleting every inventoried file. Directory existence alone is not product existence. WR12 therefore seals the absence of product **files** in those trees, while allowing empty directory nodes and unrelated generated/local workspace residue.
