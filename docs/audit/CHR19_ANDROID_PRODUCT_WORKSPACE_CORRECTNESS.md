# CHR19 Android product/workspace correctness

Overlay 19 of 20 closes the Android product/workspace correctness cluster. It focuses on user-visible contradictions and stale data traps rather than adding new backend power.

## Closed issues

- Home metrics and health rows now derive visible counts from the same non-stale Room rows, so the badge, metrics and launcher no longer disagree after a failed refresh.
- The Home recommended action now carries a destination and the hero renders it as a real CTA instead of only showing copy.
- The chroot launcher snapshot preview selects the target before previewing, so the ViewModel no longer drops launcher-originated snapshot previews.
- Cached/stale chroot workspaces keep showing available cached panes behind a stale-data warning; stale global state no longer hides Storage or Logs entirely.
- Storage status reports cross-device/mount-skipped size estimates, traversal errors, snapshot footprint, mismatched mounts and freshness metadata.
- Rootfs/cache/snapshot sizes use a same-device traversal so live bind mounts are skipped instead of recursively counted.
- Logs carry count/tail/truncated/freshness/read-error metadata and Android preserves cached log rows on failed refresh.
- Same-filter live-tail requests are serialized with a monotonic request token so older responses cannot overwrite a newer poll.
- Log rows avoid duplicated severity labels when the line already contains the level.
- Service journal read failures remain visible in the detail text instead of looking like a successful blank journal.

## Validation owner

`ValidateAndroidProductWorkspaceCorrectness` seals this overlay by checking the UI models, workspace policies, repository mappers, storage/log backend shape, source coverage ledger and this audit evidence.
