# ChrootCTL Android release runbook

1. Apply overlays with normal Devtool validation.
2. Confirm SDK 36 remains pinned.
3. Run the real-device smoke suite from Debug Workbench with at least one registered chroot when available.
4. Complete the Phase 41–42 manual UI seal: phone portrait/landscape, tablet width when available, 200% font scale, TalkBack/switch traversal, degraded-capability fallback, and RootService reconnect.
5. Persist and export smoke evidence, recording the two manual recovery checks beside it.
6. Generate a support bundle if smoke fails.
7. Check `release.readiness` on Home.
8. Run `final.preflight` and `final.release_seal` before packaging.
9. Confirm the module package contains no retired WebUI artifacts.

The Android app plus Python bridge are the primary UI/control surface. The WebUI remains retired.


### Phase 41–42 audit closure
- Verify restored selected-chroot state re-binds ViewModel/backend selection after recreation.
- Verify capability-gated rooms remain disabled until capabilities are known.
- Treat selected-chroot workspace probe failures as blocking smoke failures when a smoke target exists.
- Record the manual pending count for degraded-protocol and RootService reconnect checks.
