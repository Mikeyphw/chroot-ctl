# CC-08–CC-10: Skybind consumer, edition transitions, real-device evidence

**Implementation state:** automated offline/hosted checks are implemented. **NOT a personal-release qualification**. No physical Android installation, real Skybind root-module grant, GitHub native build or independently signed installed artifact evidence was obtained in this delivery.

## Architecture and runtime promise

- Both packages use identical `chrootctl` backend bytes, same module ID, API 26 and read-only `skybind-read`. Neither depends on the presence of the optional embedded `rclone` binary for Skybind R1. `scripts/ci/verify-dual-release.go` proves the shared Chrootctl backend hash and opposite rclone membership in the ZIP/runtime/edition manifests.
- Skybind R1 is a **separate read-only, opt-in** interface, not a fallback binary. The production endpoint names remain fixed; the `readVia` helper is private to `internal/skybindr1` and exists solely for network-equivalent mock testing. Client requests forbid arbitrary `cat`, `rcat`, `moveto`, `deletefile`, `serve`, general `copy` and `sync`, before any socket access. A denied gateway response or missing grant never falls back to native rclone.
- The mocked grant → gateway conformance tests prove only Chrootctl-side JSON, token, grant rejection, cancellation and allowlist behavior. Skybind real-caller UID/SELinux identity, policy-enforced remote-scoped grant, revocation and durable streamed transfer correctness **remain OPEN**.
- The R3/R4 Skybind provider streaming commands and immutable publication are **NOT QUALIFIED**. Chrootctl Standard must report unavailable native-rclone workflows unless another independently authorized provider is configured; it must not pretend `skybind-read` is a complete rclone replacement. The embedded edition retains native rclone while explicit Skybind read access remains independent.

## New automated gates

| Roadmap | Actual code/test | Scope | State |
|---|---|---|---|
| CC-08 R1 allowlist and grant/gateway | `internal/skybindr1/cc08_consumer_conformance_test.go`; `TestCC08*` | mocked sockets, positive read and negative mutation/deny/cancel | SOURCE TEST IMPLEMENTED; REAL AUTHORITY PENDING |
| CC-08 same backend both variants | `scripts/ci/verify-dual-release.go`, `verify-editions` Devtool DAG | embedded native runtime equality, no rclone in Standard | IMPLEMENTED; GITHUB BUILD PENDING |
| CC-09 switch both ways and rollback | `internal/module/cc09_upgrade_acceptance_test.go`; existing `release_edition_security_test.go` | offline staged root-manager simulation, valid old active, user state retention | TESTS IMPLEMENTED; DEVICE REBOOT PENDING |
| CC-09 active-installed snapshot | `scripts/device/cc09-module-snapshot.sh` plus `cc09_device_snapshot_test.go` | read-only runtime inventory, API26, source/Devtool identity, SELinux/boot markers | PROBE IMPLEMENTED; DEVICE CAPTURE PENDING |
| CC-10 hosted/device reconciliation | `scripts/ci/reconcile-qualification.go` + tests | reject byte mismatch / fixture proof / wrong source+edition; do not self-attest | IMPLEMENTED; EXTERNAL ACCEPTANCE PENDING |
| CC-10 full roadmap CC-00…CC-10 | source and hosted check matrix in this document | promise evidence status carried forward | PARTIAL (cannot close without CI/physical device) |

The hosted Devtool DAG now adds separate `test-skybind-consumer`, `test-edition-upgrade` stages, runs the offline reconciler test inside `test-verifier` and records `release-qualification.json` from the completed GitHub-hosted candidate. The reconciliation always uses `NOT_DEVICE_QUALIFIED` until independent device authority exists.

## Running the read-only physical-device probe

On an Android device with the candidate already installed and boot completed, inspect the script, then run it from a root shell *from the module's supported process context*, e.g. on-device Termux (adjust to the actual checked-out tree):

```sh
su -c 'sh /data/local/tmp/cc09-module-snapshot.sh' > standard-device.json
```

This is just an example for an explicitly copied reviewed script, **not** a claim that Termux `su` matches the privileged Chrootctl service process. Do not copy secrets, root config or live chroots. No built-in automatic root grant, install or restart is performed. Capture the Standard snapshot, then repeat after intentionally installing Embedded and rebooting into it (save separately as `rclone-device.json`). The script reads `/data/adb/modules/chrootctl`, requires `sys.boot_completed=1`, API ≥26, SELinux Enforcing, UID 0, sealed SHA-256 runtime, matching source+Devtool identity and no unexpected runtime files. It emits only fixed identities/checksums/boot ID and unqualified status; it does not run a Skybind command.

Offline fixture override `CHROOTCTL_DEVICE_PROBE_FIXTURE=1 CHROOTCTL_DEVICE_PROBE_ROOT=<fixture-root>` is solely for source-level test environments. `mode=fixture` is *always* rejected by the release reconciler.

After the GitHub hosted workflow has produced its artifact directory, run:

```sh
go run scripts/ci/reconcile-qualification.go \
  --hosted-evidence out/hosted-evidence \
  --device-standard standard-device.json \
  --device-rclone rclone-device.json \
  --output out/hosted-evidence/device-reconciliation.json
```

Require no `FAIL_CC10_RECONCILE`, then still independently verify GitHub origin/attestation, module ZIP byte→installed runtime provenance, Android 16 KiB behavior, boots and root-manager integration, and independently approved `skybind-read` R1 calls **from real Chrootctl root-module process** with allowlisted prefixes, revocation and rejection. Neither JSON artifact nor test-only fake socket by itself constitutes qualified external evidence.

## Remaining acceptance (unqualified)

- [ ] Fresh exact-SHA GitHub-hosted NDK/Tmux/bclone/CGO cross-compile; both ZIPs downloaded, hashes + optional attestations verified and installed.
- [ ] Standard and Rclone clean install, same-edition update, cross-edition switch both directions, rollback/downgrade, interrupted install and second-boot health, live WebUI and user-state integrity on rooted Android.
- [ ] Actual source-to-installed ELF/package provenance and SELinux caller identity, not just a user-controlled script output.
- [ ] Skybind R1 real root-module grant, scoped list/stat, revocation, unauthorized caller rejection for **each** edition. Keep scope and remote credentials private.
- [ ] Native embedded rclone disposable-remote import/export and checksum/immutable publication tests; Skybind R3/R4 remains unavailable until the provider itself implements and qualifies the exact stream/write semantics.
- [ ] Final cumulative ledger incorporation and evidence-backed promise audit for CC-00…CC-10; do not claim final release until all applicable gates pass.

## Implementation constraints

CC-09 script must never change modules or persistent state. CC-10 reconciler refuses inconsistent snapshots and ZIP digest tampering but cannot distinguish an operator-created JSON forgery without independent trust anchors; accordingly its only terminal classification is `NOT_DEVICE_QUALIFIED`. Source test fixtures cannot satisfy real device gates by construction. Preserve older accepted evidence; do not reinterpret deferred/manual tests as failed automated tests.
