# Final validation evidence contract

GO17 release readiness is evidence-driven and Go-native. `repoctl final-seal` is the only supported producer of passing final-validation evidence; it executes the release gates itself and then writes `validation-results.json` atomically with mode `0600`.

Runtime readiness consumes `validation-results.json` from the chrootctl state directory, or the path named by `CHROOTCTL_VALIDATION_RESULTS`.

## Schema v3 and identity

The file uses `schemaVersion: 3` and records:

- `validationRunId` and `generatedAt`;
- optional `sourceCommit` and `sourceTree` when sealing from a Git checkout;
- `compatibilityManifestSha256`, the SHA-256 of `docs/release/compatibility-manifest.json`; and
- the exact required `checks` object.

When a Git checkout is available, `final-seal` refuses to record evidence from a dirty worktree and records the current `HEAD` and `HEAD^{tree}`. Runtime readiness rejects evidence when those recorded identities no longer match the current checkout. Installed runtimes without `.git` are anchored by the compatibility-manifest SHA-256.

## Required checks

The exact check IDs are:

- `go_test`
- `go_vet`
- `go_contracts`
- `repo_purity`
- `source_package`
- `android_compileDebugKotlin`
- `android_testDebugUnitTest`
- `android_lintDebug`
- `module_render`
- `module_zip`
- `module_shell`
- `source_no_webui`

A passing check carries `status: pass`, `exitCode: 0`, a non-empty `command`, a positive `recordedAt`, and provenance of either `subprocess` or `internal-check`. Missing, extra, malformed, or failed checks make release readiness fail closed.

`go_contracts` validates the retained GO16 test map, the frozen GO00 fixtures, and the live 69-node CLI / 86-operation bridge metadata. `source_package` builds the source archive twice and requires identical SHA-256 values. `module_zip` likewise packages the module twice and requires byte-for-byte deterministic ZIP output. The three Android checks execute the exact Gradle tasks rather than accepting caller assertions. `source_no_webui` scans the current runtime source for retired WebUI dependencies/surfaces.

Repository-internal validation also seals the CHR01–CHR03 roadmap foundations before final evidence can pass: build/Devtool configuration, generated CLI-contract freshness, the complete 609→272 audit ledger, and CHR03 configuration/registry/Room identity invariants.

## GO02 device prerequisite

The GO02 SQLite compatibility gate is separate from the 12 schema-v3 checks because it proves a physical execution environment, not a source-tree test. A final seal must either:

- run on Android/arm64, where the acceptance probe executes directly; or
- receive `--go02-evidence <file>` produced by `repoctl go02-device-acceptance --evidence <file>` on a real Android/arm64 device.

The device probe opens a frozen Python-created registry fixture with the Go SQLite layer, verifies the required PRAGMAs/schema/integrity/cascade behavior, mutates it, closes it, reopens it, and verifies the committed Go-written state. Evidence is rejected unless it is a regular non-symlink file with no group/other permissions and the expected frozen-fixture identity/invariants.

## Producer and persistence safety

Use:

```sh
scripts/final-seal --go02-evidence /path/to/go02-evidence.json
```

On Android/arm64 the `--go02-evidence` argument is not required because the probe runs directly. `scripts/release` invokes the same final seal before creating release artifacts, so release packaging cannot bypass these gates.

Evidence is written through a same-directory temporary file, file `fsync`, atomic rename, and mode `0600`. This is an execution/provenance and source-identity seal, not a public-key signature scheme; an actor with arbitrary write access as the evidence owner/root can still replace local bytes outside chrootctl.
