# Devtool cumulative improvement ledger — Chrootctl CC05–CC07 append

**Source:** Oct 24 Chrootctl, BKX, Devtool snapshots; scoped to this delivered Chrootctl overlay. Add to the cumulative Devtool ledger when updating Devtool itself, not merely in chat.

| ID | Root issue / evidence | Affected projects | Proposed Devtool-native remedy | Status |
|---|---|---|---|---|
| DT-CC-09 | Existing `native-termux` root-module EXO jobs cannot execute under Ubuntu Actions; adoption doctor previously reported 10 blocked | Devtool/Chrootctl | Portable reviewed Android NDK Go CGO cross-build provider profile, with explicit host/job safety semantics | OPEN in Devtool, consumer host-target workaround implemented |
| DT-CC-10 | Same Go/CGO runtime and tmux were compiled separately on CI and release paths | Chrootctl/BKX/Devtool | First-class shared-producer/multiple-variant artifacts, provenance dependency and distinct edition manifests | Chrootctl consumer implemented; generalized Devtool OPEN |
| DT-CC-11 | Artifact receipts must distinguish source-bound CI candidates from independently attested or installed device releases | All consumer repos | Richer source/job/output/attestation linkage + verifiable Devtool run graph output | Chrootctl source implemented; hosted evidence PENDING |
| DT-CC-12 | Source-validation tests grep fixed YAML token sequences and break upon semantic workflow changes | Chrootctl/Devtool | Structured YAML/EXO source authority gates and source drift negative tests | Chrootctl updated; semantic generic Devtool support OPEN |
| DT-CC-13 | Local Source-only DAG planning cannot establish Android native static linking or Skybind privileged UID conformance | Chrootctl/Skybind/Devtool | Make hosted/build/device and independent consumer qualification clearly separate authorities | OPEN external validation |

Preserve prior Devtool improvement entries and original historical evidence. All native/device gates remain open pending actual externally grounded receipts.
