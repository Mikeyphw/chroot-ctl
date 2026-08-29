# GO07 — users, catalogs, clipboard, completion, output

GO07 ports user/account management and UID/GID synchronization, the tool/addon
catalog contract, host clipboard bridge primitives, zsh completion data, and
terminal/JSON output helpers. The built-in catalog manifests/scripts are copied
to the top-level `resources/` tree so the eventual Python purge does not remove
the Go backend's catalog assets.

The CLI remains Python-authoritative; GO11 will connect these packages to the
human CLI after services and bridge parity are complete.
