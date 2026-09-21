# Static tmux campaign — full-roadmap four-pass audit

This audit is against the reconstructed post-TMUX-07 repository state (`2bd9296`) and the canonical TMUX-01..TMUX-07 roadmap.

## Audit 1 — architecture and persistence
Found: the implemented default state root was `/data/adb/chrootctl/tmux`, while the roadmap fixed mutable state at `/data/adb/chrootctl/runtime/tmux/`. Corrected the authority and release smoke path. Existing explicit `CHROOTCTL_TMUX_STATE_ROOT` remains supported. Also found that session kill/reconcile did not close the persistent job lifecycle. Kill now records bounded final evidence and `killed`; reconcile also reconciles persistent job metadata.

## Audit 2 — session lifecycle and protocol
Found: “Create / reconnect” attempted a second `new-session` instead of reconnecting to the deterministic existing target+user session. Corrected the service to return an existing managed session. Found that the WebUI terminal was capture-only: there was no terminal input/attach transport. Added structured `sessions.input`, bounded to 8192 bytes, argv-safe literal `tmux send-keys`, app capability metadata, response schema, and WebUI input. No raw tmux or arbitrary shell surface was added.

## Audit 3 — WebUI and recovery semantics
Verified backend-owned discovery, bounded capture, backend-mediated resize, detach/kill, retry/reconnect UI, deterministic IDs, explicit target/user selection, and sanitized environment. Corrected terminal input controls to disable after detach/kill. Persistent job metadata now follows session termination and reconciliation rather than remaining falsely `running`.

## Audit 4 — packaging, release and device evidence
Verified pinned/static AArch64 runtime, manifest/checksum packaging, no PATH-based production tmux execution, source/license documentation, root-module lifecycle integration, timeout/output bounds, and 0700 runtime directories. Expanded the device smoke contract for the canonical `/runtime/tmux` root, UTF-8/TERM/resize evidence, and explicit manual WebUI/manager/update/multi-user phases. Real-device evidence is still evidence-dependent: repository validation must not claim those manual phases passed until they are executed on Android.

The hotfix closes implementation gaps found by these four passes. The remaining item is execution of the real-device evidence checklist, not missing repository implementation.
