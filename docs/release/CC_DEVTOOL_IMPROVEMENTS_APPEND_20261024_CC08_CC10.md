# Devtool cumulative improvement ledger delta — CC-08…CC-10

Additively append these to the repo-wide Devtool improvement ledger when that repository is next edited. Do not overwrite earlier findings. Source: chrootctl post-CC07 snapshot based on `c2207d1` replay; 2026-10-24.

| Item | Concrete evidence | Proposed change | Status |
|---|---|---|---|
| DT-CC08-01 | `test-go` Devtool legacy root-module stage initially omitted `./internal/skybindr1`, while the hosted DAG ran source-only `r1` gate | Include actual consumer Go tests in legacy and hosted DAGs; add scoped real-root-process provider test as independent follow-up | Source fix implemented in Chrootctl; independent device OPEN |
| DT-CC09-02 | Installer transitions source tested, but hosted release evidence had no installed-module/boot/SELinux proof schema | Add read-only installed runtime API26/source/manifest snapshot and strict no-fixture acceptance | Chrootctl probe + offline verifier implemented; device OPEN |
| DT-CC10-03 | GitHub candidate success could be misconstrued as root-device release proof | Introduce machine-readably explicit `NOT_DEVICE_QUALIFIED` acceptance ledger with per-edition matching, never promote self-reported unsigned JSON | Chrootctl reconciler implemented; independent authority OPEN |
| DT-CC10-04 | Portable Devtool graph needed an actual test lane separating mock Skybind contract and real consumer conformance | Model an explicit external consumer evidence node without claiming it ran from source-only CI | Chrootctl hosted test nodes added; Devtool framework enhancement proposed |
| DT-CC10-05 | Cross-edition staged activation and user-state preservation require proof through real root manager, not just host shell fixtures | Native device acceptance provider should capture edition, exact package/runtime hashes, real process proof, boots and rollback | OPEN device test/provider enhancement |

No Devtool repository file was modified in this overlay; this is an append-only proposal and Chrootctl document.
