# WebUI Rclone — overlay 5 of 8

The Rclone section exposes the existing typed rclone backend without introducing a second transfer engine.

- Reports bundled runtime readiness/version and configured remote names without executable/config paths or credential values.
- Imports a decrypted `rclone.conf` only from backend-managed local staging; the backend validates it, publishes private root-owned configuration, and removes the staged credential copy.
- Browses configured remotes through `remote.rclone.list` using credential-free `rclone://REMOTE/path` locations.
- A selected remote archive is handed to Transfer import with streaming selected; a selected remote directory is converted to a remote export destination and handed to the same Transfer preview/run flow.
- Passwords and rclone credentials are never read from or rendered by the Rclone UI.

Remote directories are selected with one tap/click and opened with double-click; Up and Refresh provide explicit navigation.
