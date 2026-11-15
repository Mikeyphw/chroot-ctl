# Devtool S7 P04 — Go consumer migration (non-release)

The Go consumer is `Mikeyphw/chroot-ctl`, anchored to `main` at
`ff19b7b549b85f34aa2c8b9ca57b9aa20d380a37`. Its `chrootctl_go` target
already uses canonical Devtool orchestration. The supported Android/root-module
delivery target, `chrootctl_root_module`, is separate and **unchanged**.

This additive pilot uses the canonical S7 P02 `delivery adoption audit` and
`delivery adoption scaffold` commands from Devtool SHA
`416d24140c7f7a4b9833d7cb19df50ca7e7363b8`. It adds focused hosted tests
proving that a real Go consumer can use Devtool's source-bound audit without
writes, generate an exact-tree archive, reject stale source trees, and preserve
Go/Android target isolation. Its hosted gate also calls the same
`go run ./cmd/devtoolgates actions` / `r1` source contracts as the existing
source-contracts workflow.

The existing `.github/workflows/ci.yml`,
`.github/workflows/devtool-chrootctl-build.yml`, `go.mod`, `.devtool.toml`,
`devtoolw` and product code are unchanged. The new P04 gate is **non-release**:
no auto-merge, GitHub mutation, device install, local Android Gradle, signing
or new release authority. Existing PR-triggered release-candidate workflows
remain subject to their independent hosted policy.

The P04 feature-branch source SHA and new hosted run ID must be checked after
applying. A green P04 workflow is evidence for this **new PR HEAD**, not for the
old `main` SHA or for a formal release. GitHub Actions workflow IDs are only
assigned when GitHub registers a new workflow, so S7 P04 does **not** invent a
required-CI policy identifier in advance.
