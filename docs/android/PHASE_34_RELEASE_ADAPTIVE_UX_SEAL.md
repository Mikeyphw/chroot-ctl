# Phase 34 — Release adaptive UX seal

Phase 34 completes Overlay D on top of Overlay C and is delivered as a merged Phase 33+34 overlay because Phase 33 was intentionally not applied separately.

## Scope

- Preserve API 36, strict lint, and the Phase 29F Binder recovery contract.
- Keep the native-only boundary: no WebView, no HTTP server, no arbitrary shell bridge.
- Cover five release layout profiles: phone portrait, phone landscape, foldable, tablet, and desktop-width.
- Keep bottom navigation on compact phones and rail navigation on foldable/tablet/desktop widths.
- Cap large-screen content at 1180 dp so forms do not become runway-wide.
- Require 48 dp touch target policy and 200 percent font scale support.
- Attach a pane title to every primary destination so TalkBack announces destination changes.
- Preserve Phase 33 Activity recovery and Tools workspaces, including explicit repair decisions and bounded live-log polling.

## Acceptance gates

1. Route-by-route native parity remains present for Home, Chroots, Install, Activity, and Tools.
2. Every release profile has a deterministic navigation policy.
3. Action groups wrap and reserve at least a 48 dp interactive band.
4. The release seal rejects SDK drift, extra lint suppressions, WebView/HTTP regressions, unbounded log polling, and automatic mutating replay.
5. The merged overlay validates Phase 29, 29C, 29D, 29F, 30–31, 32, 33, and 34 contracts.


## Promise audit r2

The merged r2 overlay closes the audit gaps found after the first merged C+D artifact:

- Retry and retry-with-fixes are preview-first from the Activity UI; the card no longer exposes a direct retry button that bypasses the redaction explanation.
- Snapshot recovery from Activity now refreshes the target chroot snapshots before navigating to the Chroot detail recovery panel.
- Registry repair execution now rejects missing or empty decisions instead of manufacturing an implicit repair plan.
- Retry mode is validated explicitly and redaction detection recognizes `<redacted>`, `[redacted]`, and bare `redacted` sentinels.
- Activity and Tools action controls carry explicit 48 dp minimum target modifiers in addition to the shared release policy.
