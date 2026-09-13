# Self-sustained native module runtime seal

The Magisk/KernelSU module has no external Python bootstrap path. The module runtime contract is:

- `/system/bin/chrootctl` resolves the active module runtime;
- the launcher executes `runtime/arm64-v8a/chrootctl`;
- the bundled native runtime must validate against `runtime-manifest.json`;
- pending module update trees are diagnostics only until reboot activation;
- `payload/`, `python.env`, `dependencies.ready.json`, `dependency-mode.env`, and `chrootctl-python-bootstrap` are forbidden module artifacts; and
- configured startup targets are mounted by the module service before `chrootctl run --boot` starts the managed boot target.

Compatibility-manifest schema 3 records generic `backend` and `nativeRuntime` identities. No Python package identity is part of the current release contract.
## CHR15 package/runtime seal

CHR15 adds a package-level manifest at `config/chrootctl/module-package-manifest.json`. The manifest records module identity, backend/runtime schema, startup targets, and a deterministic inventory of every module payload file with size, SHA-256, mode, and executable-bit state. `module.Render`, `module.ValidateRendered`, `module.ValidateZipArchive`, `ModuleRuntimeService.Status`, Android `RuntimeResolver`, `repoctl validate`, and final-seal all consume the same package/runtime contract.

The module archive must pass the package seal before the transfer service registers it as an artifact. Android module-build preview calls the same Go preflight used by CLI/service builds and defaults to all installed targets, so the UI no longer previews or submits an empty target set. Startup targets are accepted only after the registry row and resolved chroot path pass backend authority checks.

Module uninstall owns transient runtime state under `/data/adb/chrootctl` (`control.state`, Android enablement state, clipboard daemon PID/token/identity, and socket files), but intentionally leaves databases, managed chroot roots, snapshots, and user data untouched.

