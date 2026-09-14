# ChrootCTL Android

This directory contains the native Android companion for the **Go-native chrootctl backend**. The production backend lives under `cmd/chrootctl`; release/module runtime construction is owned by `cmd/repoctl`. Python is legacy migration material and is not the authoritative Android backend.

The app uses a narrow privileged boundary:

- Compose Material 3 shell with **Home, Chroots, Install, Activity, and Tools** destinations.
- Room-backed operation, event, chroot, check, and Home snapshot state.
- libsu `RootService` with a fixed AIDL surface and no arbitrary command method.
- allowlisted JSON bridge requests plus descriptor-backed transfer/operation streaming.
- packaged Go runtime discovery with controlled compatibility fallback where explicitly supported.
- user-visible foreground operations and recovery state.

Backend behavior belongs in the Go services/bridge. Android should project typed backend state and invoke allowlisted capabilities rather than reimplementing chroot policy in Kotlin or introducing generic shell execution.

## Product boundaries

Devtool exposes three separate products:

- `chrootctl_go` — normal human-facing Go CLI/backend (`platform = "cli"`).
- `chrootctl_android` — this Android app (`platform = "android"`).
- `chrootctl` — repoctl runtime/module/release pipeline (`platform = "release"`).

`go run ./cmd/repoctl build-runtime` is the release-authoritative Android/ARM64 runtime builder because it resolves the Termux/NDK CGO compiler explicitly. The normal Go target intentionally does not expose a host-sensitive Android CGO variant.

## Validation

The normal Android gate is one Gradle graph/process:

```bash
./gradlew --no-daemon --continue :chrootctlDebugValidation
```

That aggregate runs stable-toolchain verification, debug unit tests, debug packaging, and a deterministic lint-configuration seal. `verifyStableToolchainBaseline` declares its inputs/output and is cache/up-to-date aware, so keeping it behind `preBuild` does not force a full re-scan on every build.

For focused debugging, individual tasks such as `:app:compileDebugKotlin` remain available, but they are not separate phases in the normal full validation pipeline.

## Architecture and test ownership

Large orchestration surfaces are tracked by behavior instead of treating a multi-workflow source file as one audit unit. See `docs/android/BEHAVIOR_OWNERSHIP.md` and `docs/android/behavior-ownership.json`.

CHR01 also introduces a directly unit-tested `HomeRefreshCoordinator` behind the `BridgeTransport` boundary. This gives repository orchestration a real JVM test seam while preserving the fixed RootService/AIDL boundary. Later roadmap overlays expand direct tests in the behavior domain they modify.


## Android app seal

The full Android app seal is:

```bash
./gradlew --no-daemon --continue :chrootctlAndroidAppSeal
```

`chrootctlAndroidAppSeal` depends on `chrootctlDebugValidation`, so it executes stable-toolchain verification, JVM unit tests, debug APK packaging, and a deterministic lint-configuration seal in one Gradle graph. The task also records a seal stamp only after the Room schema, migration contracts, lint configuration, and core Android test suites are present.

When validating through Devtool, use the Android target so the result reports Android app coverage directly:

```bash
devtool --copy --target chrootctl_android apply overlay <overlay.tar.gz> --keep-artifact
```
