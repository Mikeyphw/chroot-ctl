# Native runtime update and release seal

Runtime updates stage and validate the sealed Go-native runtime before replacing the active artifact. New artifacts use schema 2 / `go-native` and contain the Android arm64 `chrootctl` ELF plus `runtime-manifest.json`.

Current Android resolution and release validation are Go-only and fail closed on missing, unsafe, unsealed, identity-mismatched, Python, or legacy Nuitka runtime artifacts.

`repoctl final-seal` additionally requires live frozen-contract parity, the GO02 real-device SQLite acceptance gate, Go tests/vet, Android compile/unit/lint gates, deterministic source and module archives, module shell validation, and the retired-WebUI scan before it records schema-v3 release evidence.
