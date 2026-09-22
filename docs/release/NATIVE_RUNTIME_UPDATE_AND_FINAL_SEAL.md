# Native runtime update and release seal

Runtime updates stage and validate the sealed Go-native runtime before replacing the active artifact. New artifacts use schema 2 / `go-native` and contain the Android arm64 `chrootctl` ELF plus `runtime-manifest.json`.

Current Android resolution and release validation are Go-only and fail closed on missing, unsafe, unsealed, identity-mismatched, Python, or legacy Nuitka runtime artifacts.

`repoctl final-seal` remains the broad source/release audit entrypoint. Runtime release readiness is now sealed separately by the `chrootctl_root_module` Devtool lifecycle as schema-v4 evidence for restore, build, test, lint, and package, then embedded into the module and published by the active installation.
