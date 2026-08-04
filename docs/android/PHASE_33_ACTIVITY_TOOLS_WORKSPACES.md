# Phase 33: Activity recovery center and focused Tools workspaces

Phase 33 turns Activity into the recovery center and splits Tools into focused workspaces. It remains inside the native Android shell from Phases 30–31 and the workflow model from Phase 32.

## Activity recovery center

- Adds running, failed and completed filters.
- Keeps operation progress and event timelines visible.
- Adds in-screen cancellation for active operation records.
- Adds manual retry and install-specific retry-with-fixes actions.
- Routes snapshot recovery from a failed operation back to the target chroot detail so snapshot restore still uses the existing typed confirmation path.
- Shows a retry preview dialog explaining that the bridge must reject stored requests containing redacted secrets.

## Focused Tools workspaces

Tools is now a workspace selector instead of one long mixed form. Workspaces are Catalog, Packages, Transfer, Runtime, Logs, Repair and Help.

- Logs uses bounded three-second polling while live tail is enabled and stops automatically when the workspace leaves composition.
- Repair loads explicit registry repair items, lets the user select exact item IDs, previews selected decisions and applies only those decisions.
- Help provides native recovery guidance and the runtime capability groups that replace the retired WebUI API page.

## Boundaries

- `compileSdk` and `targetSdk` remain 36.
- `warningsAsErrors` and `abortOnError` remain enabled.
- `lint.xml` ignores only `OldTargetApi`.
- No WebView or HTTP server is introduced.
- Retry is manual and guarded by the bridge redaction check. Mutating work is never replayed automatically.


## Promise audit r2

The merged r2 overlay closes the audit gaps found after the first merged C+D artifact:

- Retry and retry-with-fixes are preview-first from the Activity UI; the card no longer exposes a direct retry button that bypasses the redaction explanation.
- Snapshot recovery from Activity now refreshes the target chroot snapshots before navigating to the Chroot detail recovery panel.
- Registry repair execution now rejects missing or empty decisions instead of manufacturing an implicit repair plan.
- Retry mode is validated explicitly and redaction detection recognizes `<redacted>`, `[redacted]`, and bare `redacted` sentinels.
- Activity and Tools action controls carry explicit 48 dp minimum target modifiers in addition to the shared release policy.
