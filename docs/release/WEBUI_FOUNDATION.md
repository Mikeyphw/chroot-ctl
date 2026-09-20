# KernelSU WebUI foundation

Roadmap status: **overlay 1 of 8**.

The module WebUI is packaged under `webroot/` and is hosted by a KernelSU-compatible module manager. It does not run an HTTP server and does not add a second privileged backend. The UI talks to the existing `chrootctl` Go backend through the manager's process-spawn bridge.

## Security boundary

The foundation intentionally has no generic shell helper. `webroot/kernelsu.js` exposes process spawning only. `webroot/chrootctl.js` maps named UI operations to fixed executable paths and fixed argument arrays. The public `invoke()` API accepts an allow-listed operation name, not arbitrary argv or shell text.

Overlay 1 exposes only the read-only `version` probe. Later functional overlays extend the allow-list with section-specific operations and validation. Commands such as `exec` are not implicitly available just because the backend supports them.

Backend responses use the versioned `--json` envelope. The WebUI checks `schema_version`, `command`, `ok`, and process exit status before rendering data. Output collection is bounded to 1 MiB per stream. Backend-derived text is assigned through DOM `textContent` rather than HTML injection.

The page ships a restrictive Content Security Policy and loads no network/CDN assets.

## Packaged assets

- `webroot/index.html`
- `webroot/index.css`
- `webroot/index.js`
- `webroot/kernelsu.js`
- `webroot/chrootctl.js`

These files are embedded in the Go module renderer, written as regular `0644` files, included in the module package manifest, required by rendered-module validation, and therefore sealed by ZIP validation.

## Section roadmap

1. Foundation (this overlay)
2. Chroots
3. Create
4. Transfer
5. Rclone
6. Operations
7. Logs & diagnostics
8. Settings + final convergence
