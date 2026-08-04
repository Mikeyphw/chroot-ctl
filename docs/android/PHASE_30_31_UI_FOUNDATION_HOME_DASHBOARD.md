# Phase 30–31: UI Foundation and Home Dashboard

This phase implements Overlay A from the UI/UX roadmap.

## Phase 30 foundation

- shared spacing, layout, status-color, shape, and typography tokens
- adaptive five-destination shell using a bottom bar below 720 dp and a navigation rail at or above 720 dp
- centered content capped at 1180 dp
- 48 dp minimum action targets
- reusable cards, status pills, wrapping action rows, page/section headers, loading states, recoverable errors, and responsive metric cards
- saved destination state across recreation

## Phase 31 Home

- dashboard hero with primary routes to Install, Chroots, and Activity
- runtime/readiness health summary
- running-chroot, active-operation, and warning metrics
- recent activity summary
- loading dashboard rather than an empty spinner page
- initial bootstrap failure with retry and expandable technical details
- cached Home remains visible after refresh failure, with a reconnect banner
- raw Binder/JSON/runtime errors are classified into user-facing messages while preserving technical details behind disclosure

## Preserved boundaries

- compileSdk and targetSdk remain 36
- warningsAsErrors and abortOnError remain enabled
- only OldTargetApi is ignored
- no WebView, HTTP server, arbitrary shell bridge, or widened AIDL boundary
- Phase 29F Binder recovery remains authoritative
- all existing feature destinations remain wired

## Promise audit fix

The r2 audit also reconciles the lint contract that the prior tree only described in prose: `lint.xml` now ignores exactly `OldTargetApi` and no dependency/version advisory issues. The phase validators and tests enforce that promise so strict lint cannot silently drift behind documentation.


## r3 rebase note

This overlay is rebased directly onto the uploaded Phase 29F tree from 2026-08-04. That tree contains Phase 29C/29D/29F validators but not Phase 29E validator files, so the UI foundation is applied without requiring absent Phase 29E-only Help/log/retry APIs. The five existing destinations remain Home, Chroots, Install, Activity, and Tools.
