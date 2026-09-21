# WebUI Android-retirement WR04/12 — Services workspace

The KernelSU WebUI now consumes the same typed service contracts as Android.

- Query/detail: `services.list`, `services.journal`.
- Preview: `services.preview`.
- Operations: `services.start`, `services.stop`, `services.restart`, `services.enable`, `services.disable`.
- Service status, boot enablement, description, dependency metadata, and bounded journal access are exposed without raw shell execution.
- Every mutation requires a fresh `previewId`, `payloadHash`, and `resourceRevision`, executes through NDJSON persistent operations, and exposes operation cancellation once an operation ID is available.
- Running-state action selection matches the Android policy (`running`, `active`, `started`, `ok`). Stale/failed state remains visible for diagnosis rather than being treated as healthy running state.
