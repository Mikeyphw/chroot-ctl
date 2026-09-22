# CUX-01 — Product shell and design system

CUX-01 of 7 establishes the chrootctl WebUI overhaul foundation without changing backend contracts.

- Eight stable primary product domains: Home, Chroots, Terminal, Jobs, Transfer, Rclone, Activity, System.
- Existing management workspaces remain reachable from a contextual Tools sheet until later overlays move them into their final hierarchy.
- Phone uses a compact horizontally scrollable navigation surface; wide layouts switch to a persistent navigation rail.
- KernelSU is transport metadata, not product branding. KernelSU and standalone HTTP continue to share the same WebUI.
- Shared spacing, card, hero, pill, navigation, dialog/sheet, focus, reduced-motion and responsive tokens establish the CUX visual system.
- CUX-02 will replace the intentionally lightweight Home foundation and move chroot-scoped workspaces into Chroot detail.

This overlay deliberately does not change bridge operations, HTTP routes, authentication, runtime discovery, or privileged boundaries.
