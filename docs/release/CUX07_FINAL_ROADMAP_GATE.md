# CUX-07 — final roadmap gate and release seal

CUX-07 closes the seven-overlay chrootctl WebUI overhaul. The final gate replays the product-shell, chroot hierarchy, capability truth, backend lifecycle, operational UX, transfer/rclone/system and accessibility promises together with the existing root-module build/test/lint/package seal.

## Final convergence fix
The final audit found a real routing defect: several contextual panels (Activity, Snapshots, Storage, Catalog, Maintenance, Diagnostics and Readiness) existed but were not explicitly toggled by `showSection`; Activity could additionally fall through to the placeholder state. CUX-07 fixes that defect instead of merely sealing the existing tree.

## Required release gate
Validation must run with Devtool (no `--no-validate`): restore, build, full tests, lint, package/seal, artifact validation and finalization. The permanent `TestCUX07FinalRoadmapGate` verifies route/panel reachability, chroot context, terminal/jobs/activity authority, transfer/rclone/system surfaces, transport-neutral shell, accessibility and the absence of frontend raw privileged execution.

## Four-audit closure
1. CUX-01–02 shell, Home and contextual chroot hierarchy.
2. CUX-03–04 capability truth, diagnostics, transport parity and finite backend lifecycle.
3. CUX-05–06 Terminal/Jobs/Activity, Transfer/Rclone/System and responsive/accessibility convergence.
4. CUX-07 routing repair, regression gate, package/release seal and artifact-v2 integrity.

## v2 final-gate correction

The System → Logs child route retains `data-section="logs"` in addition to its CUX `data-route="logs"` identity. This is not a return to the legacy global navigation: it preserves the long-standing WebUI foundation/security-shell contract while Logs remains contextual under System. The CUX-07 regression gate seals both identities.
