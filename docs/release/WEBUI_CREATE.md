# WebUI overlay 3/8 — Create

The Create section is a typed KernelSU WebUI client for the existing chrootctl install contracts. It does not construct shell strings or accept arbitrary executables/argv.

## Backend-driven form

The WebUI requests `install.form` through the versioned `chrootctl app` bridge. Distribution, architecture, preset, profile, desktop and mirror choices therefore come from the backend's authoritative option model. Compatible optional tools and add-ons are loaded from `catalog.tools` and `catalog.addons`. Catalog lookup failure does not block a basic install; it only disables the optional list that failed.

## Review before execution

Submitting the form issues `install.preview`. The normalized request, execution mode, phases, warnings and blocking issues are shown before the Install button is enabled. The preview layer additionally blocks a Create request when the selected name is already registered or its target rootfs already exists without an owner, so the UI cannot report a new-create request as ready when execution would immediately collide.

The action carries the one-use `previewId`, `payloadHash` and `resourceRevision` from the fresh preview into `install.run`.

## Progress, cancellation and retry

`chrootctl app` accepts a bounded `--request-json` argument for query/preview/run requests. This is argv, not a shell command, and the existing protocol parser still validates the JSON shape, protocol version, operation allowlist and payload fields before services are constructed.

Install execution uses `app run --events ndjson`. The UI consumes operation events for phase/message/percent progress and records the operation ID. Cancel calls the existing typed `app cancel OPERATION_ID` endpoint. Retry never reuses a consumed preview: it obtains a fresh preview for the same request and proceeds only if that new preview is still valid.

## Security boundary

The WebUI allowlists only `install.form`, `catalog.tools`, `catalog.addons`, `install.preview`, `install.run`, and operation cancellation for this section. User values are JSON data passed as argv to the fixed bundled chrootctl executable. No `ksu.exec`, `su -c`, `sh -c`, `eval`, dynamic function construction, or remote asset is introduced.

## Audit record

Three implementation audits were performed. The first closed auto-name, cross-architecture guidance, retry-dialog and backend-status regressions. The second closed optional-catalog failure isolation, stale async form responses, double-submit protection and preview/runtime target-collision parity. The third caught and repaired the foundation `OPERATIONS` invariant regression. Static DOM/JS reference checks, JavaScript syntax checks, shell-bridge scans and the module package test pass in the build workspace. Bridge/services runtime tests are included in the overlay validator for the device Devtool environment.
