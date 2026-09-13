# CHR15 — Module/runtime/release trust seal

## Scope

CHR15 closes the module packaging and runtime trust findings assigned to the module/runtime/release cluster. The overlay turns the Magisk/KernelSU module output into a sealed package instead of a loose directory snapshot: render, ZIP, Android runtime resolution, Go module status, service build, repoctl validation, and release wrappers now use the same package/runtime invariants.

## Implemented invariants

- Rendered modules include `config/chrootctl/module-package-manifest.json`, a deterministic SHA-256/size/mode inventory for every payload file except the manifest itself.
- `ValidateRendered()` verifies the complete package manifest, required files, startup target manifest, native runtime manifest, runtime ELF identity, and allowed Android dynamic-library dependencies.
- `ValidateZipArchive()` verifies ZIP path safety, duplicate/symlink rejection, mode/checksum inventory fidelity, and the same package seal before module archives are registered.
- Runtime status fails closed when an active module has corrupt layout, invalid package seal, stale compatibility identity, or an invalid native runtime.
- Android runtime resolution requires both compatibility manifest readiness and module package seal readiness before selecting `/data/adb/modules/chrootctl-magisk/system/bin/chrootctl`.
- Module build preview now uses the real builder preflight, reports startup-target and runtime blockers, and defaults Android module-build requests to all installed targets instead of an empty target set.
- Startup target resolution is shared by CLI/service build paths and validates installed registry rows through the same path authority used by the backend resolver.
- Repo/runtime directory replacement uses rollback-capable promotion rather than deleting the old artifact before the new one is safely promoted.
- Module uninstall owns transient `/data/adb/chrootctl` state files such as lifecycle state, Android enablement state, daemon PID/token/identity, and the clipboard socket without deleting databases or chroot data.
- `scripts/repoctl`, `scripts/release`, and `scripts/final-seal` are executable so documented production entrypoints are runnable from a checked-out source tree.

## Closed canonical findings

- D27
- U190
- U191
- U192
- U193
- U194
- U195
- U196
- U197
- U198
- U199
- U200
- U201

## Validation hook

`ValidateModuleRuntimeReleaseTrust(root)` is wired into `repoctl validate` and final-seal after CHR14. It checks the source tokens, package/runtime seal wiring, Android parity, executable wrapper modes, roadmap closure, and this audit document so CHR15 cannot regress into prose-only coverage.
