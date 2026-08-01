# Phase 25 - Real-device operational smoke suite

Phase 25 adds a native smoke suite for real device validation after WebUI retirement.

## Contracts

- `smoke.plan` returns the read-only smoke plan.
- `smoke.run` runs the smoke as a foreground operation and records the operation journal.
- `smoke.report` returns the latest smoke operation summary.

The smoke suite checks dashboard, chroot listing, operation history, debug probes, support/module previews and managed transfer artifact visibility without mutating chroots. SDK remains pinned to 36.
