# Android replacement phases 0-4

## Phase 0: parity inventory

- Added `WEBUI_PARITY_MATRIX.md` as the removal gate.
- Classified every existing human-facing WebUI area.
- Defined browser-only behavior that must be replaced rather than copied.

## Phase 1: versioned bridge

- Added `chrootctl app` and `chrootctl-app` entry points.
- Added protocol version 1 request and response envelopes.
- Added an allowlisted operation registry.
- Added stable structured errors and redaction.
- Added JSON responses and NDJSON operation events.

## Phase 2: persistent operations

- Added atomic operation records and append-only event journals.
- Added cancellation markers and process-group cancellation.
- Added global/target lock foundations.
- Added stale-process recovery.
- Converted `WebJobManager` into a compatibility adapter over the persistent engine.

## Phase 3: Android scaffold

- Added a Java 21, compileSdk 36 Compose project under `android/`.
- Added Material 3 adaptive navigation, Room foundation, feature package boundaries and strict lint.
- Deliberately omitted scanner, cleanup, broad storage and package-query behavior from DustUI.

## Phase 4: fixed root bridge

- Added an allowlisted AIDL interface with no arbitrary-shell method.
- Added root runtime discovery for packaged and Termux Python backends.
- Added fixed `ProcessBuilder` execution with argument arrays.
- Added JSON calls and descriptor-backed NDJSON streaming.
- Added native root/backend readiness presentation.

## Deferred validation sequence

The artifact requires deferred validation. Apply it without consuming the full validation plan, then advance one phase at a time:

```bash
devtool --yes -r "$HOME/Code/chroot-ctl" --target chrootctl apply-overlay "$HOME/Downloads/chrootctl_android_phase00_04_foundation_overlay.zip" --defer-validate
devtool --yes -r "$HOME/Code/chroot-ctl" --target chrootctl validate continue
```

Repeat `validate continue` until the session finalizes. The first failing phase remains available for repair and retry instead of rolling back automatically.
