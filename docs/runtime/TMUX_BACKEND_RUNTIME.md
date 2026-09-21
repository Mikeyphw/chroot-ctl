# Backend tmux runtime authority

TMUX-02 makes the Go backend the sole authority for the bundled tmux runtime. Production resolution never searches `PATH`: it resolves the module-owned `runtime/arm64-v8a/tmux` (or an explicit absolute `CHROOTCTL_TMUX_PATH` override for controlled development/recovery), alongside its manifest and checksum.

State is rooted at `/data/adb/chrootctl/runtime/tmux` with mode `0700`; sockets live only below `/data/adb/chrootctl/runtime/tmux/sockets`. The namespace defaults to `chrootctl`. These values are resolved together so later session-management code cannot independently invent binary, state, socket, or namespace locations.

`sessions.runtime` exposes a secret-free health model: readiness/status, expected ABI/version, runtime digest, backend-owned state/socket roots, namespace, validation checks, and stale socket basenames. It does not expose environment variables, command lines, credentials, or arbitrary file contents.

Runtime validation rejects missing, symlinked, group/world-writable, non-executable, corrupt, wrong-architecture, wrong-version, or checksum-mismatched runtimes. When privileged, runtime files and state directories must be root-owned. State/socket directories are created or normalized to `0700`.

Socket entries older than 24 hours are surfaced as stale/degraded evidence. TMUX-03 owns active session reconciliation and command transport; TMUX-02 intentionally does not delete sockets merely because they are old.
