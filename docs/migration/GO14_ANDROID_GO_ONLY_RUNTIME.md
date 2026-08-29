# GO14 — Android Go-only runtime resolution

GO14 removes the final Python execution fallback from the Android companion.

## Runtime policy

- An enabled `chrootctl-magisk` module is authoritative.
- Its runtime must use compatibility schema 3, backend `go`, runtime schema 2, and kind `go-native`.
- Corrupt, disabled-in-place, or incompatible active modules fail closed.
- Pending module updates are diagnostic-only until activation.
- When no module is active, standalone **Go** `chrootctl` executables may be probed from `/system/bin`, `/data/adb/chrootctl/bin`, and Termux development locations.
- Python interpreters, `python -m chrootctl.bridge.cli`, schema-2 Python identity, schema-1 Nuitka runtime identity, and `PYTHONUNBUFFERED` are no longer Android runtime contracts.

Bridge protocol remains version 1. Historical Python manifests remain readable by migration/release tooling where needed, but Android will not execute them.
