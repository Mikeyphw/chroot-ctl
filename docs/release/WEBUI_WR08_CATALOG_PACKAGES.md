# WebUI Android-retirement WR08/12 — Catalog and packages

WR08 brings the Android Tools/Catalog and package-inspection workflows to WebUI.

- Catalog search is target-aware and supports tools/add-ons, query, and category filters.
- Rows expose backend state, installed state, risk level, destructive intent, rollback, source, risk text, and backend block reasons.
- Apply requires `catalog.preview` and all three proof fields before `catalog.apply`.
- Persistent catalog operations expose cancellation and refresh authoritative state after success.
- Package inventory preserves total count, returned rows, limit/truncation semantics.
- Package comparison exposes counts, common count, and left/right differences.
- No raw package-manager or arbitrary catalog script execution is exposed by WebUI.
