# CUX-03 — Capability truth and visible bug remediation

CUX-03 of 7 aligns the WebUI's shipped Diagnostics queries with the frozen backend contract, merges the legacy Debug & readiness entry point into System → Diagnostics, makes unavailable rclone state non-actionable, and exposes concrete runtime/readiness reasons instead of unexplained `Not ready`/`Unavailable` labels.

Security boundary: this overlay adds only existing read-only query operations to the WebUI query allow-list. It does not add generic execution, shell, argv, mutation, or privileged HTTP routes. Existing preview/run gates remain unchanged.
