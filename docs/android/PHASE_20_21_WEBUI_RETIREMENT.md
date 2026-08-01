# Phase 20-21: WebUI parity seal and retirement

Phase 20 turns the parity matrix into a release gate. Phase 21 retires the browser UI from the source package and module output.

## Completed

- Every former WebUI surface is marked Native complete or Retired in `WEBUI_PARITY_MATRIX.md`.
- `chrootctl-web` is removed from Python console scripts.
- FastAPI, Jinja2, Uvicorn and python-multipart are removed from project dependencies.
- The `src/chrootctl/web` package is removed.
- WebUI-only tests are removed and replaced by parity/retirement tests.
- Magisk/KSU rendering no longer emits `chrootctl-web`, `chrootctl-webui-service`, `webui.env` or `webroot` assets.
- Android SDK remains pinned to 36.

## Preserved

- The Python chroot services remain the source of truth.
- `chrootctl` remains the CLI.
- `chrootctl-app` remains the Android bridge.
- Foreground operations, Room cache, AIDL and RootService remain the native control path.
