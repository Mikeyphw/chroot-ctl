# Phase 38: Focused Users Workspace

Phase 38 keeps the Phase 35-36 selected-chroot workspace and the Phase 37 Services workspace intact while turning Users into a focused account-management room.

## Delivered

- The default Users filter is **Managed**. Normal UID 1000+ login accounts and the intentionally special `root` account remain visible.
- System accounts are conservatively detected from known daemon names, explicit no-login shells, or UID values below 1000. `root` is the explicit exception so privileged recovery access is never silently hidden.
- System accounts are collapsed by default behind **Show N system users** and can also be reached through the **System users** filter.
- **Login users** provides a focused login-capable view without turning `/etc/passwd` into the page layout.
- Each visible user is a compact row with identity metadata, useful badges, and one **Review actions** entry point.
- Add user is a separate **Add user** review flow. Global username/shell/password fields are removed from the Users page.
- Set shell, sudo toggle, UID/GID sync, password, and remove are selected inside the review sheet. Preview and execution callbacks live in that sheet rather than in every user row.
- Password and remove stay exact-username-confirmation protected. Password submission additionally requires non-empty matching values, and password fields use obscured visual transformation.
- Remove keeps `deleteHome=false`, preserving the existing conservative destructive-action default.

## Classification policy

`UserWorkspaceFilter.Managed` intentionally means “human-relevant by default,” not “all entries parsed from `/etc/passwd`.” An account is collapsed as system when it is a known system username, explicitly has a no-login shell, or has a numeric UID below 1000. `root` is kept visible as a deliberate recovery/administration exception.

The classifier is UI-only. It does not change backend account semantics or mutate bridge payloads.

## Guardrails preserved

- Top-level Chroots remains a workspace launcher.
- Workspace tabs remain Overview, Services, Users, Snapshots, Advanced.
- Phase 37 focused Services filters, attention matching, journal action, and review-sheet flow remain present.
- Phase 35-36 bridge-shape adapters remain present for status/doctor and snapshots/users/services list wrappers.
- API 36 remains compile/target SDK.
- Native Android + privileged RootService/Binder architecture remains unchanged.
- No WebView, HTTP server, or arbitrary-shell bridge is introduced.
- Root-module-first runtime discovery and the RootService stream-drain crash fix are untouched.

## Post-delivery audit closure

The Phase 38 acceptance audit also namespaces saved review-state tokens (`add:` versus `user:`) instead of using a username-shaped sentinel. This prevents a legitimate Linux account name from being mistaken for the add-user flow while preserving saveable review selection state.
