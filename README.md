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
