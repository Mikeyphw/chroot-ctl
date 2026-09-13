# CHR17 — Bridge protocol V2 convergence

Overlay 17 of 20 closes the bridge/API convergence findings without changing the existing protocol-v1 request envelope. The "V2" work is a response-shape convergence layer: operation capabilities now expose response metadata and the backend returns Android-ready object wrappers for diagnostic/reporting surfaces that previously drifted.

## Implemented scope

- Added a bridge response-schema registry with response kind, response fields, capability tags, and preview requirements.
- Extended live capabilities and `ContractSpecs()` so Android and repoctl see the same response-shape metadata.
- Wrapped `debug.timeline` as `{schemaVersion, events, count, limit}` instead of a bare array.
- Normalized debug probe rows with stable `code`, `status`, `detail`, `next`, and raw `result` payloads.
- Added schema/version/status/count metadata to smoke plan/report/last-result responses.
- Preserved smoke failure recovery guidance instead of mapping the result through generic preview text.
- Extended Android capability models to retain response fields/tags and preview requirements.
- Extended Android envelope parsing to preserve structured error details.
- Added Android smoke/debug mappers that keep report/result/probe data distinct from generic previews.

## Source gates

`repoctl validate` now calls `ValidateBridgeProtocolV2Convergence(root)`. The gate asserts that backend schemas, capabilities, Android models/mappers, the CHR17 audit doc, and the coverage ledger remain present.

## Focused checks

```bash
go test ./internal/bridge ./internal/repoctl -run 'CHR17|BridgeProtocolV2|ResponseSchema|Timeline' -count=1
go test ./... -run '^$' -count=1
```

Full validation remains deferred to a gate overlay per roadmap policy.
