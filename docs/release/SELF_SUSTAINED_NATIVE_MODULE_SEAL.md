# Self-sustained native module runtime seal

The Magisk/KernelSU module has no external Python bootstrap path. The module runtime contract is:

- `/system/bin/chrootctl` resolves the active module runtime;
- the launcher executes `runtime/arm64-v8a/chrootctl`;
- the bundled native runtime must validate against `runtime-manifest.json`;
- pending module update trees are diagnostics only until reboot activation;
- `payload/`, `python.env`, `dependencies.ready.json`, `dependency-mode.env`, and `chrootctl-python-bootstrap` are forbidden module artifacts; and
- configured startup targets are mounted by the module service before `chrootctl run --boot` starts the managed boot target.

Compatibility-manifest schema 3 records generic `backend` and `nativeRuntime` identities. No Python package identity is part of the current release contract.
