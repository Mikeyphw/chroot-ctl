# CUX-04 functional convergence mid-gate

CUX-04 is the validation midpoint for the seven-overlay CUX campaign. It converges KSU and standalone startup semantics, bounds backend startup, persists navigation across successful backend re-checks, centralizes shell/backend state, and freezes the CUX-01 through CUX-04 UI/backend contract in `TestCUX04FunctionalConvergenceMidGate`.

The Devtool root-module validation workflow is the authoritative mid-gate: restore, build, complete tests, lint, and package/seal must all pass before CUX-05.

## Legacy regression migration

The mid-gate migrates pre-CUX tests to the new information architecture without deleting coverage. Create and Catalog must remain reachable through contextual tools; Users, Services, Storage and Snapshots must remain reachable from selected-chroot context; the KernelSU ABI test continues to seal verbatim argv transport while startup copy is transport-neutral.
