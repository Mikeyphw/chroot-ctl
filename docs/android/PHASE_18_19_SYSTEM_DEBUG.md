# Phase 18-19: System, support and Debug Workbench

Adds native system runtime status, module status/build, support bundle export, registry repair, temporary cleanup, and a grouped Debug Workbench.

## Phase 18

- `system.runtime`
- `system.module_status`
- `system.module_build_preview`
- `system.module_build`
- `support.preview`
- `support.bundle`
- `repair.preview`
- `repair.apply`
- `cleanup.temp_preview`
- `cleanup.temp`

## Phase 19

- `debug.probes`
- `debug.timeline`
- `debug.export`

Android keeps SDK 36 pinned and routes long-running operations through the existing foreground bridge service.
