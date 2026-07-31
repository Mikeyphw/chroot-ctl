# ChrootCTL Android

This directory contains the native Android replacement for the legacy WebUI.

The Phase 0-4 scaffold intentionally implements only the secure foundation:

- Compose Material 3 shell with Home, Chroots, Activity and Tools destinations
- Room operation/event cache
- libsu RootService
- fixed AIDL interface without arbitrary command execution
- runtime resolution for packaged or Termux chrootctl backends
- JSON requests and descriptor-backed NDJSON operation streaming

The Python backend remains authoritative. Add future features by extending the allowlisted bridge registry and feature repositories, not by introducing generic shell execution or duplicating chroot rules in Kotlin.

## Validation

```bash
./gradlew :app:testDebugUnitTest
./gradlew :app:lintDebug
./gradlew :app:assembleDebug
```
