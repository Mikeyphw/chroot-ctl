# WebUI to Android parity matrix

This matrix is the Phase 20 seal for replacing the FastAPI/Jinja WebUI with the native Android application.
Every human-facing WebUI surface is now either **Native complete** or deliberately **Retired** as browser-only plumbing.

| Former WebUI surface | Native destination | Migration state | Native proof |
|---|---|---|---|
| Dashboard | Home | Native complete | Home/runtime readiness from `system.runtime`, `system.status`, `system.doctor` |
| Quick Start | Home onboarding | Native complete | Home recommendations and install entry point |
| Chroot list | Chroots | Native complete | `chroots.list` and native list/detail UI |
| Chroot detail | Chroot detail | Native complete | Overview, runtime, users, services, snapshots and packages panels |
| Install wizard | Install | Native complete | `install.form`, `install.preview`, `install.run` |
| Jobs list/detail/event stream | Activity | Native complete | Persistent operations and NDJSON foreground operation stream |
| Chroot start/restart/removal | Chroot detail lifecycle panel | Native complete | preview-first lifecycle actions and typed removal confirmation |
| Snapshot list/create/restore/export | Chroot detail snapshots panel | Native complete | snapshot preview, create, restore and export operations |
| Transfer inspect/import/export | Tools transfer panel | Native complete | SAF document picker plus descriptor transfer bridge |
| Users list/detail/add/remove/password/sudo/shell | Chroot detail users panel | Native complete | users bridge contracts and typed confirmations |
| Services list/detail/start/stop/restart/enable/disable/journal | Chroot detail services panel | Native complete | services bridge contracts and journal loading |
| Tools and add-ons catalog | Tools catalog panel | Native complete | catalog search, preview and apply operations |
| Package inventory and compare | Tools packages panel | Native complete | `packages.inventory`, `packages.compare` |
| Registry repair | Tools support/system panel | Native complete | `repair.preview`, `repair.apply` |
| Logs/checks/audit/support bundle | Activity, Diagnostics and Support | Native complete | debug timeline, support bundle and diagnostics exports |
| KernelSU/module/system status | Tools system panel | Native complete | `system.runtime`, `system.module_status` |
| Module build | Tools system panel | Native complete | `system.module_build_preview`, `system.module_build` |
| Debug workbench | Tools debug workbench | Native complete | `debug.probes`, `debug.timeline`, `debug.export` |
| FAQ/docs/API reference | Native help/docs + bridge protocol docs | Native complete | Android docs and protocol validators |
| CSRF/access token | None | Retired | Browser-only security removed with WebUI |
| Chunked HTTP upload/download URLs | SAF descriptors | Retired | `transferFromDescriptor`, `transferToDescriptor` |
| FastAPI HTTP server / localhost port 8420 | libsu RootService Binder bridge | Retired | `chrootctl-app` bridge and Android RootService |

## Phase 21 retirement

The WebUI source package, console script, FastAPI/Jinja/Uvicorn dependencies, Playwright/browser tests, browser upload tests, WebUI module service and WebUI module artifacts are removed.
The supported human-facing UI is now the Android app; the supported machine-facing local API is the versioned `chrootctl-app` bridge.
