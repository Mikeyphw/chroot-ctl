# CUX-02 — Home and chroot-centered hierarchy

CUX-02 of 7 replaces the placeholder Home surface with live chroot/session/job summaries and recent activity, makes zero-chroot state actionable, and establishes a selected-chroot context for Users, Services, Storage, and Snapshots.

The legacy missing `applyDefaultChrootToSelect` failure is closed with a context-aware selector adapter while the contextual screens are migrated. Chroot-scoped tools are removed from the global Tools sheet and entered from a selected chroot instead.

This overlay is intentionally applied with `--no-validate`; CUX-04 is the campaign mid-gate.
