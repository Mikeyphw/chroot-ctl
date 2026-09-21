# Standalone WebUI SWUI-03

SWUI-03 makes the loopback WebUI directly usable from the Android browser while preserving the KernelSU bridge as a compatibility transport.

- `action.sh` launches the native backend in the background and opens its one-use bootstrap URL with Android VIEW.
- `chrootctl webui start` / `webui serve --open` can launch the browser directly.
- The bootstrap exchange redirects to authenticated module `webroot/` assets served only by the loopback server.
- The frontend auto-selects authenticated HTTP on `127.0.0.1`/`localhost`, including CSRF headers for mutations; non-HTTP module WebViews retain the KernelSU transport.
- HTTP frontend requests remain constrained to SWUI-02 typed `/api/v1` routes. No shell, exec, or arbitrary argv HTTP endpoint is introduced.
- Legacy read-only UI calls are translated to typed bridge queries in standalone mode. Legacy rename/stop remain explicitly unavailable in standalone mode pending their typed migration rather than falling back to arbitrary command execution.
