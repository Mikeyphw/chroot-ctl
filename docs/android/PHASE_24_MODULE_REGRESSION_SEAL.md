# Phase 24: Module Regression Seal

Phase 24 seals the Magisk/KernelSU module renderer after WebUI retirement.

## Purpose

Phase 23 removed stale generated module output from the repository. Phase 24 prevents the renderer from producing those artifacts again. The source package remains Android-app and bridge driven; the module must not reintroduce a browser server, WebUI service, webroot, or Playwright payload.

## Enforced behavior

`validate_magisk_module()` now rejects generated module trees containing retired WebUI path tokens:

- `chrootctl-web`
- `chrootctl-webui-service`
- `webui.env`
- `webroot`
- `playwright.config.ts`
- `payload/src/chrootctl/web`

The existing `build.sh` already calls `validate_magisk_module()` before zipping, so local package builds inherit the seal without adding shell-string token hacks to the build script.

## Release rules

- Android SDK remains pinned to 36.
- `out/` and `tmpout/` remain uncommitted generated output.
- WebUI source remains retired.
- Module output must contain `system/bin/chrootctl` and must not contain WebUI commands or browser assets.
- Future validators may mention retired tokens only as deny-list checks, never as generated runtime assets.
