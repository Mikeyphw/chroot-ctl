# GO13 generic backend identity

GO13 introduces compatibility-manifest schema 3. The current backend is `implementation: go`, version `0.11.0`, and the native runtime identity is schema 2 / `go-native` / Android / arm64-v8a / `chrootctl`.

Bridge protocol remains version 1. Runtime resolution accepts compatibility schema 2 only as an explicit migration fallback for an already-installed module. New module builds always emit schema 3.
