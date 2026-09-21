# TMUX-07 real-device and release seal

TMUX-07 seals the seven-overlay static tmux campaign. The production runtime remains the pinned static Android/arm64 tmux 3.7c artifact with SHA-256 `c753b02433e55e8d3b75507aa65f11caa63614a09dd66bffa12295dceb1439b6`. The canonical manifest records tmux, libevent and ncurses provenance; the package seal verifies the exact runtime bytes in the module ZIP and rejects dynamic `INTERP`/`NEEDED` entries.

## Device evidence

After installing the built module, run `scripts/tmux/device-release-smoke.sh` as root with `--name <installed-chroot> --user <user>`. It verifies `tmux -V`, 0700 state/socket roots, runtime readiness, create/list/get/capture/detach/reconcile/kill and cleanup. Run it with `--reboot-phase` before a reboot when collecting reboot evidence.

Closing/reopening the WebUI or restarting KernelSU Manager does not own the tmux server: the backend-managed session survives client disconnects. Reconnect is represented by list/get/capture against the same managed session ID. Module update compatibility depends on preserving `/data/adb/chrootctl/runtime/tmux`, which is outside the replaceable module tree.

## Reboot semantics

A device reboot terminates tmux processes. chrootctl does **not** claim tmux sessions survive reboot. Persistent job metadata is reconciled after restart: jobs whose tmux process disappeared become lost/recoverable evidence rather than being falsely reported as running. Stale socket state is reconciled by the backend. This is intentional fail-closed behavior.

## Multi-target and terminal behavior

Managed IDs are deterministic over chroot target plus username, preventing accidental cross-target aliasing. Backend command construction is argv-safe and owns `TERM`/locale forwarding. WebUI resize is mediated through `sessions.capture` dimensions/backend resize rather than raw tmux commands. UTF-8 is carried through locale/terminal data; bounded capture prevents unbounded evidence growth.

## Release criteria

The release seal requires: static ARM64 runtime provenance/checksum, exact ZIP inventory, no unexpected dynamic dependencies, root-module restore/build/test/lint/package green, backend/CLI/app/WebUI boundary tests, persistent-job recovery contracts, mode-0700 state authority, and real-device smoke evidence before an external release is tagged. The repository seal proves the implementation and packaging contract; device smoke is the hardware evidence step and must not be fabricated by host validation.
