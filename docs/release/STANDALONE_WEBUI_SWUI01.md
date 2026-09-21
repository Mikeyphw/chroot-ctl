# SWUI-01 — standalone WebUI server/security foundation

The standalone transport binds only to IPv4 loopback on an ephemeral port. A 256-bit one-time bootstrap token is exchanged for a short-lived HttpOnly SameSite=Strict session cookie. Bootstrap tokens are invalid after first use. Mutating authenticated routes require a double-submit CSRF token plus same-origin validation.

The server applies Host validation, no-store, CSP/frame/referrer/MIME protections, request/header/time bounds and idle shutdown. It intentionally exposes only authenticated `/api/v1/health` in SWUI-01. There is no shell, exec, argv, root-RPC, or business-operation HTTP endpoint. Typed backend mapping arrives in SWUI-02.

`chrootctl webui serve` starts the loopback authority and prints the bootstrap URL; `--json` emits machine-readable startup information. Browser opening and module Action integration are reserved for SWUI-03.
