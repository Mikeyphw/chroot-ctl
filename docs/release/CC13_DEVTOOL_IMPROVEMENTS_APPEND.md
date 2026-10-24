# Devtool cross-consumer improvements — CC13 delta (2026-10-24)

**Evidence:** Chrootctl Actions run `40118588251`, job `120945024746`, Chrootctl `55b4513470e6e455944310805ea248d3b04756a8`, pinned Devtool `445044ac4941c1542754cc19d74ebd785b5d8595`. Actual run: `chrootctl_hosted_release.preflight` failed on `NDK revision differs`, 18 of 19 nodes skipped, zero artifacts. GitHub-hosted setup reported SDK/NDK install success but the Chrootctl selector could prefer ambient `ANDROID_NDK_HOME`. The precise inspected path was not in original logs; do not claim an independently established external NDK discrepancy.

| ID | Issue / evidence | Recommended Devtool / consumer response | Status |
|---|---|---|---|
| DT-CC13-01 | Host-inherited toolchain environment can supersede a pinned side-by-side SDK installation | Explicit toolchain selector with exact lock, source.properties and API checks; never downgrade silently. CC13 applies a consumer-side guard | CONSUMER FIXED; DEVTOOL REVIEW OPEN |
| DT-CC13-02 | A failed preflight returned `unknown_failure`, obscuring toolchain path/value | Preserve structured stage failure reason, expected/actual path and version in Devtool machine receipts and summary, without leaking secrets | OPEN |
| DT-CC13-03 | Release pipeline has correct skipped dependency propagation (1 failed + 18 skipped) but no artifact uploaded on preflight failure | Optionally upload separate redacted failure-only diagnostic receipts while keeping release candidate artifact upload strictly gated on complete success | OPEN |

Append these to the persistent cumulative Devtool improvements ledger during Devtool repository maintenance. This file is an additive Chrootctl-side ledger delta, not evidence of Devtool source modification.
