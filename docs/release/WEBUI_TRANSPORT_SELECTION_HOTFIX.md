# WebUI transport-selection hotfix

Real-device evidence showed `WEBUI_HTTP_ERROR` after the common frontend parser repair.
KernelSU/MMRL hosts can serve module assets from a loopback HTTP origin, so a localhost
hostname is not sufficient evidence that the frontend is running under chrootctl's
standalone server.

The frontend now prefers the KernelSU bridge when that bridge is actually present.
Only an ordinary loopback browser page without a KernelSU bridge selects standalone
HTTP. Standalone API URLs are resolved explicitly against the page's current origin,
so they cannot retain a stale bootstrap port or cross into a different localhost host.
