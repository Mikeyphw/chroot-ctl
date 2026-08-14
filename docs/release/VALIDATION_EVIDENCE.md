# Final validation evidence contract

Overlay 10 makes release readiness evidence-driven. Runtime readiness consumes `validation-results.json` from the chrootctl state directory, or the path named by `CHROOTCTL_VALIDATION_RESULTS`.

The file uses `schemaVersion: 1`, numeric `generatedAt`, non-empty `sourceCommit`, `compatibilityManifestSha256`, and a `checks` object. When chrootctl runs from a Git checkout it rejects evidence from another HEAD; when a release compatibility manifest is available it also rejects evidence bound to a different manifest hash. Required check IDs are:

- `python_pytest`
- `python_mypy`
- `python_compileall`
- `source_package`
- `android_compileDebugKotlin`
- `android_testDebugUnitTest`
- `android_lintDebug`
- `module_render`
- `module_zip`
- `module_shell`
- `source_no_webui`

Each check records `status` (`pass`, `fail`, `warn`, or `pending`), `detail`, the executed `command` when applicable, and `recordedAt`. A `pass` without `recordedAt` is rejected as invalid evidence. Missing evidence is `pending`; it is never synthesized as a pass. Overlay 11 is responsible for executing the final gates and recording their actual results, source commit, and compatibility-manifest hash.
