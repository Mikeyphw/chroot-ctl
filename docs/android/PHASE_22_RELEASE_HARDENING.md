# Phase 22: Release hardening seal

Phase 22 is the final hardening pass after the WebUI retirement. It does not add a new product surface. It locks down the native Android + Python bridge architecture so future overlays cannot accidentally reintroduce old browser, storage, IPC, SDK or lint hazards.

## Release hardening goals

- Keep Android SDK 36 pinned unless the project owner explicitly changes it.
- Keep the WebUI retired: no FastAPI, Jinja2, Uvicorn, python-multipart, `chrootctl-web`, browser templates, browser static assets or WebUI module service files.
- Keep the Android app native: no WebView and no localhost HTTP control path.
- Keep the privileged interface as fixed AIDL/Binder IPC, not arbitrary shell execution.
- Keep foreground operations user-visible with the `dataSync` service type and matching foreground service permissions.
- Keep import/export on the Storage Access Framework with descriptor transfer, not broad storage permissions.
- Keep destructive actions behind preview and typed confirmation flows.
- Keep operation execution recoverable through the persistent operation journal and foreground service wiring.
- Keep support, repair, debug and export paths valid after WebUI removal.

## Android contracts sealed

The Android project remains pinned to:

```text
compileSdk = 37
targetSdk = 36
minSdk = 26
```

The app keeps strict lint:

```text
abortOnError = true
warningsAsErrors = true
```

Manifest/resource consistency is part of the phase gate:

- `@xml/backup_rules` exists when referenced.
- `@xml/data_extraction_rules` exists when referenced.
- Adaptive icons include a `monochrome` tag for themed icon lint.
- No broad storage permission is declared.
- No `QUERY_ALL_PACKAGES` permission is declared.
- The operation service declares `android:foregroundServiceType="dataSync"`.

## Fixed AIDL seal

The root service interface is intentionally narrow:

```text
serviceInfo
capabilities
query
preview
startOperation
operationState
cancelOperation
transferFromDescriptor
transferToDescriptor
```

The interface still deliberately excludes arbitrary command methods such as `runShell` or `executeArbitraryCommand`.

## Storage Access Framework seal

Import/export remains descriptor-based:

- `ActivityResultContracts.OpenDocument` for import.
- `ActivityResultContracts.CreateDocument` for export.
- `transferFromDescriptor` for controlled import staging.
- `transferToDescriptor` for controlled artifact export.
- `stageImportArchive` and `copyManagedArtifactToDocument` on the root side.

## Release operations sealed

Phase 22 verifies that the bridge still exposes the native app operations that replaced WebUI flows:

```text
install.run
chroots.start
chroots.restart
chroots.remove.execute
snapshots.restore
users.set_password
services.restart
catalog.apply
transfer.import
transfer.export
system.module_build
support.bundle
repair.apply
cleanup.temp
debug.export
```

## WebUI remains retired

The old WebUI remains fully retired. The release gate rejects:

- `src/chrootctl/web` source files.
- browser/Playwright WebUI tests.
- FastAPI/Jinja/Uvicorn/python-multipart dependencies.
- `chrootctl-web` entry points.
- Magisk/KernelSU WebUI service files.
- browser webroot assets.

## Validation

Run:

```bash
devtool --yes --copy   -r "$HOME/Code/chroot-ctl"   --target chrootctl_android   apply-overlay "$HOME/Downloads/chrootctl_android_phase22_release_hardening_overlay.zip"   --validate
```

The Phase 22 validator is:

```bash
python scripts/validate-android-phase22.py
```

It is intentionally strict. This phase is the castle wall, not another room inside the castle. If a future overlay reintroduces WebUI, broad permissions, arbitrary shell IPC, SDK drift, missing backup resources, fragile Kotlin Flow inference or unsafe notification constants, Phase 22 should catch it early.
