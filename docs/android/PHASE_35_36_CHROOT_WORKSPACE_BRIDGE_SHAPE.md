# Phase 35-36: Chroot Workspace and Bridge Shape Adapter

The Chroots destination is now a workspace launcher instead of a single scroll surface that renders every user, service, snapshot and raw diagnostic inline.

## Phase 35: workspace shell

- The top-level Chroots screen keeps search, filters and compact chroot cards.
- Opening a chroot enters an internal workspace with tabs: Overview, Services, Users, Snapshots and Advanced.
- Heavy management panels are no longer rendered directly on the top-level list.
- Destructive lifecycle removal and raw diagnostic details live in Advanced.

## Phase 36: bridge shape adapter

Some backend operations can return arrays where older Android code expected an object, or object wrappers where older Android code expected a top-level array. Android now accepts these compatible shapes for chroot status, doctor checks, snapshots, users and services.

User-facing errors no longer headline raw messages such as `Bridge response data was array; expected a JSON object`. The raw message remains available under technical details.

## Preserved contracts

- API 36 remains pinned.
- Strict lint remains enabled and only `OldTargetApi` is ignored.
- No WebView, HTTP server or arbitrary shell surface was added.
- Existing lifecycle, snapshot, user and service callbacks are preserved inside the workspace.
