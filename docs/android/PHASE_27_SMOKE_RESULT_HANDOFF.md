# Phase 27 - Smoke result capture and support handoff

Phase 27 makes real-device smoke useful after it runs. The app can now load the last smoke result, persist it as a managed JSON artifact, export smoke evidence, and create a support bundle tied to a failed smoke result.

## Bridge contracts

- `smoke.last_result`
- `smoke.result.persist`
- `smoke.result.export`
- `smoke.failure.bundle`

## Native UI

The Debug Workbench adds a smoke result handoff section with actions for the last result, persistence, evidence export, and failure bundle creation. SDK remains pinned to 36.
