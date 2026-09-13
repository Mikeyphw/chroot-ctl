# CHR12 — User identity safety

Status: implemented as an intermediate overlay. Full release validation is reserved for the next sensible gate overlay.

CHR12 closes the user-management root cause set by making account classification, sudo state, Android previews, and UID/GID synchronization share one explicit safety model.

## Account safety model

- `root`, known system accounts, low UID accounts, and non-login-shell accounts are classified as protected/system and non-mutable.
- `users.list`, `users.show`, `users.show-id`, bridge payloads, and Android user rows now expose `protected`, `system`, `login`, `mutable`, and `policy_reasons` metadata.
- Android no longer treats `root` as a managed user. Protected/system rows can be inspected, but destructive actions show a read-only explanation instead of launching an operation.

## Sudo correctness

- `users list` no longer hardcodes `sudo=false`; it derives sudo from the sudo group and managed sudoers fragments.
- The canonical sudoers fragment is `/etc/sudoers.d/<username>`, matching installer phase inference.
- Newly written fragments are passwordless (`NOPASSWD: ALL`) and legacy `90-chrootctl-<username>` fragments are still recognized and cleaned up.
- Sudo enable writes and validates the sudoers fragment before adding group membership; if group mutation fails, the fragment is rolled back.
- Sudo disable no longer hides `gpasswd` failures behind `|| true`, and sudoers cleanup errors are returned.

## User mutation hardening

- Add/remove/password/shell/sudo/sync operations reject protected/system accounts.
- User creation rolls back the newly created user/group and sudoers fragment if later setup fails.
- Shell changes require an absolute, non-login-blocked, executable shell inside the chroot.
- Password entry preserves leading/trailing spaces, requires exact confirmation, and reports terminal echo suppression failures.

## UID/GID synchronization

- `users sync-id root` and protected/system sync are blocked.
- UID/GID collision checks now fail closed when passwd/group cannot be read.
- Sync uses one guarded chroot script with rollback traps for user/group ID changes and newly created account/group state.
- Ownership repair now uses the captured old identity and updates owned files under the user's home before restoring shared temp/cache ownership.

## Android bridge contract

`users.preview` now accepts confirmation and password preview payload fields, so remove/password previews use the same typed payload shape as execute operations.
