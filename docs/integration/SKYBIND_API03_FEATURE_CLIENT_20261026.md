# API-03 chrootctl root consumer of Skybind API-02

**Baseline:** `a4b24129285266e56e0acca67dd325358f8f44a9` clean source.

A new **explicit root-only CLI command** delegates to the installed Skybind binary through the existing `skybind feature` protocol. This is not a new privileged network or Android-app transport. The existing chrootctl R1 `skybind-read` metadata gateway, sealed standard/rclone runtime editions, private config, backup/repository behavior and grant policy remain intact.

```sh
su -c 'chrootctl skybind-feature capabilities'
printf '%s\n' '{"api_version":1,"request_id":"check_001","arguments":{"name":"demo"}}' | su -c 'chrootctl skybind-feature call mount.status --stdin'
```

The executable path is fixed to `/data/adb/modules/skybind/system/bin/skybind`. Root ownership, ordinary-file mode, non-symlink components and non-writable ancestors are checked before execution; no shell, PATH search, user-selected executable, `su` invocation, logging of stderr, ambient remote/config access or argument-based credential fields. The consumer restricts commands to API-02's 16 managed feature operation names. Skybind independently checks root, installed capabilities, operation classes, preview/proofs, durable receipts, namespace ownership and duplicate mutation IDs. A stable request ID is required; denied but valid result receipts are preserved on stdout with nonzero status so operators can inspect original status after a lost reply.

**Device acceptance:** independently verify actual module binary, root process, SELinux, capabilities, read-only status and operation receipts. With a disposable namespace/mount and a preview proof, verify exactly one mutation, retry denial, receipt lookup, lost-reply reconciliation and denial from nonroot Android app process. Revoke/retest grants and R1 identities separately. DO NOT perform unreviewed mount or module mutations.

**Deferred:** a nonroot Android app transport and BKX cross-UID principal admission do not exist in API-02. This client neither asserts they do nor authorizes the BKX app to elevate.

**Devtool improvements ledger:** API03-CHROOT-01 — API-specific CLI integration must preserve machine-readable server receipts and fail closed on malformed/oversize, unsupported operation, changed module ownership. SOURCE IMPLEMENTED, local focused tests passed; hosted full compile/device/release qualification OPEN.

## Independent R2 correctness audit

R2 rejects duplicate top-level and nested request keys locally before the root CLI executes. It likewise rejects duplicate response keys and preserves a failed-operation receipt **only** when the producer emitted a complete typed Fault (`code`, `category`, `stage`, `message`, `retryable`) with the matching request ID. Missing or malformed errors must never be represented as safely reconcilable receipts. This hardening does not expand the 16-operation allowlist, authorize cross-UID calls or mutate the daemon.
