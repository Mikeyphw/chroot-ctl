# Root-module Android-retirement WR10/12 — Debug, smoke, readiness

WR10 moves Android's remaining debug/smoke/release-health workflow into the root-module WebUI.

- Debug probes are typed and group-filterable (`all`, `runtime`, `host`); audit timeline is a separate typed feed.
- Debug evidence is a managed sanitized support artifact; no arbitrary output path is accepted by WebUI.
- Smoke execution is read-only and requires an exact fresh `smoke.preview` before `smoke.run`.
- The exact backend step plan is rendered before Run; streaming progress and persistent-operation cancellation remain available.
- Latest smoke result/report semantics remain typed. Persist/export controls require an actual result; failure bundle is enabled only for a non-success result.
- Release readiness renders the backend evidence/check ledger rather than inventing a WebUI-only health verdict.
