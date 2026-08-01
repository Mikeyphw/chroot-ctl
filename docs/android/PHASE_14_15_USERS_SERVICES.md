# Phase 14-15 · Native Users and Services

Phase 14 replaces the WebUI user-management surface with native Android bridge contracts and Compose panels. Phase 15 does the same for chroot-bound service units.

## Phase 14 · Users

Bridge contracts added:

- `users.list`
- `users.get`
- `users.preview`
- `users.add`
- `users.remove`
- `users.sync_uid_gid`
- `users.set_shell`
- `users.set_sudo`
- `users.set_password`

Android UI added inside the chroot detail screen:

- users refresh panel
- add-user form with shell and sudo selection
- UID/GID sync action
- shell update action
- sudo enable/disable action
- password action with typed username confirmation
- remove-user action with typed username confirmation

Password payloads are redacted by the operation journal through the bridge redaction layer. UI values are used only to start immediate operations and are not added to Room entities.

## Phase 15 · Services

Bridge contracts added:

- `services.list`
- `services.get`
- `services.preview`
- `services.start`
- `services.stop`
- `services.restart`
- `services.enable`
- `services.disable`

Android UI added inside the chroot detail screen:

- services refresh panel
- service status cards
- journal detail loader
- start/stop/restart controls
- enable/disable controls
- preview action before each mutation

## Guardrails

- SDK remains pinned to 36.
- No WebView is introduced.
- No arbitrary shell AIDL method is introduced.
- No broad storage or package-query permission is introduced.
- Kotlin avoids fragile `combine(arrayOf(...))` inference.
- Kotlin avoids direct `Manifest.permission.POST_NOTIFICATIONS` references.
- Kotlin root paths are composed from `File` parts instead of hardcoded `/data/` literals.
