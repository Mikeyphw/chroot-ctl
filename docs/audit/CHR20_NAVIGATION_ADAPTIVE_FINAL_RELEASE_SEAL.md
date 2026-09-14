# CHR20 — Navigation, adaptive UI & final release seal

CHR20 closes the remaining Android shell/adaptive/accessibility and final-gate findings from the audit ledger.

## Closure

- Replaced the single destination string with an explicit destination back stack sealed by `NavigationReleasePolicy`.
- Integrated system Back/predictive Back through `BackHandler` so secondary destinations pop before the Activity exits.
- Gated notification operation deep links behind a proven operation snapshot; stale or unknown operation IDs wait for refresh instead of replaying navigation after recreation.
- Stopped eager startup of off-screen privileged domains. Install and Tools warm up only when their destination is opened.
- Made adaptive navigation height and font-scale aware so short landscape and 200% type do not force a rail.
- Kept compact navigation labels visible at large font scale.
- Added live-region semantics for dynamic status pills and selected-state semantics helpers for custom controls.
- Cleared restored workspace names when the referenced chroot no longer exists.
- Made the final gate executable through `.devtool-artifact/validate.sh`, `repoctl validate`, and Android `:chrootctlAndroidAppSeal`.

## Executable proof

- `ValidateNavigationAdaptiveFinalReleaseSeal` source gate checks the runtime policy, Android wiring, final gate script, roadmap closure, and audit documentation.
- `NavigationReleasePolicyChr20Test` proves back-stack sanitation/pop/push behavior, deep-link proof gating, height/font-scale adaptive navigation, and removed workspace restore behavior.
- `ReleaseUxPolicyTest` now requires the CHR20 seal checks, final-gate command list, and Android instrumentation checklist.

## Final gate

CHR20 is a gate overlay. Unlike the CHR11–CHR19 intermediate overlays, the apply command should run validation. The validator runs contract generation, CHR20 source-gate tests, `repoctl validate`, and Android `:chrootctlAndroidAppSeal` when the Gradle wrapper is present.

## v3 gate hotfix

The v3 gate rebuild fixes validation regressions outside the navigation code path. CHR13 external catalog trust now allows Android system ancestors such as `/data/data` only while walking parent chains under an app-private Termux tree; configured manifest and script directories still require private owner/mode checks. CHR15 module runtime tests now bypass the modern registry writer only for the corrupt legacy-row fixture, preserving the production fail-closed module startup-target path assertion.
