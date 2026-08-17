# Final validation evidence contract

Overlay 10 made release readiness evidence-driven. Overlay 11 seals that contract so a supported recorder path cannot manufacture successful checks and stale evidence cannot remain valid after rollback or source-tree changes.

Runtime readiness consumes `validation-results.json` from the chrootctl state directory, or the path named by `CHROOTCTL_VALIDATION_RESULTS`.

## Schema v2 and source identity

The file uses `schemaVersion: 2` and records:

- `validationRunId`, `validationStartedAt`, and `validationCompletedAt`;
- `sourceCommit`, the source commit (the pre-Overlay-11 Git `HEAD`) whose clean tree Devtool started from, encoded as an exact lowercase 40-hex Git object ID;
- `sourceTree`, the exact `HEAD^{tree}` for that pre-overlay commit, also exact lowercase 40-hex;
- `validatedTree`, an exact lowercase 40-hex Git tree object written from an alternate index populated from the exact tracked plus non-ignored untracked worktree that passed the gates;
- `compatibilityManifestSha256`, an exact lowercase 64-hex SHA-256; and
- a `checks` object containing every required final gate.

The alternate index is disposable. It never stages the user's real index.

Devtool validates the atomic Overlay 11 bundle before creating its single manifest-driven final commit. A Git checkout therefore accepts evidence in only two states:

1. **Validation/pre-commit:** `HEAD == sourceCommit`, `HEAD^{tree} == sourceTree`, and the exact current worktree tree equals `validatedTree`.
2. **Committed seal:** `HEAD^ == sourceCommit`, `HEAD^{tree} == validatedTree`, the recorded `sourceCommit` still resolves to `sourceTree`, and the exact current worktree tree also equals `validatedTree`.

The worktree comparison is unconditional whenever a Git checkout is available. Therefore rollback to the pre-overlay commit, an unrelated commit, a different parent, a changed tracked file, or a new non-ignored untracked file invalidates the evidence. The compatibility-manifest SHA-256 must also match the current source/runtime identity. If no trustworthy current compatibility manifest can be resolved, readiness fails closed instead of silently skipping that identity check.

For an installed runtime without `.git`, the compatibility manifest remains the runtime identity anchor; source-checkout release qualification still requires the exact Git identities above.

## Required checks and provenance

Required check IDs are:

- `python_pytest`
- `python_mypy`
- `python_compileall`
- `android_contract_validators`
- `source_package`
- `android_compileDebugKotlin`
- `android_testDebugUnitTest`
- `android_lintDebug`
- `module_render`
- `module_zip`
- `module_shell`
- `source_no_webui`

A passing check must carry `status: pass`, `exitCode: 0`, non-empty `command`/task provenance, an allowed `provenance` value, and numeric `recordedAt`. Missing or malformed provenance fails closed.

`scripts/final-release-seal.py` is the authoritative evidence producer. It captures the source/worktree identity before validation, executes the Python, source-package, Android source-contract, module, and packaging gates, verifies that the source/worktree tree is unchanged afterward, and only then assembles and atomically persists the evidence itself.

The retired-WebUI check is **not executed twice**: it is the concrete result from `validate-android-phase20-21.py` inside the one-pass sorted Android validator set, and its evidence is marked `deduplicated-subprocess` with that aggregate gate as its source.

Before any Python gate, the seal reads the runtime dependencies plus the `dev` extra directly from `pyproject.toml`, resolves and enforces a temporary root outside the Git checkout before creating anything, creates a temporary virtual environment there, installs those declared requirements into that environment, verifies imports for `pytest`, `mypy`, `pydantic`, `rich`, and `yaml`, and recomputes the exact validated worktree tree before proceeding. This prevents a bare host interpreter with missing project dependencies from producing misleading collection failures while keeping dependency installation out of the repository tree. Failure to create or satisfy that environment fails closed and records no evidence.

The Python regression gate enumerates every `tests/test_*.py` file, verifies the inventory is neither lost nor duplicated, and runs that complete inventory in four deterministic fresh-process partitions. This is intentionally equivalent in scope to the full suite while avoiding process-global/subprocess state leaking from one test family into another; the evidence records the exact four pytest commands that passed. It disables pytest's repository cache, suppresses bytecode writes, and removes only known ignored Python/pytest cache directories before and between partitions; after each partition the exact Overlay 11 Git worktree tree is recomputed and must still match the sealed tree.

The three Android Gradle tasks are manifest-driven on a Devtool bundle apply as an outer transaction gate. The evidence-producing final seal does **not** trust a Devtool environment marker or caller assertion; it independently executes the same exact Gradle task set against the still-verified Overlay 11 worktree before it can assemble Android pass evidence. This deliberate second execution is the evidence provenance boundary and prevents a manual bundle-validator invocation from minting Android passes.

`scripts/record-validation-evidence.py` is now only a hard-fail compatibility shim. Calling it directly fails without writing evidence, and importing it exposes no success payload-builder or evidence-writer API. Successful schema-v2 evidence is assembled only inside the authoritative `scripts/final-release-seal.py` process, after that process has executed and checked every required gate. The final-seal process rejects an incomplete result set, non-pass/nonzero results, invalid provenance, inconsistent timing provenance, ambiguous source/validated tree identity, and non-hex Git/SHA-256 identity fields before persistence.

## Trust boundary

The seal prevents **supported chrootctl tooling paths** from converting caller-supplied "pass" dictionaries into release evidence. The legacy recorder cannot build or write passing evidence, and the authoritative final-seal entry point has no parameter that accepts precomputed pass results; it runs the gates itself. As with any local state file, an actor that already has arbitrary code execution and write access as the evidence owner/root could replace bytes directly outside chrootctl, so this contract is an execution/provenance and source-identity seal rather than a public-key signature scheme.

## Persistence safety

Evidence is external to the repository and is written as a regular non-symlink file with mode `0600`. Direct writes use a same-directory temporary file, file `fsync`, `os.replace`, and a best-effort directory `fsync`. Android root-state fallback rejects symbolic-link path components, uses a root-created same-directory temporary file, then atomically renames it into place and enforces mode `0600`.

Release readiness rejects evidence that grants group/other permissions.

### Android evidence is execution-bound

The three Android evidence checks are never synthesized from a caller-provided “prevalidated” flag or environment marker. The outer Devtool bundle still requires the exact manifest-driven `chrootctl_android` tasks; after those pass, the evidence-producing final seal independently executes the same exact Gradle task set against the still-verified Overlay 11 worktree and records only that concrete subprocess success. Therefore manually invoking the bundle validator cannot skip Android execution and mint Android pass evidence.
