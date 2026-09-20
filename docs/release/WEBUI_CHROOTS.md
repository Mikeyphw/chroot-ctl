# WebUI overlay 2/8 — Chroots

The Chroots section lists registered environments and projects lifecycle state without parsing human CLI output. The WebUI bridge remains allow-listed: names are validated against a conservative identifier grammar and the UI cannot supply executable paths, flags, or arbitrary argv.

Delivered surfaces: registered chroot cards; running/stopped/partial state; distro, architecture, profile, user and registered-path metadata; structured details; start/mount; stop/unmount; restart as an explicit unmount+mount sequence (never an attached interactive shell); rename; typed-name-confirmed removal; and refresh after terminal mutations.

Destructive removal requires an exact typed identity and displays the registered filesystem path before execution. Lifecycle controls are state-aware. Partial mount state is not flattened into stopped/running. Backend failures are retained as explicit errors rather than being rendered as an authoritative empty list.

Later roadmap sections remain inert placeholders. Overlay 3 adds Create; 4 Transfer; 5 Rclone; 6 Operations; 7 Logs/diagnostics; 8 Settings and final convergence.

Audit hardening: card-detail enrichment failures are preserved as non-authoritative state, the Details dialog refreshes lifecycle status directly, and lifecycle controls are hidden when mount state is unknown/unavailable. Partial state exposes teardown only, so recovery can unmount without falsely offering Start/Restart.
