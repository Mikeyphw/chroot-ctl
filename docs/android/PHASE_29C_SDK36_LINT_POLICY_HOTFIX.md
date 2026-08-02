# Phase 29C: SDK 36 lint policy hotfix

## Scope

SDK 36 remains pinned for both `compileSdk` and `targetSdk`. The project deliberately retains this compatibility contract instead of following the moving "latest target" advisory.

The app keeps `warningsAsErrors = true`, `abortOnError = true`, release lint checks, and the existing `lint.xml` configuration. Only the `OldTargetApi` advisory is ignored in `lint.xml`.

## Guardrails

- No SDK level is changed.
- No warning is globally demoted.
- No wildcard lint suppression is introduced.
- No other lint issue is newly ignored.
- Build, unit-test, manifest, resource, security, storage, bridge, and architecture checks remain unchanged.
