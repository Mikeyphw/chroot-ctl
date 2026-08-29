# GO05 system runner and low-level host primitives

GO05 ports the process/host boundary used by controllers and operations.

## Safety invariants

- Every managed subprocess starts in a separate process group.
- A persisted process identity is signal-safe only when PID, PGID, Linux
  `/proc/<pid>/stat` start time and kernel boot ID all still match.
- Legacy identities missing start-time or boot-ID data are never signalled.
- Timeout and cancellation terminate the managed process group, escalating to
  SIGKILL only after the grace period.
- Chroot environments strip host loader, Python, Termux, Android storage and
  temporary-directory variables before applying deterministic defaults.
- Captured output is bounded with head/tail preservation rather than unbounded
  in-memory pipes.
- Spawn log files use `O_NOFOLLOW`, close-on-exec and mode 0600.

## Portability

`internal/system` is stdlib-only and compiles with
`CGO_ENABLED=0 GOOS=android GOARCH=arm64`. SQLite remains isolated in GO04.
