# WebUI Android-retirement WR03/12 — Users workspace

The KernelSU WebUI now consumes the same typed user bridge contracts as Android.

- Query: `users.list`, `users.get`.
- Preview: `users.preview`.
- Operations: `users.add`, `users.remove`, `users.sync_uid_gid`, `users.set_shell`, `users.set_sudo`, `users.set_password`.
- Protected/system accounts are rendered read-only from backend policy metadata.
- Remove and password changes require exact username confirmation.
- Password changes require matching password confirmation and scrub secret values after blocked previews, errors, and terminal execution.
- Every mutation requires `previewId`, `payloadHash`, and `resourceRevision` and runs through NDJSON persistent operations.
