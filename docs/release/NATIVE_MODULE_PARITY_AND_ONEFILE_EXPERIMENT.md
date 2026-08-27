# Native module parity and onefile experiment

This repository now has two release-time native-runtime checks beyond the module ZIP seal.

## Android app/module parity seal

The Android companion app resolves an installed module only when `RuntimeResolver.kt` agrees with the Python/Magisk release constants:

- bridge protocol version
- module id, version, and versionCode
- Python package version
- Android app versionName and versionCode
- native runtime kind, platform, ABI, root, and entrypoint

Run:

```bash
PYTHONPATH=src python3 scripts/validate-native-module-parity.py
```

The script intentionally checks the checked-in Android resolver constants and `docs/release/compatibility-manifest.json` against the same constants used by module generation. A release must fail if any of those surfaces drift.

## Optional onefile experiment

The supported module runtime remains Nuitka standalone under:

```text
runtime/arm64-v8a/chrootctl.dist/chrootctl-native-entry
```

A onefile build is only an experiment because onefile runtimes extract internal files before execution. That extraction model is harder to audit inside Magisk/KSU than a sealed standalone directory with a manifest inventory.

Generate the experimental command without building:

```bash
PYTHONPATH=src python3 scripts/build-native-android-runtime.py --onefile-experiment --print-command
```

Actually running the experiment requires an explicit opt-in flag:

```bash
PYTHONPATH=src python3 scripts/build-native-android-runtime.py --onefile-experiment --allow-onefile-experiment
```

Do not package the onefile artifact into the Magisk/KSU module until it has an equivalent integrity model to the standalone runtime manifest.
