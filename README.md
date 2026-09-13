# chrootctl CHR09 validator hotfix v4

This is a corrective overlay for `chrootctl_chr09_metadata_faithful_snapshots_v3.tar.gz`.

It fixes two validation misses found by the repo validator after v3 was applied:

1. `ChrootService.Remove` bypassed the CHR07 unmount indirection (`crudUnmountTarget`) and called the real controller unmount path directly. The CHR07 atomicity tests intentionally replace that hook with a no-op; bypassing it made rootless validation fail with `failed to unmount chroot`.
2. `TestCHR08MountRestoresDataFlags` exercised a fake BusyBox/mount table harness but still hit the real root gate before the fake mount command could run. The controller now routes root checks through a package-local seam, and that one test overrides it while still exercising the real remount/restore command sequence.

The overlay includes its own artifact validator script. Apply it without `--no-validate` when possible so Devtool runs the script, then the script invokes `go run ./cmd/repoctl validate` as the authoritative seal.

## v6 validator harness correction

The CHR08 fake BusyBox test helper now writes its shebang with an absolute
`python3` or `python` path discovered from the active validation environment.
This avoids `/usr/bin/env` assumptions on Termux, where `/usr/bin/env` is not
portable, while preserving the same fake mount-table behavior for Linux hosts.
## Installer and upgrade reconstruction

The Go-native installer now normalizes CLI, bridge, and Android requests through one backend policy. Use `chrootctl install <distro> --resume` to continue a matching install plan, `--repair` to rerun failed or inferred phases, and `--overwrite-existing` only after intentionally approving replacement of an existing rootfs directory. Install preview shows the exact normalized plan before Android or CLI starts `install.run`.

Selected tools/add-ons are part of install completion: finalize records `pending-catalog` until catalog application succeeds, then marks the chroot installed. Upgrade preview rejects incomplete targets and validates distro, registry path identity, runtime prerequisites, and managed pre-upgrade snapshot behavior before package commands run.

## User identity safety

User operations are protected by the CHR12 safety model. `users list` and Android user rows expose sudo, protected/system, mutability, login-shell, and policy-reason metadata. Root and system accounts are read-only. Sudo fragments are canonicalized to `/etc/sudoers.d/<username>` with passwordless rules, while legacy `90-chrootctl-<username>` fragments remain readable and removable for upgrade compatibility.

## Catalog and package workflow safety

CHR13 adds executable catalog state to tools and add-ons. Catalog entries now expose source, script SHA-256, rollback, risks, risk level, destructive intent, confirmation requirement, and target state. `sync-uid` remains documented but is blocked from catalog execution because UID/GID mutation must use the host-managed user service.

External catalog files are read only after parent-directory, symlink, permissions, owner, and stable-read checks. Package inventory responses distinguish total package count from returned package rows and set `truncated=true` when a bridge limit cuts the list. Android catalog screens now use real category filters, installed-target chips, blocked-state rows, and preview-gated apply actions.
### CHR14 clipboard privileged integration

CHR14 makes clipboard integration target-aware and lifecycle-safe: daemon state lives under the Termux-private runtime root, custom control paths must already be private, starts are locked, stale/corrupt PID/socket/token state is cleaned or rejected safely, host `set/get` use the daemon host socket by default, stdin is bounded while preserving trailing newlines, and generated wrappers carry the installing target identity so the daemon can reject requests from targets where clipboard was not enabled.
### CHR15 module/runtime/release trust seal

CHR15 makes module packaging, runtime readiness, Android selection, and release wrappers share one sealed Go-native contract. Rendered modules now carry a full package manifest at `config/chrootctl/module-package-manifest.json`; module ZIPs are validated against that inventory before artifact registration; runtime status and Android runtime resolution fail closed on corrupt package/runtime seals; module-build preview uses the real backend preflight; startup targets resolve through the installed-target path authority; replacement promotion is rollback-capable; uninstall removes transient module state; and the documented production wrappers are executable.

## CHR16 — logging, diagnostics, audit & evidence

Overlay 16 of 20 hardens the diagnostic plane: private/redacted logs, bounded operation/event journals, support bundles as managed tar.gz artifacts, sanitized audit events, correct severity thresholds, follow-mode filtering, and Android import-password clearing after dispatch.

