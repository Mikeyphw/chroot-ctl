# Self-Sustained Native Module Runtime Seal

This release removes the Magisk/KernelSU module's external Python bootstrap path.
The module runtime contract is now:

- `/system/bin/chrootctl` resolves the active module only.
- The launcher executes `runtime/arm64-v8a/chrootctl`.
- The bundled native runtime must validate against `runtime-manifest.json`.
- Pending module update trees are diagnostics only until reboot activation.
- `payload/`, `python.env`, `dependencies.ready.json`, `dependency-mode.env`, and `chrootctl-python-bootstrap` are forbidden module artifacts.

The remaining Python package metadata in the compatibility manifest is an identity
contract for the source package compiled into the native runtime. It is not an
external runtime dependency.
