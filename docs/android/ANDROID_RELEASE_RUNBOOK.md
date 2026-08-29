# ChrootCTL Android release runbook

1. Apply source changes with normal Devtool validation.
2. Confirm SDK 36 remains pinned.
3. Run the real-device smoke suite from Debug Workbench with at least one registered chroot when available.
4. Complete the Phase 41–42 manual UI seal: phone portrait/landscape, tablet width when available, 200% font scale, TalkBack/switch traversal, degraded-capability fallback, and RootService reconnect.
5. Run the GO02 real Android/arm64 SQLite acceptance gate and preserve its evidence when the final seal will run on another host:
   `scripts/repoctl go02-device-acceptance --evidence /path/to/go02-evidence.json`.
6. Generate a support bundle if smoke fails.
7. Run `scripts/final-seal --go02-evidence /path/to/go02-evidence.json` (the evidence argument is unnecessary when the seal itself runs on Android/arm64).
8. Confirm `release.readiness` and `final.preflight` report ready from the schema-v3 evidence produced by that seal.
9. Package through `scripts/release`, which reuses the authoritative final-seal gate.
10. Confirm the module package contains no retired WebUI or Python/Nuitka runtime artifacts.

The Android app plus the Go protocol-v1 bridge are the primary UI/control surface. The WebUI remains retired.

### Phase 41–42 audit closure

- Verify restored selected-chroot state re-binds ViewModel/backend selection after recreation.
- Verify capability-gated rooms remain disabled until capabilities are known.
- Treat selected-chroot workspace probe failures as blocking smoke failures when a smoke target exists.
- Record the manual pending count for degraded-protocol and RootService reconnect checks.
