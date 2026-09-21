# TMUX-03 of 7 — Go session manager

The Go backend owns managed tmux sessions. `internal/tmuxruntime.SessionManager` is the single tmux command-construction authority and invokes the bundled runtime directly with argv-safe arguments; the generic app protocol does not gain raw shell execution in this overlay.

Managed identities are deterministic for `(chroot target, username)` and use the `cc-` namespace. Target and username are also stored as tmux session metadata so list/get results retain their ownership identity. Session creation resolves an installed registered chroot and validated username through the services layer, then uses the existing controller login invocation.

The manager provides list/get/create, detach/kill, bounded capture, resize control, and stale/live reconcile. Subprocesses run with a timeout, bounded captured output, an explicit host environment, the backend-owned socket path, and structured `CommandError` failures. Caller environment cannot replace the tmux binary, socket authority, host PATH, HOME, or namespace.

Reconcile accepts the backend's expected managed-session identity set, returns live sessions, and kills managed sessions that are no longer expected. Unmanaged tmux sessions are ignored by the parser and never adopted into chrootctl state.
