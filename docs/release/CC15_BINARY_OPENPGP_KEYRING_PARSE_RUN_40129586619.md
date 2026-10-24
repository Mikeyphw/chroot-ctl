# CC15 — Binary OpenPGP keyring byte-preservation repair

**GitHub run:** https://github.com/Mikeyphw/chroot-ctl/actions/runs/40129586619  
**Source base:** `662d49b3f0c4c1489735e6752283d8da87b6328b` (CC14)  
**Status:** source hotfix only, hosted qualification still OPEN.

## Observed failure
Devtool hosted release DAG: 9 passed, 1 failed (`release.test-go`), 9 skipped. `internal/integrity/openpgp_test.go:109` reported `TestVerifyDetachedSignatureWithKeyringFileWithoutHostGPG: cannot parse signing keyring ... subkey signature invalid: unexpected EOF`. The NDK and tmux verification phases completed successfully, proving CC13 and CC14 passed their previous gates. No release ZIPs were uploaded.

## Root cause in source
`internal/integrity/integrity.go:parseKeyring` unconditionally called `bytes.TrimSpace(raw)` before passing a binary keyring to `openpgp.ReadKeyRing`. Randomly generated valid signatures can end in bytes that `bytes.TrimSpace` identifies as whitespace. Removing one or more such bytes truncates the final length-framed packet, yielding `unexpected EOF`. This explains the nondeterministic nature of the Go test failure; the exact random keyring bytes from the hosted failing test were not retained, so the root cause remains *strongly source-supported*, to be confirmed on the next hosted run.

## Repair
- Detect ASCII-armored public keys using a whitespace-trimmed view, preserving whitespace tolerance for ASCII armor.
- Feed **unaltered raw bytes** to `openpgp.ReadKeyRing` for non-armored binary keyrings. Do not loosen signature, signer, fingerprint, size or keyring validation.
- Add a test-only public GPG keyring whose final valid packet octet is 0x0a. New deterministic regression test compares the production parser against direct binary parsing and checks the pinned primary fingerprint identity. No secret/private key fixture is included.

## Evidence and gates
- Fixture was independently accepted by GnuPG (`gpg --import-options show-only --import`), ending 0x0a; trimming removes a valid byte.
- Source compilation and direct Go regression tests require the project's pinned `github.com/ProtonMail/go-crypto v1.4.1`, unavailable in the offline overlay authoring environment. Do not classify those tests PASS until GitHub or another environment with the dependency executes them.
- Source-format checks, exact original file SHA checks, byte-preservation static assertions, and fixture provenance can be tested locally without dependencies.
- Hosted CI: the next run must pass `release.test-go`, all 19 DAG nodes, complete both edition ZIPs and reconcile machine receipts. Android installation/Skybind real-process evidence remains independently pending.

## Devtool ledger addition
**DT-CC15-01 — High-signal test failure reporting for binary crypto fixtures**: Devtool correctly attributes the failure to `release.test-go`, but the hosted failure excludes reproducible test seed and fixture bytes. Retain redacted deterministic fixture/test-case diagnostics and a failure-only machine receipt artifact without weakening release publication gates. Consumer fix: deterministic public fixture and preservation test. Devtool-side diagnostics improvement: OPEN.
