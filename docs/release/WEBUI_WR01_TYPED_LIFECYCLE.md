# WebUI Android-retirement WR01/12 — typed lifecycle convergence

WR01 migrates the lifecycle mutations that Android already executes through the preview-bound bridge contract.

## Delivered

- Start: `chroots.lifecycle.preview(action=start)` → `chroots.start`.
- Restart: `chroots.lifecycle.preview(action=restart)` → `chroots.restart`.
- Upgrade: newly exposed in WebUI, `chroots.lifecycle.preview(action=upgrade)` → `chroots.upgrade`.
- Remove: `chroots.lifecycle.preview(action=remove)` → `chroots.remove.execute`, with exact typed-name confirmation.
- Preview proof (`previewId`, `payloadHash`, `resourceRevision`) is mandatory before run.
- Runs use `app run --events ndjson`, therefore create persistent operation records and expose operation IDs/progress.
- Running lifecycle operations can be cancelled through the existing typed app cancellation endpoint.
- The former direct WebUI `mount`, remount composite, and `chroots remove --yes` paths for these overlapping Android actions are removed.

## Deliberately retained

`Stop`/unmount and `Rename` remain on their existing allow-listed CLI paths in WR01 because the current Android preview contract does not define `stop` or `rename` lifecycle actions. WR01 does not invent a second contract while claiming Android parity. They can be moved when/if a typed backend operation is established.

## Retirement invariant

For every lifecycle action shared with Android and declared preview-bound by the backend (`start`, `restart`, `upgrade`, `remove.execute`), WebUI now uses the same authoritative preview/action contract rather than a direct mutation command.
