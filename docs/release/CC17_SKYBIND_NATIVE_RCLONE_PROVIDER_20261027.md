# CC17 — Explicit Skybind native-rclone provider for Chrootctl

Source base: Chrootctl `2118e6ddd21f4bf657dcf53f24b162b41ba08054`, Skybind reference `091a98eed2985647416fdd55ed2d281c41dcc2ae` (both October 27 2026 snapshots). This is source implementation evidence, **not** a newly hosted Android candidate, installed-pair acceptance or independent Skybind signature attestation.

## Architectural decision

API-01 exposes `/system/bin/skybind-rclone` as a deterministic wrapper for its own native engine, with default root-private credentials `/data/adb/skybind/config/rclone.conf`. Direct rclone transfers require no Skybind API-02 or legacy R1 token. API-03 remains the separate root-local interface for Skybind-managed mounts, namespace lifecycle, durable managed receipts and other managed features. Nothing in this patch edits those APIs or broadens their authority.

Chrootctl's remote listing, import, export, transfers and archive stream paths already call `internal/rcloneops.RuntimeFromEnvironment()`, so selecting the trusted wrapper there reuses all existing transfer validation, checksum, cancellation, retry and progress handling. **No independent provider implementation is duplicated.**

## How selection works

No implicit discovery of `/system/bin/rclone` for root processes. Provider selection is explicit:

* Default/unconfigured: existing `chrootctl` rclone discovery, including its bundled runtime and existing explicit overrides.
* `CHROOTCTL_RCLONE_PROVIDER=skybind`: root-only, fail-closed; resolve ONLY `/data/adb/modules/skybind/system/bin/skybind-rclone`, its manifest-attested native engine and private Skybind configuration. Never fall back to Chrootctl's bundled rclone on missing/mismatched resources.
* Root-only persistent choice: `/data/adb/chrootctl/rclone/provider` containing `skybind\n` or `chrootctl\n`, owned by root, mode `0600`, within root-owned non-writable parent. Read by any newly started root CLI/WebUI instance; explicit `CHROOTCTL_RCLONE_PROVIDER` overrides for one invocation.
* `CHROOTCTL_RCLONE_PROVIDER=chrootctl`: force existing legacy discovery for this invocation, even with a persistent Skybind selection.
* Invalid/malformed provider or conflicting `CHROOTCTL_RCLONE_PATH`, `CHROOTCTL_RCLONE_CONFIG` or `CHROOTCTL_RCLONE_ALLOW_PATH` in Skybind mode: fail rather than guess.

An operator helper at `scripts/device/select-skybind-rclone-provider.sh` checks/sets the persistent selection atomically, retaining a root-private backup when replacing a previous file. Running this script is **not** part of release/module installation and is never automatic. Reopen the running WebUI backend after a change.

## Security and compatibility

Before Chrootctl executes a privileged Skybind launcher, it checks root-owned/non-symlink/non-writable directory components, the installed `id=skybind` module identity, `skybind.manifest.json`, the manifested runtime provenance digest, declared `arm64` engine path, checksums and sizes for the launcher alias, public `rclone`, native engine and provenance file, identical alias and launcher identities, and native engine ARM64 ELF header. It separately requires Skybind's root-owned, non-symlink, private, nonempty `rclone.conf` and containing directory. Tests reject corrupt or absent resources. This attests *consistency with installed root-owned files*; it does **not** independently prove a build provenance/signing authority or installed device acceptance. Root compromise is out of scope.

In Skybind mode, `chrootctl remotes config import` is disabled. It must not import credentials into Chrootctl's config while Skybind owns the selected remote definitions. Skybind's wrapper resets `RCLONE_CONFIG` to its private path, and Chrootctl also passes its validated explicit `--config` path. No secrets are copied between stores.

**Write authority:** direct native rclone operations execute with the root caller's privileges, including potential remote writes. They are not confined to legacy R1 read-only grants. The operator must trust the module and select this mode deliberately. No auto-mounts, auto-transfers, automatic credential exports, API-fallback or SELinux changes are added.

**Skybind module transitions:** `skybind.manifest.json` and `runtime.provenance.json` must continue exposing API-01's canonical paths, schema and hashes. A future Skybind ABI or file layout change should be recognized as a failed provider check, then handled in source with an explicit compatible update; do not bypass the check by selecting arbitrary paths.

## Commands after a new Chrootctl build is installed

```sh
# From the updated Chrootctl repo checkout, read-only:
su -c "sh '$PWD/scripts/device/select-skybind-rclone-provider.sh' --check"

# One-command, non-persistent, root-only smoke (the installed binary must contain CC17):
su -c 'CHROOTCTL_RCLONE_PROVIDER=skybind /data/adb/modules/chrootctl/runtime/arm64-v8a/chrootctl remotes status --json'

# To persistently use Skybind in newly started CLI/WebUI processes:
su -c "sh '$PWD/scripts/device/select-skybind-rclone-provider.sh' --use skybind"
su -c "sh '$PWD/scripts/device/select-skybind-rclone-provider.sh' --check"

# Roll back the selection without deleting remotes or restoring old binaries:
su -c "sh '$PWD/scripts/device/select-skybind-rclone-provider.sh' --use chrootctl"
```

If status reports unavailable, verify the exact installed Skybind API-01 module, its manifests, root file modes, engine, private config and absence of conflicting overrides. **Do not copy credentials, relax permissions, change SELinux, or silently fall back.**

## Promise-by-promise evidence

| Promise | Source evidence | Status |
|---|---|---|
| Default Chrootctl runtime unchanged | existing discovery branch in `runtime.go`; root-only Skybind branch opt-in | Implemented in source, device open |
| Skybind native wrapper without API or R1 | verified fixed paths / provenance in `skybind_provider.go`; `Runtime.Executable` consumed by existing remote operations | Implemented in source, installed interaction open |
| Skybind private config, no credential copying | `Config` uses Skybind root-private path; `ImportConfig` rejects Skybind choice | Implemented in source, device open |
| Fail-closed identity, no PATH fallback | manifest/source checks, strict root file modes, symlink, ELF arm64, no alternate candidate | Unit-tested, installed security open |
| Persistent opt-in and safe rollback | root-only selector, atomic rename, private backup, environment override | Locally fixture-tested, device open |
| Provider visible in status | `RuntimeInfo.Provider`, `RcloneStatus.provider` | Implemented, CLI/WebUI receipt open |
| API-02/API-03 and R1 isolation | zero source changes to these adapters | Source-preserved; their external gates remain open |
| Hosted build and real transfers | Devtool full release, installed APK/module checks, dry-run/disposable remote execution | **OPEN** |

## External acceptance gates (not closed by local tests)

1. Apply the overlay to the exact matching repository checkout, run Devtool validation and all Go tests in an environment with required dependencies; build hosted Android API26 packages.
2. Independently verify new Standard/Rclone ZIP checksums, version/edition metadata and native ARM64 runtime, then install the chosen edition using the user's normal trusted root-manager process.
3. Verify that Skybind API-01 is actually installed, with canonical wrapper, native ELF and private config. Test root-only `remotes status --json` through explicit Skybind mode, confirm `provider: "skybind"`, no fallback, no secret disclosure.
4. Exercise a disposable, independently approved **read-only** remote directory listing; optionally a small authorized upload/download/archive roundtrip after separate approval. Check hashes, retries, cancellation and receipts without using personal folders.
5. Apply persistent selection, reopen WebUI backend, verify selected provider reflected in new processes; roll back to `chrootctl`, verify bundled-runtime behavior and preserved on-disk configurations.
6. Repeat on Rclone edition if separate edition acceptance is required. Old R1 live grant/revoke and API-03 managed-mount gates remain separate.
