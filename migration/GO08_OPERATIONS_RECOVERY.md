# GO08 — Persistent operations, locking, cancellation, recovery

The Go backend now owns the operation journal compatibility layer.

Implemented contracts:
- schema version 2 records with schema-1/camelCase/snake_case compatibility;
- atomic record writes and bounded JSONL event journals;
- request/progress/result redaction before persistence;
- global and target advisory locks with blocking operation IDs;
- persistent cancellation markers and verified child/host process signalling;
- explicit, non-mutating-read stale operation reconciliation;
- cancel-vs-interrupt recovery semantics;
- corruption placeholders which fail closed and request repair.

Production bridge routing remains Python-authoritative until GO10.
