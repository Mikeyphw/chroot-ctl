# Rclone remote import/export

chrootctl uses credential-free `rclone://REMOTE/path` locations. The URI contains only the configured remote name and object path; provider credentials remain exclusively in `/data/adb/chrootctl/rclone/rclone.conf` (root-owned mode `0600`). Unsafe remote names, URI credentials, query strings, and fragments are rejected.

## Runtime

The root module can bundle an Android/arm64 `rclone` executable at:

`/data/adb/modules/chrootctl-magisk/runtime/arm64-v8a/rclone`

`repoctl build-runtime` automatically adds a trusted rclone executable from `CHROOTCTL_RCLONE_PATH`, `out/rclone/arm64-v8a/rclone`, or a compatible local `rclone` executable. Set `CHROOTCTL_REQUIRE_RCLONE=1` to make a missing rclone runtime a build failure. `scripts/install-rclone-android-runtime.sh out/rclone` builds the pinned rclone release from verified source/vendor archives for Android arm64.

Privileged runtime discovery does not silently trust an arbitrary PATH executable. `CHROOTCTL_RCLONE_PATH` is the explicit override for testing/custom deployments.

## Configuration

Import a normal decrypted rclone config:

```sh
chrootctl remotes config import /path/to/rclone.conf
```

Android stages the selected document first and asks the root backend to publish it. After a managed staged config is successfully copied into the private config location, chrootctl removes the staged credential-bearing copy, its staged checksum sidecar, and its managed-artifact registry entry. Encrypted `RCLONE_ENCRYPT_V0:` configs are rejected because chrootctl does not persist an rclone config password. Imported configs are size-limited and atomically published with mode `0600`.

Useful commands:

```sh
chrootctl remotes status
chrootctl remotes list
chrootctl remotes ls rclone://drive/chroots
```

## Remote import

```sh
chrootctl chroots import rclone://drive/chroots/androidos.tar.zst
```

`auto` is storage-aware for both local and remote imports. Before extraction chrootctl inspects free space on the actual chroot target filesystem and the temporary filesystem, estimates the expanded tar/rootfs size, applies a safety reserve, and selects `staged` only when the staged layout is expected to fit safely. Otherwise it selects `streaming`. An explicit `staged` request fails early with `INSUFFICIENT_IMPORT_SPACE` and actionable target/temp capacity details when the estimate cannot fit.

For a remote streaming import, the backend reads the remote archive once for checksum/manifest/topology preflight and a second time for extraction, verifying that the compressed archive SHA-256 is identical on both passes. Neither the compressed remote object nor a decompressed tar is persisted locally. A remote staged import downloads one compressed copy and then uses the local staged pipeline.

Imports support:

```sh
--import-strategy auto|staged|streaming
```

`auto` selects streaming when conservative free-space estimates say a staged decompressed tar plus extracted rootfs would be unsafe. After the manifest provides the exact expanded byte count, chrootctl performs a second target-filesystem capacity check before creating the extraction stage, so an underestimated archive fails before rootfs extraction rather than at `ENOSPC`.

If `<archive>.sha256` exists remotely it must verify. If it is absent, SHA-256 is computed on import and the result is explicitly marked `computed_on_import`. Legacy pre-CHR09 metadata archives still require `--allow-legacy-metadata`.

## Remote export

```sh
chrootctl --name androidos transfer export rclone://drive/chroots/androidos.tar.zst
```

Remote export streams `tar --zstd` (and optional openssl encryption) directly into `rclone rcat`; it does not materialize a local compressed archive. When encryption is requested, a destination that does not already end in `.enc` is normalized to `<destination>.enc`, and its checksum sidecar is `<destination>.enc.sha256`.

Before upload, chrootctl refuses to publish over an existing final archive or checksum sidecar. Data is first uploaded to unique `.partial-*` remote objects. chrootctl computes SHA-256 while streaming, re-reads the uploaded temporary object and verifies both its byte count and SHA-256 **before publication**, uploads the checksum sidecar, then promotes both objects with immutable remote moves so a concurrently-created destination cannot be overwritten. Final remote size and sidecar contents are re-read and verified before success is returned. Failed/unverified partial publications are cleaned up; pre-existing remote objects are never removed as cleanup.

Rclone JSON transfer statistics are translated into chrootctl progress events, including bytes transferred/total, rate, ETA, file counts, and the current remote object when rclone supplies them. Cancellation terminates the child rclone operation. Diagnostics redact common credential/token forms and the private config path.
