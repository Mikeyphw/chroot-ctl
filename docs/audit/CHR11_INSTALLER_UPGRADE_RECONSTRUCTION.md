# CHR11 — Installer & upgrade reconstruction

CHR11 closes the installer/upgrade bug-hunt tranche by making the Go backend the authority for install options, install plan semantics, and upgrade preflight. The Android wizard now consumes backend option IDs instead of stale fallbacks, and both CLI and bridge payloads carry explicit recovery/overwrite decisions.

## Implemented behavior

- **Android form parity:** `install.form` returns authoritative distro, architecture, preset, profile, desktop, and mirror options. The Android parser prefers option `id` over display labels, so button selections send backend IDs such as `ubuntu`, `arch`, `dev`, `xfce4`, and `plasma` rather than UI labels or stale aliases.
- **Safe request normalization:** install preview uses one normalized shape for CLI, bridge, and Android. Presets resolve to exact profile/desktop combinations, unsupported `debian`, `developer`, `xfce`, and `lxqt` fallbacks are rejected, and Arch exposes only the `arm64` rootfs architecture.
- **Installer state reconstruction:** install transactions seed a registry record before the first extract step, emit phase progress on boundaries/substeps, use request-context checks for resume, and run repair from observed/failed phase state. Existing unmanaged rootfs directories are blocked unless the request explicitly carries `overwrite_existing`/`--overwrite-existing` or is a repair/resume path.
- **Production download/fetch wiring:** distro installers continue to receive concrete `curl` fetch/download implementations from the factory, with Ubuntu release discovery and Arch rootfs download isolated behind explicit installer functions.
- **Package/locale/hooks:** extra packages are validated against a package-name allowlist and shell-quoted before package manager calls. Finalize applies configured locale and post-install hooks as recorded substeps.
- **Install completion semantics:** when tools or add-ons are selected, finalize records `pending-catalog`; the registry is marked installed only after all selected catalog entries complete successfully.
- **Upgrade preflight:** upgrade preview and execution reject incomplete chroots, unsupported/corrupt distro values, registry/runtime path mismatches, missing target identity, and foreign-architecture execution gaps. Upgrade mounts runtime prerequisites and uses the managed snapshot service before package commands when destructive snapshots are configured.

## Gate

`repoctl validate` now invokes `ValidateInstallerUpgradeReconstruction`, and the final seal includes the CHR11 source gate after CHR10. This gate checks the installer policy, request normalization, Android form wiring, CLI/bridge contracts, upgrade preflight, and CHR11 coverage ledger.
