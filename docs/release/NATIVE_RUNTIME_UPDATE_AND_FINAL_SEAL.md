# Native runtime update and release seal

Runtime updates stage and validate the sealed Go-native runtime before replacing the active artifact. New artifacts use schema 2 / `go-native` and contain the Android arm64 `chrootctl` ELF plus `runtime-manifest.json`.

Final release checks fail closed on missing, unsafe, unsealed, or identity-mismatched runtime artifacts. Legacy schema-1 `nuitka-onefile` manifests remain readable only for migration diagnostics and are not produced by current builds.
