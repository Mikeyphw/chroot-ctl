# WebUI overlay 6 of 8 — Operations

The Operations section is backed exclusively by the persistent chrootctl operation journal. It lists active and recent records, restores state after WebUI reopen/reconnect, renders determinate or indeterminate progress, exposes stage/bytes/entries/rate/ETA when the backend records them, and shows terminal success/failure details.

Cancellation uses the typed app cancellation endpoint. Retry uses `operations.retry`, which creates a new persistent operation and retains backend retry safety: preview-bound operations are rejected and must return to their owning workflow for a fresh authoritative preview. No operation state is fabricated from browser-local storage.

The UI polls only while the Operations section is visible. Backend failures remain explicit rather than being converted into an empty history.
