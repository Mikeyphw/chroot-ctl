# WebUI OV08 — Settings and final convergence

Overlay 8 of 8 closes the KernelSU WebUI roadmap.

## Settings delivered

- device-local WebUI default chroot and accessibility preferences;
- backend-authoritative runtime, module and rclone readiness without exposing credential/config paths;
- active module startup targets read from the module package;
- typed `system.module_build_preview` → `system.module_build` workflow to rebuild startup targets with preview proof instead of editing boot scripts;
- effective configured mount/bind visibility for registered chroots;
- direct navigation to Rclone and Logs/diagnostics.

Changing module startup targets produces a managed module archive. The user must install that archive in the root manager and reboot before the new startup set becomes active.

## Security and convergence

The final WebUI keeps the OV01 security boundary: fixed backend executable candidates, typed/allow-listed operations, no arbitrary shell API, no CDN assets, and a CSP with `connect-src 'none'`. Rclone credentials remain backend-only.

The final navigation surface is:

`Chroots | Create | Transfer | Rclone | Operations | Logs | Settings`

The final validator checks all seven panels, JavaScript syntax, typed settings/startup contracts, accessibility preferences, CSP/arbitrary-shell hardening, and focused Go package tests for module/bridge/logging/redaction behavior.

## Final promise-audit corrections

The final convergence pass also closes two OV07 roadmap items that were not complete in its first implementation: Logs now includes persistent operation progress-event logs, an optional three-second follow mode for active log/event views, and copy-friendly controls for chroot logs, service journals, and operation events.

## Three-pass promise-audit corrections

The post-seal promise audit closed cross-section gaps that string-only convergence tests did not catch: Rclone-selected remote paths now reach the shared Transfer engine with explicit provenance; blocked transfer previews scrub passwords; Logs includes runtime/module/Rclone/backend readiness without private paths; and the stored default chroot is honored by Transfer and Logs target selectors when their previous selection is not valid. The final convergence test now asserts these contracts.
