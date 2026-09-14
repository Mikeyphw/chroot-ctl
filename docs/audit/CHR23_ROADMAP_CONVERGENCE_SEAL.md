# CHR23 — Roadmap convergence seal

Status: final convergence gate, overlay 23 of 23.

CHR23 is the post-roadmap reconciliation overlay. It exists because the CHR21 Android app seal and CHR22 configuration-cache hotfix were individually valid, but a second audit found that the repository no longer proved the complete CHR01–CHR20 promise set in one gate: CHR20's artifact validator had lost the Go validation leg, CHR01's executable contract still described an older Android aggregate, and CHR16's 16 owned canonical findings were still marked `planned` even though many fixes had landed and several remaining production gaps still needed closure.

`ValidateRoadmapConvergenceSeal` is the executable CHR23 source gate. `repoctl validate` and `repoctl final-seal` both invoke it.

## Converged final gate

`.devtool-artifact/validate.sh` now runs both halves of the release contract:

1. `go run ./cmd/repoctl validate`
2. Android `:chrootctlAndroidAppSeal`
3. Android `:chrootctlAndroidLintConfigurationSeal` replay to prove configuration-cache reuse

The Android app seal remains the authoritative Android aggregate. `chrootctlDebugValidation` remains an internal dependency, not the externally advertised release gate.

## CHR16 closure

All 16 CHR16-owned canonical findings and all 42 of their source manifestations are now closed in `docs/audit/roadmap-coverage.json`.

The convergence implementation adds or seals the missing behavior:

- production audit events for user mutations, service lifecycle mutations, and catalog applies;
- audit actor, target, message, and metadata redaction before persistence;
- redaction at human and JSON CLI error boundaries;
- bounded reverse log-tail reads with exact truncation evidence, severity filtering, 1 MiB line bounds, redaction, I/O error propagation, and symlink rejection;
- bounded service lifecycle log files with private permissions and oversized-file rotation;
- non-overlapping Android live-log refresh jobs;
- transfer-import and user-password review state clearing immediately after dispatch;
- exact audit-coverage enforcement for CHR14 through CHR20, plus a final invariant that no canonical finding remains `planned`.

## Release evidence convergence

The current lint evidence ID is `android_lint_configuration_seal` everywhere in the release evidence/readiness path. The retired `android_lintDebug` ID is rejected by the CHR23 gate.

CI, Devtool, repoctl final-seal, Android release policy, and documentation all name `:chrootctlAndroidAppSeal` as the current Android release gate.

## Regression coverage

CHR23 adds focused regression tests for:

- redaction of title/message/details/hints/action fields in CLI error responses;
- bounded, filtered, redacted log tails with truthful truncation;
- symlink rejection for log reads;
- oversized service lifecycle log rotation;
- Android full-gate wiring, live-log refresh cancellation, password-state clearing, and zero remaining planned roadmap findings.

## Acceptance

The campaign is complete only when the CHR23 Devtool apply reports zero diagnostics and passes the composite Go + Android validation path. A successful Android-only graph is not sufficient for this final convergence seal.
