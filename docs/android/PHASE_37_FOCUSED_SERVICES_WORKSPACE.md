# Phase 37: Focused Services Workspace

Phase 37 keeps the Phase 35-36 chroot workspace shell and redesigns the Services tab into a focused service-management workspace.

## Delivered

- Service filters: All, Running, Enabled, Needs attention and Failed. Needs attention is driven by stale/failure/error/degraded signals, not by merely opening a journal.
- Compact service rows with status, enabled/disabled, boot and needs-attention badges.
- Journal remains a direct read-only row action.
- Start/Stop, Restart and Enable/Disable no longer render duplicate permanent Preview buttons.
- Service actions open a review sheet.
- Preview and execution now live inside the review sheet as deliberate steps.
- Empty and no-match states are explicit.

## Guardrails

- Top-level Chroots remains a workspace launcher.
- Dedicated Users, Snapshots and Advanced workspace tabs remain in place.
- No WebView, HTTP server or arbitrary shell bridge is introduced.
- Bridge shape adapter from Phase 35-36 is preserved.
- Destructive or mutating service actions do not execute directly from service rows.
## R3 rebase note

The 2026-08-07 12:45 uploaded repository snapshot already contained the Phase 37 r2 service workspace output. The r3 overlay is therefore a source-hash rebase and acceptance seal for that current tree: it preserves the focused Services UI, the explicit needs-attention matching, and the review-sheet action flow while changing only this note.

