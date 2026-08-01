# ChrootCTL Android release runbook

1. Apply overlays with normal Devtool validation.
2. Confirm SDK 36 remains pinned.
3. Run the real-device smoke suite from Debug Workbench.
4. Persist and export smoke evidence.
5. Generate a support bundle if smoke fails.
6. Check `release.readiness` on Home.
7. Run `final.preflight` and `final.release_seal` before packaging.
8. Confirm the module package contains no retired WebUI artifacts.

The Android app plus Python bridge are the primary UI/control surface. The WebUI remains retired.
