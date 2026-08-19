# Phase 41–42 — UI quality and real-device smoke seal

## Scope

Overlay I is a stabilization seal for the selected-chroot workspace landed through Phase 40. It does not add a WebView, HTTP server, generic shell surface, or new destructive backend operation. SDK 36 and the privileged RootService architecture remain unchanged.

## Adaptive layout and 200% font scale

The app keeps the existing phone/tablet navigation breakpoints and maximum content width. Phase 41 hardens the shared section header so actions stack below the title at compact widths instead of competing with long text. Workspace action groups remain wrapping `FlowRow`s and are explicit keyboard/focus traversal groups. These rules are validated against the phone portrait, phone landscape, foldable, tablet, and desktop-width release profiles and the 200% font-scale contract.

## Accessibility

Every selected-chroot room exposes a Compose pane title. Mutation review surfaces for snapshots, users, and services expose their own pane title and heading so TalkBack announces the context change. Navigation remains text-labelled, all action controls retain the 48dp minimum target, and action groups are focus groups for keyboard/switch traversal.

## State restoration safety

Safe navigation state remains saveable: launcher query/filter, selected workspace and tab, service/user/log filters, live-tail preference, and harmless Advanced disclosures. When an Activity/process is recreated and the saved workspace name returns before ViewModel selection state, the screen re-binds that workspace once it is present in the loaded chroot list; this restores the backend detail/users/services selection instead of restoring only the visual shell. Mutation review state is deliberately transient: snapshot review identity and restore confirmation, generated snapshot create name, user review, service review, and typed remove confirmation are not restored as executable-looking state after recreation.

## Loading / empty / ready / failure states

Services, Users, Snapshots, Storage, and Logs now derive an explicit `WorkspacePaneState` and render loading, empty, ready, or retryable failure feedback. Advanced exposes the same state contract for its asynchronous diagnostics/support evidence while keeping local chroot lifecycle diagnostics available. Cached content can remain visible with a retryable refresh failure instead of collapsing to an empty screen.

## Lifecycle-aware log polling

The Logs live-tail preference is saveable, but the polling coroutine runs only while the Android lifecycle is at least `STARTED`. Navigating away disposes the Logs composition and cancels the effect. Backgrounding the Activity stops polling; returning to the foreground resumes polling only when the user had live tail enabled.

## Degraded / older bridge capability behavior

Workspace tabs are capability-aware. Overview and Advanced are always available. Capability-gated rooms stay disabled while capabilities are still unknown, preventing a restored Storage/Logs/etc. tab from firing an unsupported request during startup. A restored gated tab is held as pending safe state during that temporary Overview fallback; it is not overwritten until capabilities are known, so it reappears if supported and is sanitized only when the backend truly lacks it. The ViewModel also defers Users/Services refresh side effects until the capability set is known, then refreshes only advertised rooms for the selected chroot. Services, Users, Snapshots, Storage, and Logs require their matching allowlisted query capability. When a connected backend does not advertise a newer room, the tab and Overview shortcut are disabled and a limited-capabilities notice is shown rather than issuing a request that is known to fail. Legacy string capability entries continue to be accepted by `BridgeCapabilities`.

## Real-device smoke seal

The existing read-only smoke plan now includes root-module discovery and safe workspace probes for Services, Users, Snapshots, Storage, Logs, and Advanced using the first registered chroot or an explicitly supplied target. When a target exists, Services/Users/Snapshots/Storage/Logs and Advanced probe failures are blocking instead of advisory warnings. Manual degraded-protocol and RootService reconnect steps remain explicitly reported as pending manual evidence. `smoke.report`, `smoke.last_result`, and final preflight now preserve failed-run truth instead of treating the mere presence of a smoke record as a pass; pending manual checks downgrade preflight to warning until they are completed and recorded in release evidence. Degraded-protocol fallback and RootService reconnect/recovery remain manual Android checks because deliberately breaking protocol/Binder state is not appropriate for the read-only automatic smoke runner. They are still listed in the plan and release checklist so evidence cannot silently omit them.

## Guardrails preserved

- compileSdk = 36 and targetSdk = 36.
- Native Android + privileged RootService architecture.
- Root-module-first runtime resolution.
- RootService stdout/stderr drain hardening.
- Existing bridge-shape adapters.
- No WebView, HTTP server, or arbitrary-shell capability.
- Phase 37 Services, Phase 38 Users, and Phase 39–40 recovery/storage/logs/advanced behavior remain in place.
