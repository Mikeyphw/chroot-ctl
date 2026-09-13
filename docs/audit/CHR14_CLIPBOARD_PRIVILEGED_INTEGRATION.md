# CHR14 — Clipboard privileged integration

## Closed findings

- `D28`

## Runtime invariants

- Clipboard control state is rooted in the Termux-private runtime directory (`$PREFIX/tmp/chrootctl`) instead of a root-only Android state directory, so host `daemon start/status/stop`, host `get/set`, and chroot wrappers share one socket/token authority.
- Custom clipboard control paths are no longer silently created and chmodded. The managed control root may be created by chrootctl; custom parents must already exist, be real directories, and be private.
- Daemon starts are serialized with a managed lock file. A corrupt PID/identity pair with a live process fails closed instead of spawning a second daemon.
- `daemon run` refuses to unlink or take over an existing socket. A failed post-spawn PID/identity persistence path terminates the child and removes partial socket/token state.
- `daemon stop` removes stale PID, identity, socket, and token files so future starts do not inherit dead control state.
- The daemon writes internal lifecycle/rejection events to the selected log file and rotates the previous log to `.1` when it exceeds the retention cap.
- Each connection has separated read, host-command, and write deadlines, and the daemon rejects connections beyond its bounded concurrency limit.

## Clipboard request and text fidelity

- Host `clipboard set/get` defaults to the same host socket as `clipboard daemon start` rather than the chroot-view socket path.
- `clipboard set ""` is treated as explicit empty text, while omitted text reads stdin through a 1 MiB bounded reader.
- Chroot wrappers preserve trailing newlines by building JSON from raw slurped stdin instead of shell command substitution.
- Wrapper requests carry the installing chroot target name. The daemon rejects target-scoped requests unless all generated wrapper markers are present for that target, and `clipboard doctor --name <target>` reports target-specific wrapper readiness.

## Gate

`ValidateClipboardPrivilegedIntegration` is wired into repoctl source gates and the final seal. The overlay remains an intermediate `--no-validate` overlay; full release validation is reserved for a later gate overlay.
