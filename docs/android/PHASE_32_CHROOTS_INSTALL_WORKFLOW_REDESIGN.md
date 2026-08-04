# Phase 32 — Chroots and install workflow redesign

Phase 32 implements Overlay B from the UI/UX roadmap on top of the landed Phase 30–31 shell.

## Chroots

- Adds a search field covering name, distro, release, architecture, path, status, mount state and health.
- Adds stable filters for all, running, stopped and needs-attention chroots.
- Replaces dense lifecycle entry points with compact chroot cards.
- Keeps details, status, path and health visible without forcing the user into the deep detail panel.
- Uses `ActionFlowRow` for card and detail actions so narrow screens wrap controls instead of crushing labels.
- Exposes preview-first upgrade from the chroot card and detail lifecycle section, with execution routed through the bridge operation that previews again before mutating.
- Keeps typed confirmation for removal.

## Install

- Replaces the single tall install form with a three-step wizard:
  1. choose system
  2. configure essentials
  3. review the exact plan
- Persists wizard step with `rememberSaveable`; field values remain in `MainViewModel` through `InstallDraft`.
- Adds close-to-field validation for distro, chroot name and Linux username.
- Keeps advanced release, version and mirror fields collapsed by default.
- Shows a foreground-operation handoff and routes users to Activity for progress and cancellation.
- Keeps install preview-first: the start button is available only after a successful bridge preview.

## Runtime contract

The Python bridge now registers `chroots.upgrade` as an operation. It previews first through `services.preview().upgrade`, checks cancellation before execution, then runs `services.install().upgrade` with progress callbacks. This avoids showing a dead-end Upgrade button in the new Android card UI.

## Preserved boundaries

- API 36 remains pinned.
- `warningsAsErrors` and `abortOnError` remain enabled.
- Only `OldTargetApi` is ignored.
- No WebView, HTTP server or arbitrary shell execution was introduced.
- Phase 29F Binder recovery remains untouched.


## r2 promise audit corrections

The r2 overlay closes gaps found during an adversarial promise audit of the first Phase 32 artifact:

- Upgrade previews now return an explicit `ok` field, so Android preview cards and `chroots.upgrade` execution are not permanently blocked by a preview shape mismatch.
- The bridge operation also treats missing `ok` defensively as `blocking.isEmpty()`, preventing the same dead-end from returning if the preview schema is extended.
- Compact chroot cards now expose a remove preview entry point; destructive execution still remains behind the detail panel typed-confirmation gate.
- The install wizard now validates the distro on the choose step, blocks progression from Configure until distro/name/username are valid, and removes the inert Continue button from the Review step.
