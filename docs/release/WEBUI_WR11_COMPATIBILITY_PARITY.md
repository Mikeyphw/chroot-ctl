# Root-module Android-retirement WR11/12 — Compatibility, parity, and hardening

WR11 is the compatibility/parity gate before Android retirement.

## Runtime contract

- WebUI discovers the live backend through `chrootctl app capabilities`.
- Bridge protocol must be exactly v1. A mismatched or missing protocol blocks privileged UI operation access with a concrete compatibility error.
- A backend advertising arbitrary shell access is rejected.
- Query/preview/run calls are now the intersection of the WebUI allow-list and the backend-advertised operation metadata; unsupported or mode-mismatched operations fail closed.
- The Debug & readiness workspace exposes backend version, protocol, transports, operation count, and the complete advertised operation metadata.
- Major action buttons are capability-gated instead of assuming every backend feature exists.

## Parity matrix

| Android authority | Root-module WebUI authority |
| --- | --- |
| Home/runtime health | Readiness + compatibility |
| Chroot list/detail/lifecycle | Chroots |
| Install/create | Create |
| Users | Users |
| Services | Services |
| Snapshots/storage | Snapshots + Storage |
| Transfer/Rclone | Transfer + Rclone |
| Tools/add-ons/packages | Catalog |
| Operations | Operations |
| Logs/doctor/journal | Logs & diagnostics |
| Repair/support/temp cleanup | Maintenance |
| Debug probes/timeline | Debug & readiness |
| Smoke/release readiness | Debug & readiness |
| Settings/theme/default target | Settings |

All privileged actions remain typed; no arbitrary shell surface is introduced.

## Accessibility/security hardening

The compatibility failure banner uses status/live-region semantics, exposes actionable compatibility text, and disables privileged form controls when the backend contract cannot be trusted. Backend output remains escaped before HTML rendering and operation output limits remain enforced.
