# WebUI overlay 4/8 — Transfer

The Transfer section exposes the existing typed transfer bridge without a generic shell surface.

## Import

The WebUI accepts a local `.tar.zst` or encrypted `.enc` archive path, optional target name, rename/overwrite conflict policy, Auto/Streaming/Staged import strategy, encrypted-archive password, and explicit legacy-metadata compatibility opt-in. Every import is previewed through `transfer.import_preview` before `transfer.import` can run. The preview surfaces archive/expanded size, checksum integrity source, metadata fidelity, warnings and blocking conditions.

Legacy compatibility remains fail-closed unless the checkbox is explicitly enabled. Auto remains the recommended strategy; Streaming is exposed for space-constrained devices and Staged for users who explicitly want the staged path.

## Export

The export form selects a registered chroot, accepts an optional managed destination and optional encryption password, previews through `transfer.preview_export`, and executes `transfer.export`. Backend export continues to emit the SHA-256 sidecar. Password fields are password inputs and are cleared after preview failures and after every terminal execution path. Retry never retains a password; password-protected transfers require fresh password entry and a fresh preview.

## Progress and recovery

Import/export consume the persistent bridge NDJSON stream. The operation dialog renders percentage, phase/message, bytes done/total, entry count and current archive path when the backend supplies them. Storage preflight events display free bytes, expanded payload, safety reserve and required bytes. ENOSPC-style failures add actionable guidance to prefer Streaming where applicable, clean stale transfer artifacts, or free space on the filesystem containing the chroot root.

Operations can be cancelled by operation ID. Retry performs a fresh authoritative preview before executing again; if conditions changed and the new preview is blocked, execution does not resume. Editing any transfer field invalidates the previous preview.

## Security boundary

The WebUI continues to spawn only fixed chrootctl executable paths. Transfer operations use the versioned app bridge and allow-listed `transfer.*` operations; no arbitrary command or shell-string execution is introduced.

## Overlay boundary

Overlay 4 is deliberately local-only. `rclone://` and other URI-style destinations are rejected in the WebUI and remain owned by overlay 5. Successful exports display the backend-returned archive and checksum-sidecar paths; the UI does not invent encrypted suffixes or integrity state.
